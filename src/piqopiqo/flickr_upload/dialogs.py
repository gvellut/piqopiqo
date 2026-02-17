"""Dialogs and launch flow for Flickr upload."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from piqopiqo.cache_paths import get_flickr_cache_dir, get_flickr_token_file_path
from piqopiqo.settings_state import (
    RuntimeSettingKey,
    UserSettingKey,
    get_runtime_setting,
    get_user_setting,
)

from .auth import token_file_exists
from .constants import TOKEN_VALIDATION_ERROR_TEXT
from .manager import FlickrUploadManager, FlickrUploadResult
from .workers import FlickrLoginWorker, FlickrTokenValidationWorker

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
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Upload to Flickr")
        self.setModal(True)
        self.setMinimumWidth(560)

        self.selected_action: str | None = None
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

    def _on_action(self) -> None:
        self.selected_action = "upload" if self._token_exists else "login"
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
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Upload to Flickr")
        self.setModal(True)
        self.setMinimumSize(620, 300)

        self._api_key = api_key
        self._api_secret = api_secret
        self._exiftool_path = exiftool_path
        self._upload_items = upload_items

        self._manager: FlickrUploadManager | None = None
        self._token_worker: FlickrTokenValidationWorker | None = None
        self._finished = False

        self.invalid_token = False
        self.result: FlickrUploadResult | None = None

        layout = QVBoxLayout(self)

        self.status_label = QLabel("Validating Flickr token...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.stage_label = QLabel("Step: -")
        self.stage_label.setWordWrap(True)
        layout.addWidget(self.stage_label)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

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

        self.progress_bar.setRange(0, max(1, len(self._upload_items)))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0/%v")
        self.status_label.setText("Uploading to Flickr...")

        manager = FlickrUploadManager(
            api_key=self._api_key,
            api_secret=self._api_secret,
            exiftool_path=self._exiftool_path,
            token_cache_dir=str(get_flickr_cache_dir()),
            max_workers=int(
                get_runtime_setting(RuntimeSettingKey.FLICKR_UPLOAD_MAX_WORKERS)
            ),
            parent=self,
        )
        self._manager = manager
        self.manager_started.emit(manager)
        manager.stage_changed.connect(self._on_stage_changed)
        manager.progress.connect(self._on_progress)
        manager.status.connect(self._on_status)
        manager.finished.connect(self._on_finished)
        manager.start(self._upload_items)

    def _on_validation_cancelled(self) -> None:
        self._finished = True
        self.reject()

    def _on_validation_error(self, message: str) -> None:
        self._finished = True
        QMessageBox.warning(self, "Upload to Flickr", str(message))
        self.reject()

    def _on_stage_changed(self, stage: str) -> None:
        self.stage_label.setText(f"Step: {stage}")

    def _on_progress(self, completed: int, total: int) -> None:
        self.progress_bar.setRange(0, max(0, int(total)))
        self.progress_bar.setValue(max(0, int(completed)))
        self.progress_bar.setFormat(f"{completed}/{total}")

    def _on_status(self, message: str) -> None:
        if message:
            self.status_label.setText(message)

    def _on_finished(self, result: FlickrUploadResult) -> None:
        self._finished = True
        self.result = result

        if self._manager is not None:
            self.manager_finished.emit(self._manager)

        self.cancel_btn.setEnabled(False)

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

    def _on_cancel(self) -> None:
        if self._token_worker is not None:
            self._token_worker.request_cancel()
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


def launch_flickr_upload(parent: MainWindow) -> None:
    """Launch Flickr upload flow from MainWindow."""
    api_key = str(get_user_setting(UserSettingKey.FLICKR_API_KEY) or "").strip()
    api_secret = str(get_user_setting(UserSettingKey.FLICKR_API_SECRET) or "").strip()

    if not api_key or not api_secret:
        QMessageBox.warning(
            parent,
            "Upload to Flickr",
            "Flickr API key and Flickr API secret are empty.\n"
            "Set them in Settings > External/Workflow > Flickr.",
        )
        return

    visible_items = list(parent.images_data)
    if not visible_items:
        QMessageBox.warning(
            parent,
            "Upload to Flickr",
            "No visible photos to upload.",
        )
        return

    token_path = str(get_flickr_token_file_path())

    while True:
        preflight = FlickrPreflightDialog(
            visible_count=len(visible_items),
            token_file_path=token_path,
            token_exists=token_file_exists(token_path),
            parent=parent,
        )
        if preflight.exec() != QDialog.DialogCode.Accepted:
            return

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
        upload_items = _build_upload_items(parent, visible_items)
        exiftool_path = str(get_user_setting(UserSettingKey.EXIFTOOL_PATH) or "")

        upload_dialog = FlickrUploadProgressDialog(
            api_key=api_key,
            api_secret=api_secret,
            exiftool_path=exiftool_path,
            upload_items=upload_items,
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

        if parent._active_flickr_upload_manager is not None:
            parent._active_flickr_upload_manager.stop(timeout_s=0.5)
            parent._active_flickr_upload_manager = None

        return
