from __future__ import annotations

import logging
import multiprocessing

import exiftool
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .components import EllidedLabel
from .config import Config
from .model import ImageItem

logger = logging.getLogger(__name__)


def exif_worker_task(
    file_path: str, exiftool_path: str | None, common_args: list[str]
) -> tuple[str, dict]:
    """Fetch EXIF metadata in a separate process."""
    with exiftool.ExifToolHelper(
        executable=exiftool_path, common_args=common_args
    ) as helper:
        metadata = helper.get_metadata(file_path)
        if not metadata:
            return (file_path, {})
        return (file_path, metadata[0])


class ExifPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Create main layout for the panel
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Create scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # Create container widget for the grid
        container = QWidget()
        # Set size policy to prevent vertical expansion
        container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.layout = QGridLayout(container)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(Config.EXIF_PANEL_ROW_SPACING)
        self.layout.setColumnStretch(0, Config.EXIF_PANEL_LAYOUT[0])
        self.layout.setColumnStretch(1, Config.EXIF_PANEL_LAYOUT[1])

        # Create labels once for all fields
        self.field_labels = []
        self.value_labels = []

        for i, field in enumerate(Config.EXIF_FIELDS):
            field_label = EllidedLabel(field)
            value_label = EllidedLabel("")

            field_label.setToolTip(field)

            self.layout.addWidget(field_label, i, 0)
            self.layout.addWidget(value_label, i, 1)

            self.field_labels.append(field_label)
            self.value_labels.append(value_label)

        # Set the container as the scroll area's widget
        scroll_area.setWidget(container)

        # Add scroll area to main layout
        main_layout.addWidget(scroll_area)

    def update_exif(self, items: list[ImageItem]):
        if not items:
            # Clear all values if no items selected
            for value_label in self.value_labels:
                value_label.setText("")
                value_label.setToolTip("")
            return

        for i, field in enumerate(Config.EXIF_FIELDS):
            # Defensive check in case config changed (shouldn't happen at runtime)
            if i >= len(self.value_labels):
                logger.warning(
                    f"Config.EXIF_FIELDS has more entries ({len(Config.EXIF_FIELDS)}) "
                    f"than initialized labels ({len(self.value_labels)})"
                )
                break

            values = set()
            for item in items:
                if item.exif_data and field in item.exif_data:
                    value = item.exif_data[field]
                    if not isinstance(value, str):
                        # TODO see if some should not be converted
                        value = str(value)  # "<Unable to display>"
                    values.add(value)
                else:
                    values.add("<Not Present>")

            value_str = values.pop() if len(values) == 1 else "<Multiple values>"

            # Update only the text, not the widget itself
            self.value_labels[i].setText(value_str)
            self.value_labels[i].setToolTip(value_str)


class ExifManager(QObject):
    exif_ready = Signal(str, dict)

    def __init__(
        self,
        exiftool_path: str | None,
        common_args: list[str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.exiftool_path = exiftool_path
        self.common_args = common_args or ["-G"]
        self.pool = multiprocessing.Pool(Config.MAX_WORKERS)
        self.pending: set[str] = set()

    def fetch_exif(self, file_path: str):
        if file_path in self.pending:
            return

        self.pending.add(file_path)
        self.pool.apply_async(
            exif_worker_task,
            (file_path, self.exiftool_path, self.common_args),
            callback=self._on_task_done,
            error_callback=lambda e, fp=file_path: self._on_task_error(fp, e),
        )

    def _on_task_done(self, result: tuple[str, dict]):
        file_path, metadata = result
        if file_path in self.pending:
            self.pending.remove(file_path)
        self.exif_ready.emit(file_path, metadata)

    def _on_task_error(self, file_path: str, error: Exception):
        if file_path in self.pending:
            self.pending.remove(file_path)
        logger.error(f"Error fetching EXIF for {file_path}: {error}")
        self.exif_ready.emit(file_path, {})

    def stop(self):
        """Stop the EXIF worker pool."""
        self.pool.close()
        self.pool.join()
