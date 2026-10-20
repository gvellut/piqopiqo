"""Dialog for saving DB metadata to EXIF."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCharFormat
from PySide6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.components.summary_text_edit import SummaryLine, SummaryTextEdit
from piqopiqo.dialogs.modal import managed_modal_dialog
from piqopiqo.metadata.exif_write import build_exif_tags
from piqopiqo.model import ImageItem
from piqopiqo.tools.tool_flow import (
    ToolButton,
    ToolFlowDialog,
    ToolScreen,
    ToolTaskHandle,
    ToolWorkflow,
)

if TYPE_CHECKING:
    from piqopiqo.background.media_man import MediaManager
    from piqopiqo.main_window import MainWindow

logger = logging.getLogger(__name__)


def launch_save_exif(window: MainWindow) -> None:
    """Save DB metadata to EXIF for selected or all filtered photos."""
    selected = window.photo_model.get_selected_photos()
    items = selected if selected else list(window.images_data)
    if not items:
        return

    dialog = SaveExifDialog(items, window.media_manager, window)
    with managed_modal_dialog(dialog):
        try:
            dialog.exec()
        finally:
            dialog.stop_all_tasks(cancel=True)


class SaveExifDialog(ToolFlowDialog):
    """Dialog for saving DB metadata to EXIF with progress tracking."""

    def __init__(
        self,
        items: list[ImageItem],
        exif_manager: MediaManager,
        parent=None,
    ):
        self._items = items
        self._exif_manager = exif_manager
        self._is_running = False
        self._error_count = 0
        self._error_lines: list[str] = []
        self._processed_paths: list[str] = []

        workflow = ToolWorkflow(
            initial_screen="confirm",
            screens={
                "confirm": ToolScreen(
                    id="confirm",
                    title="Save EXIF Metadata",
                    build=lambda dialog: dialog._build_body(),
                    buttons=(
                        ToolButton("cancel", "Cancel"),
                        ToolButton("launch", "Launch", default=True),
                    ),
                    min_width=500,
                ),
                "writing": ToolScreen(
                    id="writing",
                    title="Save EXIF Metadata",
                    build=lambda dialog: dialog._build_body(),
                    buttons=(ToolButton("stop", "Stop", default=True),),
                    min_width=500,
                    show_progress=True,
                    close_policy="cancel",
                ),
                "result": ToolScreen(
                    id="result",
                    title="Save EXIF Metadata",
                    build=lambda dialog: dialog._build_result(),
                    buttons=(ToolButton("ok", "OK", default=True),),
                    min_width=500,
                ),
            },
            transitions={
                ("confirm", "launch"): lambda dialog, event: dialog._on_launch(),
                ("confirm", "cancel"): lambda dialog, event: dialog.reject(),
                ("writing", "stop"): lambda dialog, event: dialog._on_stop(),
                ("writing", "progress"): lambda dialog, event: dialog._on_progress(
                    *event.args
                ),
                ("writing", "file_completed"): (
                    lambda dialog, event: dialog._on_file_completed(*event.args)
                ),
                ("writing", "all_completed"): lambda dialog, event: (
                    dialog._on_all_completed()
                ),
                ("result", "ok"): lambda dialog, event: dialog.accept(),
            },
        )
        super().__init__(workflow, parent=parent)
        self._update_confirmation_text()
        self.sync_size_to_content()

    def _build_body(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)

        self.confirm_label = QLabel(widget)
        self.confirm_label.setWordWrap(True)
        layout.addWidget(self.confirm_label)

        self.error_label = QLabel(widget)
        self.error_label.setStyleSheet("color: red;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.error_text = SummaryTextEdit("", widget)
        self.error_text.hide()
        layout.addWidget(self.error_text)

        return widget

    def _build_result(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        self.summary_text = SummaryTextEdit("", widget)
        layout.addWidget(self.summary_text)
        self.error_text = SummaryTextEdit("", widget)
        self.error_text.hide()
        layout.addWidget(self.error_text)
        return widget

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
        self._error_lines = []
        self._processed_paths = []

        self.transition_to("writing")
        self.set_progress(0, len(self._items))

        self.confirm_label.setText("Writing EXIF metadata...")
        self.sync_size_to_content()

        items_with_tags = []
        for item in self._items:
            if item.db_metadata:
                tags = build_exif_tags(item.db_metadata)
                items_with_tags.append((item.path, tags))

        if not items_with_tags:
            self._finish(cancelled=False)
            return

        self.set_progress(0, len(items_with_tags))

        self.start_task(
            "write_exif",
            ToolTaskHandle.from_signals(
                start_fn=lambda: self._exif_manager.write_exif(items_with_tags),
                cancel_fn=self._exif_manager.stop_write,
                signal_map={
                    self._exif_manager.write_progress: "progress",
                    self._exif_manager.write_file_completed: "file_completed",
                    self._exif_manager.write_all_completed: "all_completed",
                },
            ),
        )

    def _on_stop(self):
        self.stop_task("write_exif", cancel=True)
        self._finish(cancelled=True)

    def _on_cancel(self):
        if self._is_running:
            self.stop_task("write_exif", cancel=True)
        self.reject()

    def _disconnect_signals(self):
        self.stop_task("write_exif", cancel=False)

    def _on_progress(self, completed: int, total: int):
        self.set_progress(completed, total)

    def _on_file_completed(self, file_path: str, success: bool, error_message: str):
        if success:
            self._processed_paths.append(file_path)
        else:
            self._error_count += 1
            self.error_label.setText(f"{self._error_count} file(s) with errors")
            self.error_label.show()

            # Add to error text
            filename = os.path.basename(file_path)
            line = f"{filename}: {error_message}"
            self._error_lines.append(line)
            self.error_text.set_lines(self._error_lines)
            self.error_text.show()
            self.sync_size_to_content()

    def _on_all_completed(self):
        self._disconnect_signals()
        self._finish(cancelled=False)

    def _finish(self, cancelled: bool):
        self._is_running = False

        self.transition_to("result")

        completed, total = self._exif_manager.get_write_progress()
        if cancelled:
            summary = f"Operation stopped. {completed} of {total} files processed."
        else:
            if self._error_count > 0:
                summary = (
                    f"Complete. {completed} files processed, "
                    f"{self._error_count} with errors."
                )
            else:
                summary = f"Complete. {completed} files processed."
        self.summary_text.set_lines(summary)
        if self._error_count > 0:
            error_format = QTextCharFormat()
            error_format.setForeground(Qt.GlobalColor.red)
            self.error_text.set_lines([
                SummaryLine(f"{self._error_count} file(s) with errors", error_format),
                *self._error_lines,
            ])
            self.error_text.show()
        self.sync_size_to_content()

    def get_processed_paths(self) -> list[str]:
        """Get list of file paths that were successfully processed."""
        return self._processed_paths.copy()

    def closeEvent(self, event):
        """Handle dialog close."""
        if self._is_running:
            self._exif_manager.stop_write()
            self._disconnect_signals()
        super().closeEvent(event)
