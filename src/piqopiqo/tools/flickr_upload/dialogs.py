"""Dialogs and launch flow for Flickr upload."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
)

from piqopiqo.cache_paths import get_flickr_cache_dir, get_flickr_token_file_path
from piqopiqo.ssf.settings_state import (
    RuntimeSettingKey,
    UserSettingKey,
    get_runtime_setting,
    get_user_setting,
)

from .albums import FlickrAlbumPlan, fetch_album_info
from .auth import create_flickr_client, token_file_exists
from .constants import (
    FOLDER_STATE_LAST_FLICKR_ALBUM_ID,
    STAGE_ADD_TO_ALBUM,
    STAGE_ALBUM_CHECK,
    STAGE_UPLOAD,
    TOKEN_VALIDATION_ERROR_TEXT,
)
from .manager import FlickrUploadManager, FlickrUploadResult
from .workers import (
    FlickrAlbumCheckWorker,
    FlickrLoginWorker,
    FlickrTokenValidationWorker,
)

if TYPE_CHECKING:
    from piqopiqo.main_window import MainWindow
    from piqopiqo.model import ImageItem


class FlickrPreflightDialog(QDialog):
    """Preflight dialog showing upload scope and token-file state."""

    def __init__(
        self,
        *,
        visible_count: int,
        token_file_path: str,
        token_exists: bool,
        album_text: str = "",
        album_error: str = "",
        album_display_plan: FlickrAlbumPlan | None = None,
        show_album_link: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Upload to Flickr")
        self.setModal(True)
        self.setMinimumWidth(560)

        self.selected_action: str | None = None
        self.selected_album_text: str = str(album_text or "")
        self._token_exists = bool(token_exists)

        layout = QVBoxLayout(self)

        count_label = QLabel(f"Visible photos to upload: {int(visible_count)}")
        count_label.setWordWrap(True)
        layout.addWidget(count_label)

        token_status = "present" if token_exists else "missing"
        token_label = QLabel(
            f"Token file state: {token_status}\nPath: {token_file_path}"
        )
        token_label.setWordWrap(True)
        layout.addWidget(token_label)

        self.album_input: QLineEdit | None = None
        self.album_info_label: QLabel | None = None
        self.album_link_label: QLabel | None = None
        self.album_error_label: QLabel | None = None

        if self._token_exists:
            album_row = QHBoxLayout()
            album_label = QLabel("Add to album (Optional)")
            album_row.addWidget(album_label)

            help_btn = QToolButton(self)
            help_btn.setText("?")
            help_btn.setFixedSize(20, 20)
            help_btn.setToolTip(
                "Album title (new or existing), Flickr Album ID or Flickr Album URL"
            )
            help_btn.setStyleSheet(
                "QToolButton { border: 1px solid palette(mid); border-radius: 10px;"
                " font-weight: bold; font-size: 11px; }"
            )

            album_row.addWidget(help_btn)
            album_row.addStretch()
            layout.addLayout(album_row)

            self.album_input = QLineEdit(self)
            self.album_input.setText(self.selected_album_text)
            self.album_input.textChanged.connect(self._on_album_text_changed)
            layout.addWidget(self.album_input)

            self.album_info_label = QLabel(self)
            self.album_info_label.setWordWrap(True)
            if (
                album_display_plan is not None
                and album_display_plan.is_existing_album()
            ):
                display_title = album_display_plan.album_title or "<untitled>"
                self.album_info_label.setText(
                    f"Album: '{display_title}' (ID: {album_display_plan.album_id})"
                )
                self.album_info_label.show()
            else:
                self.album_info_label.hide()
            layout.addWidget(self.album_info_label)

            self.album_link_label = QLabel(self)
            self.album_link_label.setTextFormat(Qt.TextFormat.RichText)
            self.album_link_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextBrowserInteraction
            )
            self.album_link_label.setOpenExternalLinks(True)
            if (
                show_album_link
                and album_display_plan is not None
                and album_display_plan.album_url
            ):
                url = album_display_plan.album_url
                self.album_link_label.setText(
                    f'<a href="{url}" style="color:#1f6feb;">{url}</a>'
                )
                self.album_link_label.show()
            else:
                self.album_link_label.hide()
            layout.addWidget(self.album_link_label)

            self.album_error_label = QLabel(self)
            self.album_error_label.setStyleSheet("color: red;")
            self.album_error_label.setWordWrap(True)
            layout.addWidget(self.album_error_label)
            self._set_album_error(album_error)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_btn)

        action_label = "Upload" if token_exists else "Login to Flickr"
        self.action_btn = QPushButton(action_label)
        self.action_btn.clicked.connect(self._on_action)
        button_row.addWidget(self.action_btn)

        layout.addLayout(button_row)

    def _set_album_error(self, message: str) -> None:
        if self.album_error_label is None:
            return
        text = str(message or "").strip()
        if text:
            self.album_error_label.setText(text)
            self.album_error_label.show()
            return
        self.album_error_label.clear()
        self.album_error_label.hide()

    def _on_album_text_changed(self, _value: str) -> None:
        self._set_album_error("")

    def _on_action(self) -> None:
        self.selected_action = "upload" if self._token_exists else "login"
        if self.album_input is not None:
            self.selected_album_text = str(self.album_input.text() or "")
        self.accept()


class FlickrLoginProgressDialog(QDialog):
    """Indeterminate login progress dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Upload to Flickr")
        self.setModal(True)
        self.setMinimumWidth(460)

        self._worker: FlickrLoginWorker | None = None
        self.error_message: str = ""
        self._finished = False

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Logging in to Flickr in your browser...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        button_row.addWidget(self.cancel_btn)
        layout.addLayout(button_row)

    def start(self, worker: FlickrLoginWorker) -> None:
        self._worker = worker
        worker.signals.finished.connect(self._on_finished)
        worker.signals.cancelled.connect(self._on_cancelled)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_finished(self, _result) -> None:
        self._finished = True
        self.accept()

    def _on_cancelled(self) -> None:
        self._finished = True
        self.reject()

    def _on_error(self, message: str) -> None:
        self._finished = True
        self.error_message = str(message)
        self.accept()

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()
        self.reject()

    def closeEvent(self, event) -> None:
        if not self._finished and self._worker is not None:
            self._worker.request_cancel()
        super().closeEvent(event)


class FlickrUploadProgressDialog(QDialog):
    """Token-validation + upload progress/result dialog."""

    manager_started = Signal(object)  # FlickrUploadManager
    manager_finished = Signal(object)  # FlickrUploadManager

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        exiftool_path: str,
        upload_items: list[dict],
        album_text: str,
        cached_album_plan: FlickrAlbumPlan | None,
        set_folder_album_id_callback,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Upload to Flickr")
        self.setModal(True)
        self.setMinimumWidth(620)

        self._api_key = api_key
        self._api_secret = api_secret
        self._exiftool_path = exiftool_path
        self._upload_items = upload_items
        self._album_text = str(album_text or "")
        self._cached_album_plan = cached_album_plan
        self._set_folder_album_id_callback = set_folder_album_id_callback

        self._manager: FlickrUploadManager | None = None
        self._token_worker: FlickrTokenValidationWorker | None = None
        self._album_worker: FlickrAlbumCheckWorker | None = None
        self._finished = False
        self._current_stage = "Validating Flickr token..."
        self._album_action_text = ""

        self.invalid_token = False
        self.result: FlickrUploadResult | None = None
        self.album_validation_error: str = ""
        self.resolved_album_plan: FlickrAlbumPlan | None = None

        layout = QVBoxLayout(self)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        layout.addWidget(self.status_label)

        self.stage_label = QLabel("")
        self.stage_label.setWordWrap(True)
        layout.addWidget(self.stage_label)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.album_action_label = QLabel("")
        self.album_action_label.setWordWrap(True)
        self.album_action_label.hide()
        layout.addWidget(self.album_action_label)

        self.details = QTextEdit(self)
        self.details.setReadOnly(True)
        self.details.hide()
        layout.addWidget(self.details, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        button_row.addWidget(self.cancel_btn)

        self.ok_btn = QPushButton("OK")
        self.ok_btn.setEnabled(False)
        self.ok_btn.hide()
        self.ok_btn.clicked.connect(self.accept)
        button_row.addWidget(self.ok_btn)

        layout.addLayout(button_row)
        self._update_stage_label()
        self._sync_height_to_content()

    def _update_stage_label(self) -> None:
        stage_text = self._current_stage.strip() or "-"
        if stage_text == STAGE_ADD_TO_ALBUM and self._album_action_text:
            stage_text = f"{stage_text} - {self._album_action_text}"
        self.stage_label.setText(stage_text)

    def _sync_height_to_content(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self.adjustSize()
        target_height = self.sizeHint().height()
        if target_height > 0:
            self.setFixedHeight(target_height)

    def start(self) -> None:
        worker = FlickrTokenValidationWorker(
            api_key=self._api_key,
            api_secret=self._api_secret,
        )
        self._token_worker = worker
        worker.signals.finished.connect(self._on_token_validated)
        worker.signals.cancelled.connect(self._on_validation_cancelled)
        worker.signals.error.connect(self._on_validation_error)
        QThreadPool.globalInstance().start(worker)

    def _on_token_validated(self, valid: bool) -> None:
        if not valid:
            self.invalid_token = True
            self._finished = True
            QMessageBox.warning(self, "Upload to Flickr", TOKEN_VALIDATION_ERROR_TEXT)
            self.reject()
            return

        self._current_stage = STAGE_ALBUM_CHECK
        self._album_action_text = ""
        self._update_stage_label()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("")
        self._sync_height_to_content()

        album_text = self._album_text.strip()
        if not album_text:
            self._set_folder_album_id_callback(None)
            self.resolved_album_plan = FlickrAlbumPlan()
            self._start_upload_manager(FlickrAlbumPlan())
            return

        worker = FlickrAlbumCheckWorker(
            api_key=self._api_key,
            api_secret=self._api_secret,
            album_text=album_text,
            cached_plan=(
                self._cached_album_plan.to_dict()
                if self._cached_album_plan is not None
                else None
            ),
        )
        self._album_worker = worker
        worker.signals.finished.connect(self._on_album_checked)
        worker.signals.cancelled.connect(self._on_album_check_cancelled)
        worker.signals.error.connect(self._on_album_check_error)
        QThreadPool.globalInstance().start(worker)

    def _on_album_checked(self, plan: FlickrAlbumPlan) -> None:
        self.resolved_album_plan = plan

        if plan.is_existing_album():
            self._set_folder_album_id_callback(plan.album_id)

        self._start_upload_manager(plan)

    def _start_upload_manager(self, album_plan: FlickrAlbumPlan) -> None:
        self.progress_bar.setRange(0, max(1, len(self._upload_items)))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0/%v")
        self._current_stage = STAGE_UPLOAD
        self._album_action_text = ""
        self._update_stage_label()
        self._sync_height_to_content()

        manager = FlickrUploadManager(
            api_key=self._api_key,
            api_secret=self._api_secret,
            exiftool_path=self._exiftool_path,
            token_cache_dir=str(get_flickr_cache_dir()),
            max_workers=int(
                get_runtime_setting(RuntimeSettingKey.FLICKR_UPLOAD_MAX_WORKERS)
            ),
            album_plan=album_plan,
            on_album_id_resolved=self._set_folder_album_id_callback,
            parent=self,
        )
        self._manager = manager
        self.manager_started.emit(manager)
        manager.stage_changed.connect(self._on_stage_changed)
        manager.progress.connect(self._on_progress)
        manager.status.connect(self._on_status)
        manager.album_status.connect(self._on_album_status)
        manager.finished.connect(self._on_finished)
        manager.start(self._upload_items)

    def _on_album_check_cancelled(self) -> None:
        self._finished = True
        self.reject()

    def _on_album_check_error(self, message: str) -> None:
        self._finished = True
        self.album_validation_error = str(message)
        QMessageBox.warning(self, "Upload to Flickr", self.album_validation_error)
        self.reject()

    def _on_validation_cancelled(self) -> None:
        self._finished = True
        self.reject()

    def _on_validation_error(self, message: str) -> None:
        self._finished = True
        QMessageBox.warning(self, "Upload to Flickr", str(message))
        self.reject()

    def _on_stage_changed(self, stage: str) -> None:
        if self._finished:
            return
        self._current_stage = str(stage or "").strip() or "-"
        if stage != STAGE_ADD_TO_ALBUM:
            self._album_action_text = ""
        self._update_stage_label()
        self.album_action_label.clear()
        self.album_action_label.hide()
        self._sync_height_to_content()

    def _on_progress(self, completed: int, total: int) -> None:
        if self._finished:
            return
        if int(total) <= 0:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("")
            return
        self.progress_bar.setRange(0, int(total))
        self.progress_bar.setValue(max(0, int(completed)))
        self.progress_bar.setFormat(f"{completed}/{total}")

    def _on_status(self, _message: str) -> None:
        # Keep running-step text driven by stage_changed only to avoid stale
        # previous-stage status updates overriding the current step label.
        return

    def _on_album_status(self, message: str) -> None:
        if self._finished:
            return
        text = str(message or "").strip()
        if self._current_stage != STAGE_ADD_TO_ALBUM:
            return
        self._album_action_text = text
        self._update_stage_label()
        self.album_action_label.clear()
        self.album_action_label.hide()
        self._sync_height_to_content()

    def _on_finished(self, result: FlickrUploadResult) -> None:
        self._finished = True
        self.result = result

        if self._manager is not None:
            self.manager_finished.emit(self._manager)

        if result.album_id:
            self.resolved_album_plan = FlickrAlbumPlan(
                raw_text=self._album_text.strip(),
                album_id=result.album_id,
                album_title=result.album_title,
                user_nsid=result.album_user_nsid,
                album_url=result.album_url,
                is_create=False,
            )

        self.cancel_btn.setEnabled(False)
        self.stage_label.hide()
        self.progress_bar.hide()
        self.album_action_label.clear()
        self.album_action_label.hide()
        self.status_label.show()
        self.details.clear()
        self.details.hide()

        lines: list[str] = []
        if result.fatal_error:
            self.status_label.setText("Upload failed.")
            lines.append(result.fatal_error)
        elif result.cancelled:
            self.status_label.setText("Upload cancelled.")
            lines.append(
                "Uploaded "
                f"{result.uploaded_count}/{result.total_photos} "
                "photo(s) before cancellation."
            )
        elif result.failures:
            self.status_label.setText("Upload completed with issues.")
            lines.append(
                f"Uploaded {result.uploaded_count}/{result.total_photos} photo(s)."
            )
            lines.append(f"Reset date: {result.reset_date_count}")
            lines.append(f"Make public: {result.made_public_count}")
        else:
            self.status_label.setText("Upload completed successfully.")
            lines.append(
                f"Uploaded {result.uploaded_count}/{result.total_photos} photo(s)."
            )
            lines.append(f"Reset date: {result.reset_date_count}")
            lines.append(f"Make public: {result.made_public_count}")

        if result.album_id:
            display_title = result.album_title or result.album_id
            lines.append(f"Album: {display_title} ({result.album_id})")
            if result.album_created:
                lines.append(
                    "Album operation: created album then added uploaded photos."
                )
            elif result.album_added_count:
                lines.append(f"Added to album: {result.album_added_count} photo(s).")

        if result.failures:
            lines.append("")
            lines.append("Failures:")
            for failure in result.failures:
                base_name = (
                    os.path.basename(failure.file_path)
                    if failure.file_path
                    else "<unknown>"
                )
                lines.append(f"- [{failure.stage}] {base_name}: {failure.message}")

        if lines:
            self.details.setPlainText("\n".join(lines))
            self.details.show()

        self.ok_btn.setEnabled(True)
        self.ok_btn.show()
        self.ok_btn.setFocus()
        self._sync_height_to_content()

    def _on_cancel(self) -> None:
        if self._token_worker is not None:
            self._token_worker.request_cancel()
        if self._album_worker is not None:
            self._album_worker.request_cancel()
        if self._manager is not None:
            self._manager.request_cancel()
        self.reject()

    def closeEvent(self, event) -> None:
        if not self._finished:
            self._on_cancel()
        super().closeEvent(event)


def _build_upload_items(
    parent: MainWindow,
    visible_items: list[ImageItem],
) -> list[dict]:
    upload_items: list[dict] = []

    for order, item in enumerate(visible_items):
        metadata = item.db_metadata
        if metadata is None:
            metadata = parent.db_manager.get_db_for_image(item.path).get_metadata(
                item.path
            )
            if metadata is not None:
                item.db_metadata = metadata.copy()

        upload_items.append(
            {
                "file_path": item.path,
                "order": order,
                "db_metadata": metadata.copy() if isinstance(metadata, dict) else None,
            }
        )

    return upload_items


def _set_album_for_folders(
    parent: MainWindow,
    source_folders: list[str],
    album_id: str | None,
) -> None:
    value = str(album_id).strip() if album_id is not None else ""
    to_store = value if value else None
    for folder in source_folders:
        db = parent.db_manager.get_db_for_folder(folder)
        db.set_folder_value(FOLDER_STATE_LAST_FLICKR_ALBUM_ID, to_store)


def _get_first_folder_album_id(parent: MainWindow, source_folders: list[str]) -> str:
    for folder in source_folders:
        value = parent.db_manager.get_db_for_folder(folder).get_folder_value(
            FOLDER_STATE_LAST_FLICKR_ALBUM_ID
        )
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _resolve_prefill_album_plan(
    *,
    api_key: str,
    api_secret: str,
    album_id: str,
) -> FlickrAlbumPlan | None:
    aid = str(album_id).strip()
    if not aid:
        return None

    try:
        flickr = create_flickr_client(
            api_key,
            api_secret,
            token_cache_dir=get_flickr_cache_dir(),
            response_format="parsed-json",
        )
        info = fetch_album_info(flickr, aid)
    except Exception:
        return None

    return FlickrAlbumPlan(
        raw_text=aid,
        album_id=info.album_id,
        album_title=info.title,
        user_nsid=info.user_nsid,
        album_url=info.url,
        is_create=False,
    )


def launch_flickr_upload(parent: MainWindow) -> None:
    """Launch Flickr upload flow from MainWindow."""
    api_key = str(get_user_setting(UserSettingKey.FLICKR_API_KEY) or "").strip()
    api_secret = str(get_user_setting(UserSettingKey.FLICKR_API_SECRET) or "").strip()

    if not api_key or not api_secret:
        dialog = QMessageBox(parent)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Upload to Flickr")
        dialog.setText(
            "Flickr API key and Flickr API secret are empty.\n"
            "Set them in Settings > External/Workflow > Flickr."
        )
        go_to_settings_btn = dialog.addButton(
            "Go to settings", QMessageBox.ButtonRole.AcceptRole
        )
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.exec()
        if dialog.clickedButton() == go_to_settings_btn:
            parent.open_settings(tab_title="External/Workflow")
        return

    visible_items = list(parent.images_data)
    if not visible_items:
        QMessageBox.warning(
            parent,
            "Upload to Flickr",
            "No visible photos to upload.",
        )
        return

    source_folders = list(parent.photo_model.source_folders)
    token_path = str(get_flickr_token_file_path())

    session_album_text = ""
    session_album_error = ""
    cached_album_plan: FlickrAlbumPlan | None = None
    cached_album_from_folder_data = False

    while True:
        token_exists = token_file_exists(token_path)

        if token_exists and not session_album_text.strip():
            folder_album_id = _get_first_folder_album_id(parent, source_folders)
            if folder_album_id:
                session_album_text = folder_album_id
                cached_album_plan = _resolve_prefill_album_plan(
                    api_key=api_key,
                    api_secret=api_secret,
                    album_id=folder_album_id,
                )
                cached_album_from_folder_data = cached_album_plan is not None

        preflight = FlickrPreflightDialog(
            visible_count=len(visible_items),
            token_file_path=token_path,
            token_exists=token_exists,
            album_text=session_album_text,
            album_error=session_album_error,
            album_display_plan=(
                cached_album_plan if cached_album_from_folder_data else None
            ),
            show_album_link=cached_album_from_folder_data,
            parent=parent,
        )
        if preflight.exec() != QDialog.DialogCode.Accepted:
            return

        session_album_text = preflight.selected_album_text

        if preflight.selected_action == "login":
            worker = FlickrLoginWorker(api_key=api_key, api_secret=api_secret)
            login_dialog = FlickrLoginProgressDialog(parent=parent)
            login_dialog.start(worker)
            if login_dialog.exec() != QDialog.DialogCode.Accepted:
                return

            if login_dialog.error_message:
                QMessageBox.warning(
                    parent,
                    "Upload to Flickr",
                    login_dialog.error_message,
                )
            # refresh preflight after login attempt
            continue

        # Upload flow
        session_album_error = ""
        upload_items = _build_upload_items(parent, visible_items)
        exiftool_path = str(get_user_setting(UserSettingKey.EXIFTOOL_PATH) or "")

        cached_plan_for_upload = None
        if (
            cached_album_plan is not None
            and cached_album_plan.normalized_raw_text() == session_album_text.strip()
        ):
            cached_plan_for_upload = cached_album_plan

        upload_dialog = FlickrUploadProgressDialog(
            api_key=api_key,
            api_secret=api_secret,
            exiftool_path=exiftool_path,
            upload_items=upload_items,
            album_text=session_album_text,
            cached_album_plan=cached_plan_for_upload,
            set_folder_album_id_callback=lambda album_id: _set_album_for_folders(
                parent,
                source_folders,
                album_id,
            ),
            parent=parent,
        )

        def _on_manager_started(manager: FlickrUploadManager) -> None:
            parent._active_flickr_upload_manager = manager

        def _on_manager_finished(_manager: FlickrUploadManager) -> None:
            parent._active_flickr_upload_manager = None

        upload_dialog.manager_started.connect(_on_manager_started)
        upload_dialog.manager_finished.connect(_on_manager_finished)
        upload_dialog.start()
        upload_dialog.exec()

        if upload_dialog.invalid_token:
            continue

        if upload_dialog.album_validation_error:
            session_album_error = upload_dialog.album_validation_error
            cached_album_plan = None
            cached_album_from_folder_data = False
            continue

        if upload_dialog.resolved_album_plan is not None:
            cached_album_plan = upload_dialog.resolved_album_plan
            cached_album_from_folder_data = False

        if parent._active_flickr_upload_manager is not None:
            parent._active_flickr_upload_manager.stop(timeout_s=0.5)
            parent._active_flickr_upload_manager = None

        return
