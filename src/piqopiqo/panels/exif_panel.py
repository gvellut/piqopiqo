"""EXIF metadata display panel."""

from __future__ import annotations

import logging
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.components.ellided_label import EllidedLabel
from piqopiqo.config import Config
from piqopiqo.model import ExifField, ImageItem

logger = logging.getLogger(__name__)


def format_exif_key(key: str) -> str:
    """Auto-format an exiftool key for display.

    Removes the prefix (before colon) and adds spaces around capital letters.
    Examples:
        "File:FileName" => "File Name"
        "EXIF:DateTimeOriginal" => "Date Time Original"
        "EXIF:FNumber" => "F Number"

    Args:
        key: The exiftool key (e.g., "EXIF:DateTimeOriginal")

    Returns:
        Formatted display string
    """
    # Remove prefix (e.g., "EXIF:", "File:")
    if ":" in key:
        key = key.split(":", 1)[1]

    # Insert space before each capital letter that follows a lowercase letter
    # or before a capital letter that is followed by a lowercase letter
    formatted = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key)
    formatted = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", formatted)

    return formatted


def get_exif_display_label(field: ExifField) -> str:
    """Get the display label for an ExifField.

    If the field has an explicit label, use it.
    If EXIF_AUTO_FORMAT is True and no label, auto-format the key.
    Otherwise, return the raw key.

    Args:
        field: The ExifField instance

    Returns:
        The display label string
    """
    if field.label is not None:
        return field.label
    if Config.EXIF_AUTO_FORMAT:
        return format_exif_key(field.key)
    return field.key


class ExifPanel(QWidget):
    """Panel for displaying EXIF metadata."""

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
            display_label = get_exif_display_label(field)
            field_label = EllidedLabel(display_label)
            value_label = EllidedLabel("")

            field_label.setToolTip(field.key)

            self.layout.addWidget(field_label, i, 0)
            self.layout.addWidget(value_label, i, 1)

            self.field_labels.append(field_label)
            self.value_labels.append(value_label)

        # Set the container as the scroll area's widget
        scroll_area.setWidget(container)

        # Add scroll area to main layout
        main_layout.addWidget(scroll_area)

    def update_exif(self, items: list[ImageItem]):
        """Update the panel with EXIF data from the given items."""
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
                if item.exif_data is None:
                    values.add("Reading...")
                    continue

                value = item.exif_data.get(field.key)
                if value is None:
                    values.add("<Not Present>")
                    continue

                if not isinstance(value, str):
                    value = str(value)
                values.add(value)

            value_str = values.pop() if len(values) == 1 else "<Multiple values>"

            # Update only the text, not the widget itself
            self.value_labels[i].setText(value_str)
            self.value_labels[i].setToolTip(value_str)
