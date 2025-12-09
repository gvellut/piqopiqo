from __future__ import annotations

import logging

import exiftool
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
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


class ExifFetcher(QRunnable):
    def __init__(self, exif_manager: ExifManager, file_path):
        super().__init__()
        self.exif_manager = exif_manager
        self.file_path = file_path

    def run(self):
        try:
            metadata = self.exif_manager.etHelper.execute_json(self.file_path)
            # get_metadata(self.file_path)
            # single file passed so [0] to retrieve its metadata
            metadata = metadata[0]
            self.exif_manager.exif_ready.emit(self.file_path, metadata)
        except Exception as e:
            logger.error(f"Error fetching EXIF for {self.file_path}: {e}")
            self.exif_manager.exif_ready.emit(self.file_path, {})


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

    def __init__(self, etHelper: exiftool.ExifToolHelper, parent=None):
        super().__init__(parent)
        self.etHelper = etHelper
        self.thread_pool = QThreadPool()

    def fetch_exif(self, file_path: str):
        worker = ExifFetcher(self, file_path)
        self.thread_pool.start(worker)
