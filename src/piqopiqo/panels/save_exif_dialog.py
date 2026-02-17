"""Dialog for saving DB metadata to EXIF."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from piqopiqo.metadata.exif_write import build_exif_tags
from piqopiqo.model import ImageItem

if TYPE_CHECKING:
    from piqopiqo.background.media_man import MediaManager

logger = logging.getLogger(__name__)


class SaveExifDialog(QDialog):
    """Dialog for saving DB metadata to EXIF with progress tracking."""

    def __init__(
        self,
        items: list[ImageItem],
        exif_manager: MediaManager,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Save EXIF Metadata")
        self.setMinimumSize(500, 300)
        self.setModal(True)

        self._items = items
        self._exif_manager = exif_manager
        self._is_running = False
        self._error_count = 0
        self._processed_paths: list[str] = []

        self._setup_ui()
        self._update_confirmation_text()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Confirmation label
        self.confirm_label = QLabel()
        self.confirm_label.setWordWrap(True)
        layout.addWidget(self.confirm_label)

        # Progress bar (hidden initially)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Error count label (hidden initially)
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: red;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        # Scrollable error text box (hidden initially)
        self.error_text = QTextEdit()
        self.error_text.setReadOnly(True)
        self.error_text.hide()
        layout.addWidget(self.error_text, 1)

        # Button row
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.launch_btn = QPushButton("Launch")
        self.launch_btn.clicked.connect(self._on_launch)
        btn_layout.addWidget(self.launch_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)

    def _update_confirmation_text(self):
        count = len(self._items)
        self.confirm_label.setText(
            f"This will write metadata from the database to {count} image file(s).\n\n"
            "This operation will modify the original files. Existing EXIF metadata "
            "may be overwritten.\n\n"
            "Click Launch to start, or Cancel to abort."
        )

    def _on_launch(self):
        if self._is_running:
            return

        self._is_running = True
        self._error_count = 0
        self._processed_paths = []

        # Update UI
        self.launch_btn.setText("Stop")
        self.launch_btn.clicked.disconnect()
        self.launch_btn.clicked.connect(self._on_stop)

        self.cancel_btn.hide()

        self.progress_bar.show()
        self.progress_bar.setMaximum(len(self._items))
        self.progress_bar.setValue(0)

        self.confirm_label.setText("Writing EXIF metadata...")

        # Prepare items with their tags
        items_with_tags = []
        for item in self._items:
            if item.db_metadata:
                tags = build_exif_tags(item.db_metadata)
                items_with_tags.append((item.path, tags))

        if not items_with_tags:
            self._finish(cancelled=False)
            return

        # Update progress bar max for actual items to process
        self.progress_bar.setMaximum(len(items_with_tags))

        # Connect signals
        self._exif_manager.write_progress.connect(self._on_progress)
        self._exif_manager.write_file_completed.connect(self._on_file_completed)
        self._exif_manager.write_all_completed.connect(self._on_all_completed)

        # Start writing
        self._exif_manager.write_exif(items_with_tags)

    def _on_stop(self):
        self._exif_manager.stop_write()
        self._disconnect_signals()
        self._finish(cancelled=True)

    def _on_cancel(self):
        if self._is_running:
            self._exif_manager.stop_write()
            self._disconnect_signals()
        self.reject()

    def _disconnect_signals(self):
        try:
            self._exif_manager.write_progress.disconnect(self._on_progress)
        except RuntimeError:
            pass
        try:
            self._exif_manager.write_file_completed.disconnect(self._on_file_completed)
        except RuntimeError:
            pass
        try:
            self._exif_manager.write_all_completed.disconnect(self._on_all_completed)
        except RuntimeError:
            pass

    def _on_progress(self, completed: int, total: int):
        self.progress_bar.setValue(completed)
        self.progress_bar.setFormat(f"{completed}/{total}")

    def _on_file_completed(self, file_path: str, success: bool, error_message: str):
        if success:
            self._processed_paths.append(file_path)
        else:
            self._error_count += 1
            self.error_label.setText(f"{self._error_count} file(s) with errors")
            self.error_label.show()

            # Add to error text
            filename = os.path.basename(file_path)
            self.error_text.append(f"{filename}: {error_message}")
            self.error_text.show()

    def _on_all_completed(self):
        self._disconnect_signals()
        self._finish(cancelled=False)

    def _finish(self, cancelled: bool):
        self._is_running = False

        # Update button
        self.launch_btn.setText("OK")
        try:
            self.launch_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.launch_btn.clicked.connect(self.accept)

        # Update status text
        completed, total = self._exif_manager.get_write_progress()
        if cancelled:
            self.confirm_label.setText(
                f"Operation stopped. {completed} of {total} files processed."
            )
        else:
            if self._error_count > 0:
                self.confirm_label.setText(
                    f"Complete. {completed} files processed, "
                    f"{self._error_count} with errors."
                )
            else:
                self.confirm_label.setText(f"Complete. {completed} files processed.")

    def get_processed_paths(self) -> list[str]:
        """Get list of file paths that were successfully processed."""
        return self._processed_paths.copy()

    def closeEvent(self, event):
        """Handle dialog close."""
        if self._is_running:
            self._exif_manager.stop_write()
            self._disconnect_signals()
        super().closeEvent(event)
