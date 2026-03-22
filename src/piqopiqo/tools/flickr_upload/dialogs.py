"""Dialogs and launch flow for Flickr upload."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
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
from piqopiqo.dialogs.settings_redirect import (
    prompt_open_settings_for_missing_setting,
)
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDBUnavailableError
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
    TOKEN_VALIDATION_ERROR_TEXT,
    FlickrStage,
)
from .manager import FlickrUploadManager, FlickrUploadResult
from .workers import (
    FlickrAlbumCheckWorker,
    FlickrLoginWorker,
    FlickrMetadataPrecheckWorker,
    FlickrTokenValidationWorker,
)

if TYPE_CHECKING:
    from piqopiqo.main_window import MainWindow
    from piqopiqo.model import ImageItem


logger = logging.getLogger(__name__)


def _normalize_missing_paths(missing_paths_obj: object) -> list[str]:
    return [
        str(path).strip()
        for path in (missing_paths_obj if isinstance(missing_paths_obj, list) else [])
        if str(path).strip()
    ]


class FlickrPreflightDialog(QDialog):
    """Preflight dialog showing upload scope and album state."""

    def __init__(
        self,
        *,
        visible_upload_items: list[dict],
        token_exists: bool,
        label_upload_items: list[dict] | None = None,
        label_override_text: str = "",
        initial_use_label_scope: bool | None = None,
        require_metadata: bool = False,
        db_manager=None,
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
        self.selected_use_label_scope = False
        self._token_exists = bool(token_exists)
        self._require_metadata = bool(require_metadata)
        self._db_manager = db_manager
        self._visible_upload_items = list(visible_upload_items or [])
        self._label_upload_items = list(label_upload_items or [])
        self._label_override_text = str(label_override_text or "").strip()
        self._visible_validation_missing_paths: list[str] | None = []
        self._label_validation_missing_paths: list[str] | None = []
        self._visible_validation_worker: FlickrMetadataPrecheckWorker | None = None
        self._label_validation_worker: FlickrMetadataPrecheckWorker | None = None
        self._closed = False
        self._validation_started = False

        self._visible_count = len(self._visible_upload_items)
        self._label_count = len(self._label_upload_items)
        self._has_label_scope_toggle = bool(self._label_override_text)
        if self._has_label_scope_toggle and self._label_count > 0:
            if initial_use_label_scope is None:
                self.selected_use_label_scope = True
            elif bool(initial_use_label_scope):
                self.selected_use_label_scope = True

        layout = QVBoxLayout(self)

        self.scope_checkbox: QCheckBox | None = None
        self.label_scope_warning_label: QLabel | None = None
        if self._has_label_scope_toggle:
            checkbox = QCheckBox(
                f"Upload all the {self._label_override_text} images",
                self,
            )
            checkbox.stateChanged.connect(self._on_scope_toggle_changed)
            checkbox.blockSignals(True)
            if self._label_count > 0:
                checkbox.setChecked(self.selected_use_label_scope)
            else:
                checkbox.setChecked(False)
                checkbox.setEnabled(False)
                self.selected_use_label_scope = False
            checkbox.blockSignals(False)
            self.scope_checkbox = checkbox
            layout.addWidget(checkbox)

            label_scope_warning = QLabel("No image with label", self)
            label_scope_warning.setStyleSheet("color: red;")
            label_scope_warning.setWordWrap(True)
            if self._label_count <= 0:
                label_scope_warning.show()
            else:
                label_scope_warning.hide()
            self.label_scope_warning_label = label_scope_warning
            layout.addWidget(label_scope_warning)

        count_section = QVBoxLayout()
        count_section.setContentsMargins(0, 0, 0, 0)
        count_section.setSpacing(0)

        self.count_label = QLabel(self)
        self.count_label.setTextFormat(Qt.TextFormat.RichText)
        self.count_label.setWordWrap(True)
        count_section.addWidget(self.count_label)

        self.metadata_warning_label = QLabel(self)
        self.metadata_warning_label.setStyleSheet("color: red;")
        self.metadata_warning_label.setWordWrap(True)
        self.metadata_warning_label.hide()
        count_section.addWidget(self.metadata_warning_label)
        layout.addLayout(count_section)

        self.album_input: QLineEdit | None = None
        self.album_info_group: QGroupBox | None = None
        self.album_name_label: QLabel | None = None
        self.album_id_label: QLabel | None = None
        self.album_link_label: QLabel | None = None
        self.album_error_label: QLabel | None = None

        if self._token_exists:
            self.album_info_group = QGroupBox("Album", self)
            album_info_layout = QVBoxLayout(self.album_info_group)

            album_row = QHBoxLayout()
            album_label = QLabel("Add to album (Optional)", self.album_info_group)
            album_row.addWidget(album_label)

            help_btn = QToolButton(self.album_info_group)
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
            album_info_layout.addLayout(album_row)

            self.album_input = QLineEdit(self.album_info_group)
            self.album_input.setText(self.selected_album_text)
            self.album_input.textChanged.connect(self._on_album_text_changed)
            album_info_layout.addWidget(self.album_input)

            self.album_name_label = QLabel(self.album_info_group)
            self.album_name_label.setWordWrap(True)
            album_info_layout.addWidget(self.album_name_label)

            self.album_id_label = QLabel(self.album_info_group)
            self.album_id_label.setWordWrap(True)
            album_info_layout.addWidget(self.album_id_label)

            self.album_link_label = QLabel(self.album_info_group)
            self.album_link_label.setTextFormat(Qt.TextFormat.RichText)
            self.album_link_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextBrowserInteraction
            )
            self.album_link_label.setOpenExternalLinks(True)
            album_info_layout.addWidget(self.album_link_label)

            self.album_error_label = QLabel(self.album_info_group)
            self.album_error_label.setStyleSheet("color: red;")
            self.album_error_label.setWordWrap(True)
            album_info_layout.addWidget(self.album_error_label)
            layout.addWidget(self.album_info_group)
            self._set_album_display_plan(
                album_display_plan if album_display_plan is not None else None,
                show_album_link=show_album_link,
            )
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
        self._refresh_scope_state()
        self._start_metadata_validation_if_needed()
        self._sync_height_to_content()

    def selected_upload_scope_items(self) -> list[dict]:
        if self.selected_use_label_scope:
            return list(self._label_upload_items)
        return list(self._visible_upload_items)

    def _scope_count(self, use_label_scope: bool) -> int:
        return len(self._scope_items(use_label_scope))

    def _scope_items(self, use_label_scope: bool) -> list[dict]:
        return (
            self._label_upload_items if use_label_scope else self._visible_upload_items
        )

    def _scope_log_name(self, use_label_scope: bool) -> str:
        return "label" if use_label_scope else "visible"

    def _get_selected_use_label_scope(self) -> bool:
        return self.scope_checkbox is not None and self.scope_checkbox.isChecked()

    def _get_validation_missing_paths(
        self,
        use_label_scope: bool,
    ) -> list[str] | None:
        if use_label_scope:
            return self._label_validation_missing_paths
        return self._visible_validation_missing_paths

    def _set_validation_missing_paths(
        self,
        use_label_scope: bool,
        missing_paths: list[str] | None,
    ) -> None:
        if use_label_scope:
            self._label_validation_missing_paths = missing_paths
            return
        self._visible_validation_missing_paths = missing_paths

    def _set_validation_worker(
        self,
        use_label_scope: bool,
        worker: FlickrMetadataPrecheckWorker | None,
    ) -> None:
        if use_label_scope:
            self._label_validation_worker = worker
            return
        self._visible_validation_worker = worker

    def _sync_height_to_content(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self.adjustSize()
        target_height = self.sizeHint().height()
        if target_height > 0:
            self.setFixedHeight(target_height)

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

    def _set_album_display_plan(
        self,
        plan: FlickrAlbumPlan | None,
        *,
        show_album_link: bool,
    ) -> None:
        if (
            self.album_info_group is None
            or self.album_name_label is None
            or self.album_id_label is None
            or self.album_link_label is None
        ):
            return

        if plan is None or not plan.is_existing_album():
            self.album_name_label.clear()
            self.album_name_label.hide()
            self.album_id_label.clear()
            self.album_id_label.hide()
            self.album_link_label.clear()
            self.album_link_label.hide()
            return

        display_title = plan.album_title or "<untitled>"
        self.album_name_label.setText(f"Name: {display_title}")
        self.album_name_label.show()
        self.album_id_label.setText(f"ID: {plan.album_id}")
        self.album_id_label.show()
        if show_album_link and plan.album_url:
            url = plan.album_url
            self.album_link_label.setText(
                f'<a href="{url}" style="color:#1f6feb;">{url}</a>'
            )
            self.album_link_label.show()
        else:
            self.album_link_label.clear()
            self.album_link_label.hide()

    def _set_metadata_warning(self, message: str) -> None:
        text = str(message or "").strip()
        if text:
            self.metadata_warning_label.setText(text)
            self.metadata_warning_label.show()
            return
        self.metadata_warning_label.clear()
        self.metadata_warning_label.hide()

    def _set_album_input_enabled(self, enabled: bool) -> None:
        if self.album_input is not None:
            self.album_input.setEnabled(enabled)

    def _refresh_scope_state(self) -> None:
        self.selected_use_label_scope = self._get_selected_use_label_scope()
        selected_count = self._scope_count(self.selected_use_label_scope)
        self.count_label.setText(f"Photos to upload:<br><b>{selected_count}</b>")

        missing_paths: list[str] | None = None
        if self._require_metadata:
            missing_paths = self._get_validation_missing_paths(
                self.selected_use_label_scope
            )

        if self._require_metadata and missing_paths:
            self._set_metadata_warning(
                f"{len(missing_paths)} photo(s) are missing Title or keywords."
            )
        else:
            self._set_metadata_warning("")

        can_upload = selected_count > 0
        if self._require_metadata:
            can_upload = can_upload and missing_paths is not None and not missing_paths

        if self._token_exists:
            self.action_btn.setEnabled(can_upload)
            self._set_album_input_enabled(can_upload)
        else:
            self.action_btn.setEnabled(True)
        self._sync_height_to_content()

    def _start_metadata_validation_if_needed(self) -> None:
        if (
            self._validation_started
            or not self._require_metadata
            or self._db_manager is None
        ):
            return

        self._validation_started = True
        for use_label_scope, upload_items in (
            (False, self._visible_upload_items),
            (True, self._label_upload_items),
        ):
            if use_label_scope and not self._has_label_scope_toggle:
                self._set_validation_missing_paths(use_label_scope, [])
                continue
            if not upload_items:
                self._set_validation_missing_paths(use_label_scope, [])
                continue

            self._set_validation_missing_paths(use_label_scope, None)
            worker = FlickrMetadataPrecheckWorker(
                db_manager=self._db_manager,
                upload_items=upload_items,
            )
            self._set_validation_worker(use_label_scope, worker)
            worker.signals.finished.connect(
                lambda missing_paths_obj, use_label_scope=use_label_scope: (
                    self._on_metadata_validation_finished(  # noqa: B023
                        use_label_scope,
                        missing_paths_obj,
                    )
                )
            )
            worker.signals.cancelled.connect(
                lambda use_label_scope=use_label_scope: (
                    self._on_metadata_validation_cancelled(  # noqa: B023
                        use_label_scope
                    )
                )
            )
            worker.signals.error.connect(
                lambda message, use_label_scope=use_label_scope: (
                    self._on_metadata_validation_error(  # noqa: B023
                        use_label_scope,
                        message,
                    )
                )
            )
            QThreadPool.globalInstance().start(worker)

        self._refresh_scope_state()

    def _on_metadata_validation_finished(
        self,
        use_label_scope: bool,
        missing_paths_obj: object,
    ) -> None:
        self._set_validation_worker(use_label_scope, None)
        if self._closed:
            return
        self._set_validation_missing_paths(
            use_label_scope,
            _normalize_missing_paths(missing_paths_obj),
        )
        self._refresh_scope_state()

    def _on_metadata_validation_cancelled(self, use_label_scope: bool) -> None:
        self._set_validation_worker(use_label_scope, None)
        if self._closed:
            return
        self._set_validation_missing_paths(use_label_scope, [])
        self._refresh_scope_state()

    def _on_metadata_validation_error(
        self, use_label_scope: bool, message: str
    ) -> None:
        self._set_validation_worker(use_label_scope, None)
        logger.warning(
            "Flickr metadata precheck failed for %s scope; allowing upload: %s",
            self._scope_log_name(use_label_scope),
            str(message),
        )
        if self._closed:
            return
        self._set_validation_missing_paths(use_label_scope, [])
        self._refresh_scope_state()

    def _on_scope_toggle_changed(self, _state: int) -> None:
        self._refresh_scope_state()

    def _on_action(self) -> None:
        self.selected_action = "upload" if self._token_exists else "login"
        self.selected_use_label_scope = self._get_selected_use_label_scope()
        if self.album_input is not None:
            self.selected_album_text = str(self.album_input.text() or "")
        self.accept()

    def closeEvent(self, event) -> None:
        self._closed = True
        for worker in (
            self._visible_validation_worker,
            self._label_validation_worker,
        ):
            if worker is None:
                continue
            worker.request_cancel()
        self._visible_validation_worker = None
        self._label_validation_worker = None
        super().closeEvent(event)


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
        self._started = False
        self._current_stage = "Validating Flickr token..."
        self._album_action_text = ""
        self._check_status_text = ""

        self.invalid_token = False
        self.result: FlickrUploadResult | None = None
        self.album_validation_error: str = ""
        self.resolved_album_plan: FlickrAlbumPlan | None = None

        layout = QVBoxLayout(self)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        layout.addWidget(self.status_label)

        stage_row = QHBoxLayout()
        self.stage_label = QLabel("")
        self.stage_label.setWordWrap(True)
        stage_row.addWidget(self.stage_label, 1)

        self.progress_text_label = QLabel("")
        self.progress_text_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        mono = QFont("menlo")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.progress_text_label.setFont(mono)
        self.progress_text_label.hide()
        stage_row.addWidget(self.progress_text_label)
        layout.addLayout(stage_row)

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
        if (
            stage_text == FlickrStage.STAGE_CHECK_UPLOAD_STATUS.label
            and self._check_status_text
        ):
            stage_text = f"{stage_text} - {self._check_status_text}"
        elif (
            stage_text == FlickrStage.STAGE_ADD_TO_ALBUM.label
            and self._album_action_text
        ):
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
        if self._started:
            return
        self._started = True
        worker = FlickrTokenValidationWorker(
            api_key=self._api_key,
            api_secret=self._api_secret,
        )
        self._token_worker = worker
        worker.signals.finished.connect(self._on_token_validated)
        worker.signals.cancelled.connect(self._on_validation_cancelled)
        worker.signals.error.connect(self._on_validation_error)
        QThreadPool.globalInstance().start(worker)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.start()

    def _on_token_validated(self, valid: bool) -> None:
        if not valid:
            self.invalid_token = True
            self._finished = True
            QMessageBox.warning(self, "Upload to Flickr", TOKEN_VALIDATION_ERROR_TEXT)
            self.reject()
            return

        self._current_stage = FlickrStage.STAGE_ALBUM_CHECK.label
        self._album_action_text = ""
        self._check_status_text = ""
        self._update_stage_label()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("")
        self.progress_text_label.clear()
        self.progress_text_label.hide()
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
        total_items = max(1, len(self._upload_items))
        self.progress_bar.setRange(0, total_items)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"0/{total_items}")
        self.progress_text_label.setText(f"0/{total_items}")
        self.progress_text_label.show()
        self._current_stage = FlickrStage.STAGE_UPLOAD.label
        self._album_action_text = ""
        self._check_status_text = ""
        self._update_stage_label()
        self._sync_height_to_content()

        manager = FlickrUploadManager(
            api_key=self._api_key,
            api_secret=self._api_secret,
            exiftool_path=self._exiftool_path,
            token_cache_dir=str(get_flickr_cache_dir()),
            max_workers=int(
                get_runtime_setting(RuntimeSettingKey.FLICKR_UPLOAD_MAX_WORKERS)  # type: ignore
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
        if stage != FlickrStage.STAGE_ADD_TO_ALBUM.label:
            self._album_action_text = ""
        if stage != FlickrStage.STAGE_CHECK_UPLOAD_STATUS.label:
            self._check_status_text = ""
        self._update_stage_label()

        if stage == FlickrStage.STAGE_CHECK_UPLOAD_STATUS.label:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("")
            self.progress_text_label.clear()
            self.progress_text_label.hide()

        self.album_action_label.clear()
        self.album_action_label.hide()
        self._sync_height_to_content()

    def _on_progress(self, completed: int, total: int) -> None:
        if self._finished:
            return
        if int(total) <= 0:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("")
            self.progress_text_label.clear()
            self.progress_text_label.hide()
            return
        self.progress_bar.setRange(0, int(total))
        self.progress_bar.setValue(max(0, int(completed)))
        self.progress_bar.setFormat(f"{completed}/{total}")
        self.progress_text_label.setText(f"{completed}/{total}")
        self.progress_text_label.show()

    def _on_status(self, message: str) -> None:
        if self._finished:
            return
        if self._current_stage != FlickrStage.STAGE_CHECK_UPLOAD_STATUS.label:
            return
        self._check_status_text = str(message or "").strip()
        self._update_stage_label()

    def _on_album_status(self, message: str) -> None:
        if self._finished:
            return
        text = str(message or "").strip()
        if self._current_stage != FlickrStage.STAGE_ADD_TO_ALBUM.label:
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
        self.progress_text_label.hide()
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


def _build_upload_scope_items(items: list[ImageItem]) -> list[dict]:
    """Build a deterministic upload scope snapshot from the given ordered items."""
    scope_items: list[dict] = []

    for order, item in enumerate(items):
        metadata = item.db_metadata
        scope_items.append(
            {
                "file_path": item.path,
                "order": order,
                "db_metadata": metadata.copy() if isinstance(metadata, dict) else None,
            }
        )

    return scope_items


def _ensure_item_db_metadata(parent: MainWindow, item: ImageItem) -> dict | None:
    metadata = item.db_metadata
    if metadata is not None:
        return metadata if isinstance(metadata, dict) else None

    metadata = parent.db_manager.get_db_for_image(item.path).get_metadata(item.path)
    if isinstance(metadata, dict):
        item.db_metadata = metadata.copy()
        return item.db_metadata

    item.db_metadata = metadata
    return None


def _build_label_upload_scope_items(
    parent: MainWindow,
    *,
    label_override_text: str,
) -> list[dict]:
    matching_items: list[ImageItem] = []
    for item in parent.photo_model.all_photos:
        metadata = _ensure_item_db_metadata(parent, item)
        if not isinstance(metadata, dict):
            continue
        if str(metadata.get(DBFields.LABEL) or "") != label_override_text:
            continue
        matching_items.append(item)

    ordered_items = parent.photo_model.sort_photos_for_current_order(matching_items)
    return _build_upload_scope_items(ordered_items)


def _build_upload_items(
    parent: MainWindow,
    upload_scope_items: list[dict],
) -> list[dict]:
    upload_items: list[dict] = []

    for entry in upload_scope_items:
        file_path = str(entry.get("file_path") or "")
        if not file_path:
            continue

        order = int(entry.get("order", len(upload_items)))
        metadata = entry.get("db_metadata")
        if metadata is None:
            metadata = parent.db_manager.get_db_for_image(file_path).get_metadata(
                file_path
            )

        upload_items.append(
            {
                "file_path": file_path,
                "order": order,
                "db_metadata": metadata.copy() if isinstance(metadata, dict) else None,
            }
        )

    return upload_items


def _set_album_for_folders(
    parent: MainWindow,
    source_folders: list[str],
    album_id: str | None,
) -> bool:
    value = str(album_id).strip() if album_id is not None else ""
    to_store = value if value else None
    for folder in source_folders:
        db = parent.db_manager.get_db_for_folder(folder)
        try:
            db.set_folder_value(FOLDER_STATE_LAST_FLICKR_ALBUM_ID, to_store)
        except MetadataDBUnavailableError:
            handle_interrupted = getattr(parent, "_handle_interrupted_db_action", None)
            if callable(handle_interrupted):
                handle_interrupted(action_name="Upload to Flickr")
            return False
    return True


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


def _launch_flickr_upload_flow(
    parent: MainWindow,
    *,
    api_key: str,
    api_secret: str,
    visible_upload_items: list[dict],
    label_upload_items: list[dict],
    label_override_text: str,
    should_require_metadata: bool,
) -> None:
    source_folders = list(parent.photo_model.source_folders)
    token_path = str(get_flickr_token_file_path())

    session_album_text = ""
    session_album_error = ""
    session_use_label_scope: bool | None = None
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
            visible_upload_items=visible_upload_items,
            token_exists=token_exists,
            label_upload_items=label_upload_items,
            label_override_text=label_override_text,
            initial_use_label_scope=session_use_label_scope,
            require_metadata=should_require_metadata,
            db_manager=parent.db_manager if should_require_metadata else None,
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
        session_use_label_scope = preflight.selected_use_label_scope

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
        upload_items = _build_upload_items(
            parent, preflight.selected_upload_scope_items()
        )
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


def launch_flickr_upload(parent: MainWindow) -> None:
    """Launch Flickr upload flow from MainWindow."""
    api_key = str(get_user_setting(UserSettingKey.FLICKR_API_KEY) or "").strip()
    api_secret = str(get_user_setting(UserSettingKey.FLICKR_API_SECRET) or "").strip()

    if not api_key or not api_secret:
        should_open_settings = prompt_open_settings_for_missing_setting(
            parent,
            title="Upload to Flickr",
            text=(
                "Flickr API key and Flickr API secret are empty.\n"
                "Set them in Settings > External/Tools > Flickr."
            ),
        )
        if should_open_settings:
            open_settings = getattr(parent, "open_settings_for_key", None)
            if callable(open_settings):
                open_settings(UserSettingKey.FLICKR_API_KEY)
        return

    visible_items = list(parent.images_data)
    should_require_metadata = bool(
        get_user_setting(UserSettingKey.FLICKR_UPLOAD_REQUIRE_TITLE_AND_KEYWORDS)
    )
    label_override_text = str(
        get_user_setting(UserSettingKey.FLICKR_UPLOAD_LABEL) or ""
    ).strip()

    visible_upload_items = _build_upload_scope_items(visible_items)
    label_upload_items: list[dict] = []
    if label_override_text:
        label_upload_items = _build_label_upload_scope_items(
            parent,
            label_override_text=label_override_text,
        )

    if not visible_upload_items and not label_upload_items:
        QMessageBox.warning(
            parent,
            "Upload to Flickr",
            "No photos to upload.",
        )
        return

    _launch_flickr_upload_flow(
        parent,
        api_key=api_key,
        api_secret=api_secret,
        visible_upload_items=visible_upload_items,
        label_upload_items=label_upload_items,
        label_override_text=label_override_text,
        should_require_metadata=should_require_metadata,
    )
