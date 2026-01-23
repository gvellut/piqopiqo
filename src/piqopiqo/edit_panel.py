"""Editable metadata panel for photo metadata."""

import logging

from PySide6.QtCore import Qt, Signal, QRect, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from .config import Config
from .db_fields import DBFields, FIELD_DISPLAY_LABELS, EDITABLE_FIELDS
from .metadata_db import (
    MetadataDBManager,
    validate_datetime,
    validate_latitude,
    validate_longitude,
)
from .model import ImageItem

logger = logging.getLogger(__name__)

# Placeholder for multiple values
MULTIPLE_VALUES = "<Multiple Values>"


class TitleEdit(QLineEdit):
    """Single-line title editor with special key handling."""

    edit_finished = Signal()
    edit_cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_value = ""
        self.setMaxLength(Config.TITLE_MAX_LENGTH)

    def set_value(self, value: str):
        """Set the field value and store as original."""
        self._original_value = value or ""
        self.setText(self._original_value)

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key_Return or key == Qt.Key_Enter:
            if modifiers & Qt.ControlModifier:
                # Cmd+Enter does nothing for title
                return
            # Enter saves and finishes
            self.edit_finished.emit()
            return

        if key == Qt.Key_Escape:
            # Escape reverts and finishes
            self.setText(self._original_value)
            self.edit_cancelled.emit()
            return

        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        """Save on focus out if value changed."""
        if self.text() != self._original_value:
            self.edit_finished.emit()
        super().focusOutEvent(event)

    def insertFromMimeData(self, source):
        """Remove newlines when pasting."""
        if source.hasText():
            text = source.text().replace("\n", " ").replace("\r", " ")
            self.insert(text)


class DescriptionEdit(QPlainTextEdit):
    """Multi-line description editor with special key handling."""

    edit_finished = Signal()
    edit_cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_value = ""
        self.setMaximumHeight(100)

    def set_value(self, value: str):
        """Set the field value and store as original."""
        self._original_value = value or ""
        self.setPlainText(self._original_value)

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key_Return or key == Qt.Key_Enter:
            if modifiers & Qt.ControlModifier:
                # Cmd+Enter adds newline
                self.insertPlainText("\n")
                return
            # Enter saves and finishes
            self.edit_finished.emit()
            return

        if key == Qt.Key_Escape:
            # Escape reverts and finishes
            self.setPlainText(self._original_value)
            self.edit_cancelled.emit()
            return

        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        """Save on focus out if value changed."""
        text = self.toPlainText()
        if len(text) > Config.DESCRIPTION_MAX_LENGTH:
            text = text[: Config.DESCRIPTION_MAX_LENGTH]
            self.setPlainText(text)
        if text != self._original_value:
            self.edit_finished.emit()
        super().focusOutEvent(event)


class CoordinateEdit(QLineEdit):
    """Coordinate editor with validation."""

    edit_finished = Signal()
    edit_cancelled = Signal()

    def __init__(self, is_latitude: bool, parent=None):
        super().__init__(parent)
        self._original_value = ""
        self._is_latitude = is_latitude
        self._is_valid = True

    def set_value(self, value: float | None):
        """Set the field value and store as original."""
        if value is not None:
            self._original_value = f"{value:.6f}"
        else:
            self._original_value = ""
        self.setText(self._original_value)
        self._validate()

    def _validate(self):
        """Validate current value and update styling."""
        text = self.text()
        if self._is_latitude:
            valid, _ = validate_latitude(text)
        else:
            valid, _ = validate_longitude(text)

        self._is_valid = valid
        if valid:
            self.setStyleSheet("")
        else:
            self.setStyleSheet("border: 1px solid red;")

    def get_value(self) -> float | None:
        """Get the validated value."""
        text = self.text()
        if self._is_latitude:
            valid, value = validate_latitude(text)
        else:
            valid, value = validate_longitude(text)
        return value if valid else None

    def keyPressEvent(self, event):
        key = event.key()

        if key == Qt.Key_Return or key == Qt.Key_Enter:
            if self._is_valid:
                self.edit_finished.emit()
            return

        if key == Qt.Key_Escape:
            self.setText(self._original_value)
            self._validate()
            self.edit_cancelled.emit()
            return

        super().keyPressEvent(event)
        self._validate()

    def focusOutEvent(self, event):
        """Save on focus out if value changed and valid."""
        if self._is_valid and self.text() != self._original_value:
            self.edit_finished.emit()
        super().focusOutEvent(event)


class KeywordsEdit(QPlainTextEdit):
    """Keywords editor (comma-separated) with word wrap and auto-height."""

    edit_finished = Signal()
    edit_cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_value = ""
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.document().contentsChanged.connect(self._adjust_height)
        self._adjust_height()

    def _adjust_height(self):
        """Adjust height to fit content."""
        doc = self.document()
        # Use widget width if viewport not yet sized
        width = self.viewport().width()
        if width <= 0:
            width = self.width() - self.frameWidth() * 2
        if width > 0:
            doc.setTextWidth(width)

        # Get block count and calculate height based on actual line count
        block_count = doc.blockCount()
        if block_count == 0:
            block_count = 1

        # Calculate wrapped line count
        total_lines = 0
        block = doc.begin()
        while block.isValid():
            block_layout = block.layout()
            if block_layout:
                total_lines += max(1, block_layout.lineCount())
            else:
                total_lines += 1
            block = block.next()

        if total_lines == 0:
            total_lines = 1

        line_height = self.fontMetrics().lineSpacing()
        margins = self.contentsMargins()
        frame = self.frameWidth() * 2

        height = (
            total_lines * line_height + margins.top() + margins.bottom() + frame + 4
        )
        self.setFixedHeight(height)

    def resizeEvent(self, event):
        """Recalculate height on resize."""
        super().resizeEvent(event)
        self._adjust_height()

    def set_value(self, value: str):
        """Set the field value and store as original."""
        self._original_value = value or ""
        self.setPlainText(self._original_value)
        self._adjust_height()

    def text(self) -> str:
        """Return the text content (compatibility with QLineEdit interface)."""
        return self.toPlainText()

    def keyPressEvent(self, event):
        key = event.key()

        if key == Qt.Key_Return or key == Qt.Key_Enter:
            self.edit_finished.emit()
            return

        if key == Qt.Key_Escape:
            self.setPlainText(self._original_value)
            self._adjust_height()
            self.edit_cancelled.emit()
            return

        super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        """Remove newlines when pasting."""
        if source.hasText():
            text = source.text().replace("\n", " ").replace("\r", " ")
            self.insertPlainText(text)

    def focusOutEvent(self, event):
        """Save on focus out if value changed."""
        if self.toPlainText() != self._original_value:
            self.edit_finished.emit()
        super().focusOutEvent(event)


class TimeEdit(QLineEdit):
    """DateTime editor with validation."""

    edit_finished = Signal()
    edit_cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_value = ""
        self._is_valid = True
        self.setPlaceholderText("YYYY:MM:DD HH:MM:SS")

    def set_value(self, value: str):
        """Set the field value and store as original."""
        self._original_value = value or ""
        self.setText(self._original_value)
        self._validate()

    def _validate(self):
        """Validate current value and update styling."""
        valid, _ = validate_datetime(self.text())
        self._is_valid = valid
        if valid:
            self.setStyleSheet("")
        else:
            self.setStyleSheet("border: 1px solid red;")

    def get_value(self) -> str | None:
        """Get the validated value."""
        valid, value = validate_datetime(self.text())
        return value if valid else None

    def keyPressEvent(self, event):
        key = event.key()

        if key == Qt.Key_Return or key == Qt.Key_Enter:
            if self._is_valid:
                self.edit_finished.emit()
            return

        if key == Qt.Key_Escape:
            self.setText(self._original_value)
            self._validate()
            self.edit_cancelled.emit()
            return

        super().keyPressEvent(event)
        self._validate()

    def focusOutEvent(self, event):
        """Save on focus out if value changed and valid."""
        if self._is_valid and self.text() != self._original_value:
            self.edit_finished.emit()
        super().focusOutEvent(event)


class ColorSwatchDelegate(QStyledItemDelegate):
    """Delegate that draws a color swatch before item text."""

    SWATCH_SIZE = 12
    SWATCH_MARGIN = 4

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        # Get color from item data
        color_hex = index.data(Qt.UserRole)

        # Initialize style option
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        # Draw background (selection highlight if selected)
        if opt.state & QStyle.State_Selected:
            painter.fillRect(opt.rect, opt.palette.highlight())
        elif opt.state & QStyle.State_MouseOver:
            painter.fillRect(opt.rect, opt.palette.midlight())

        # Draw color swatch
        swatch_rect = QRect(
            opt.rect.left() + self.SWATCH_MARGIN,
            opt.rect.center().y() - self.SWATCH_SIZE // 2,
            self.SWATCH_SIZE,
            self.SWATCH_SIZE,
        )

        swatch_color = QColor(color_hex) if color_hex else QColor("#808080")
        painter.fillRect(swatch_rect, swatch_color)
        painter.setPen(QPen(Qt.black, 1))
        painter.drawRect(swatch_rect)

        # Draw text (standard color, not the label color)
        text_rect = opt.rect.adjusted(
            self.SWATCH_MARGIN * 2 + self.SWATCH_SIZE, 0, 0, 0
        )
        text = index.data(Qt.DisplayRole)

        if opt.state & QStyle.State_Selected:
            painter.setPen(opt.palette.highlightedText().color())
        else:
            painter.setPen(opt.palette.text().color())

        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        size = super().sizeHint(option, index)
        size.setWidth(size.width() + self.SWATCH_SIZE + self.SWATCH_MARGIN * 2)
        return size


class StatusComboBox(QComboBox):
    """Status label combobox with color swatches."""

    value_changed = Signal(str)  # Emits the selected label or empty string

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_value = ""
        self._populating = False

        # Use custom delegate for swatch display
        self.setItemDelegate(ColorSwatchDelegate(self))

        # Populate from config
        for label_name, color_hex in Config.STATUS_LABELS:
            self.addItem(label_name)
            idx = self.count() - 1
            # Store color in UserRole (for delegate)
            self.setItemData(idx, color_hex, Qt.UserRole)

        self.currentIndexChanged.connect(self._on_index_changed)

    def set_value(self, value: str):
        """Set the field value."""
        self._original_value = value or ""
        self._populating = True

        if not value:
            self.setCurrentIndex(0)  # "No Label"
        else:
            idx = self.findText(value)
            if idx >= 0:
                self.setCurrentIndex(idx)
            else:
                self.setCurrentIndex(0)

        self._populating = False

    def _on_index_changed(self, index: int):
        """Handle selection change."""
        if self._populating:
            return

        label = self.currentText()
        # "No Label" means clear the value
        if label == "No Label":
            self.value_changed.emit("")
        else:
            self.value_changed.emit(label)


class EditPanel(QWidget):
    """Panel for editing photo metadata."""

    edit_finished = Signal()  # Emitted when editing is complete (for focus return)
    refresh_requested = Signal(list)  # Emitted when refresh button clicked

    def __init__(self, db_manager: MetadataDBManager, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self._current_items: list[ImageItem] = []
        self._is_multi_select = False
        self._has_missing_data = False

        self._setup_ui()

    def _setup_ui(self):
        """Create the panel UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header with refresh button
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(10, 5, 10, 5)

        header_label = QLabel("Metadata")
        header_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(header_label)

        header_layout.addStretch()

        self.refresh_btn = QPushButton()
        self.refresh_btn.setIcon(QIcon.fromTheme("view-refresh"))
        self.refresh_btn.setToolTip("Refresh from EXIF")
        self.refresh_btn.setFixedSize(24, 24)
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        header_layout.addWidget(self.refresh_btn)

        main_layout.addWidget(header_widget)

        # Create scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # Container widget
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.layout = QGridLayout(container)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(5)
        self.layout.setColumnStretch(0, 30)
        self.layout.setColumnStretch(1, 70)

        row = 0

        # Title
        self.layout.addWidget(
            QLabel(f"{FIELD_DISPLAY_LABELS[DBFields.TITLE]}:"), row, 0
        )
        self.title_edit = TitleEdit()
        self.title_edit.edit_finished.connect(
            lambda: self._on_field_saved(DBFields.TITLE)
        )
        self.title_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.title_edit, row, 1)
        row += 1

        # Description
        desc_label = QLabel(f"{FIELD_DISPLAY_LABELS[DBFields.DESCRIPTION]}:")
        self.layout.addWidget(desc_label, row, 0, Qt.AlignTop)
        self.description_edit = DescriptionEdit()
        self.description_edit.edit_finished.connect(
            lambda: self._on_field_saved(DBFields.DESCRIPTION)
        )
        self.description_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.description_edit, row, 1)
        row += 1

        # Latitude
        self.layout.addWidget(
            QLabel(f"{FIELD_DISPLAY_LABELS[DBFields.LATITUDE]}:"), row, 0
        )
        self.lat_edit = CoordinateEdit(is_latitude=True)
        self.lat_edit.edit_finished.connect(
            lambda: self._on_field_saved(DBFields.LATITUDE)
        )
        self.lat_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.lat_edit, row, 1)
        row += 1

        # Longitude
        self.layout.addWidget(
            QLabel(f"{FIELD_DISPLAY_LABELS[DBFields.LONGITUDE]}:"), row, 0
        )
        self.lon_edit = CoordinateEdit(is_latitude=False)
        self.lon_edit.edit_finished.connect(
            lambda: self._on_field_saved(DBFields.LONGITUDE)
        )
        self.lon_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.lon_edit, row, 1)
        row += 1

        # Keywords
        self.layout.addWidget(
            QLabel(f"{FIELD_DISPLAY_LABELS[DBFields.KEYWORDS]}:"), row, 0
        )
        self.keywords_edit = KeywordsEdit()
        self.keywords_edit.edit_finished.connect(
            lambda: self._on_field_saved(DBFields.KEYWORDS)
        )
        self.keywords_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.keywords_edit, row, 1)
        row += 1

        # Time taken
        self.layout.addWidget(
            QLabel(f"{FIELD_DISPLAY_LABELS[DBFields.TIME_TAKEN]}:"), row, 0
        )
        self.time_edit = TimeEdit()
        self.time_edit.edit_finished.connect(
            lambda: self._on_field_saved(DBFields.TIME_TAKEN)
        )
        self.time_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.time_edit, row, 1)
        row += 1

        # Label (Status)
        self.layout.addWidget(
            QLabel(f"{FIELD_DISPLAY_LABELS[DBFields.LABEL]}:"), row, 0
        )
        self.status_combo = StatusComboBox()
        self.status_combo.value_changed.connect(self._on_status_changed)
        self.layout.addWidget(self.status_combo, row, 1)

        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)

    def _on_refresh_clicked(self):
        """Request refresh of current items from EXIF."""
        if self._current_items:
            self.refresh_requested.emit(list(self._current_items))

    def update_for_selection(self, items: list[ImageItem]):
        """Update the panel for a selection of items.

        Args:
            items: List of selected ImageItem objects.
        """
        self._current_items = items
        self._is_multi_select = len(items) > 1

        if not items:
            self._clear_fields()
            self.refresh_btn.setEnabled(False)
            return

        # Check if any items have missing DB data
        self._has_missing_data = False
        for item in items:
            db = self.db_manager.get_db_for_image(item.path)
            if not db.has_metadata(item.path):
                self._has_missing_data = True
                break
        self.refresh_btn.setEnabled(self._has_missing_data)

        # Gather values for each field
        field_values = self._gather_field_values(items)

        # Update each field
        self._update_field(
            DBFields.TITLE, field_values[DBFields.TITLE], self.title_edit
        )
        self._update_field(
            DBFields.DESCRIPTION,
            field_values[DBFields.DESCRIPTION],
            self.description_edit,
        )
        self._update_coordinate_field(
            DBFields.LATITUDE, field_values[DBFields.LATITUDE], self.lat_edit
        )
        self._update_coordinate_field(
            DBFields.LONGITUDE, field_values[DBFields.LONGITUDE], self.lon_edit
        )
        self._update_field(
            DBFields.KEYWORDS, field_values[DBFields.KEYWORDS], self.keywords_edit
        )
        self._update_field(
            DBFields.TIME_TAKEN, field_values[DBFields.TIME_TAKEN], self.time_edit
        )
        self._update_status_field(field_values[DBFields.LABEL])

    def _gather_field_values(self, items: list[ImageItem]) -> dict:
        """Gather field values from items, using DB only.

        Returns:
            Dictionary mapping field names to values or MULTIPLE_VALUES.
        """
        fields = {field: set() for field in EDITABLE_FIELDS}

        for item in items:
            db = self.db_manager.get_db_for_image(item.path)
            db_data = db.get_metadata(item.path)

            if db_data:
                for field in fields:
                    value = db_data.get(field)
                    fields[field].add(value if value is not None else "")
            else:
                # No DB data yet - show empty for all fields
                for field in fields:
                    fields[field].add("")

        # Convert sets to single values or MULTIPLE_VALUES
        result = {}
        for field, values in fields.items():
            if len(values) == 1:
                result[field] = values.pop()
            else:
                result[field] = MULTIPLE_VALUES

        return result

    def _update_field(self, field_name: str, value, widget):
        """Update a text field widget."""
        if value == MULTIPLE_VALUES:
            widget.set_value(MULTIPLE_VALUES)
        else:
            widget.set_value(value if value else "")

    def _update_coordinate_field(self, field_name: str, value, widget):
        """Update a coordinate field widget."""
        if value == MULTIPLE_VALUES:
            widget.set_value(None)
            widget.setText(MULTIPLE_VALUES)
            widget._original_value = MULTIPLE_VALUES
        elif value == "" or value is None:
            widget.set_value(None)
        else:
            widget.set_value(float(value) if value else None)

    def _update_status_field(self, value):
        """Update the status combobox."""
        if value == MULTIPLE_VALUES:
            self.status_combo.set_value("")
            # We can't easily show "Multiple Values" in a combobox
        else:
            self.status_combo.set_value(value if value else "")

    def _clear_fields(self):
        """Clear all fields."""
        self.title_edit.set_value("")
        self.description_edit.set_value("")
        self.lat_edit.set_value(None)
        self.lon_edit.set_value(None)
        self.keywords_edit.set_value("")
        self.time_edit.set_value("")
        self.status_combo.set_value("")

    def _on_field_saved(self, field_name: str):
        """Handle field save event."""
        if not self._current_items:
            return

        # Get the new value
        value = self._get_field_value(field_name)

        # Save to all selected items
        for item in self._current_items:
            self._save_field_for_item(item, field_name, value)

        self.edit_finished.emit()

    def _get_field_value(self, field_name: str):
        """Get the current value from a field widget."""
        if field_name == DBFields.TITLE:
            return self.title_edit.text() or None
        elif field_name == DBFields.DESCRIPTION:
            text = self.description_edit.toPlainText()
            return text if text else None
        elif field_name == DBFields.LATITUDE:
            return self.lat_edit.get_value()
        elif field_name == DBFields.LONGITUDE:
            return self.lon_edit.get_value()
        elif field_name == DBFields.KEYWORDS:
            return self.keywords_edit.text() or None
        elif field_name == DBFields.TIME_TAKEN:
            return self.time_edit.get_value()
        elif field_name == DBFields.LABEL:
            text = self.status_combo.currentText()
            return text if text != "No Label" else None
        return None

    def _save_field_for_item(self, item: ImageItem, field_name: str, value):
        """Save a single field for an item."""
        db = self.db_manager.get_db_for_image(item.path)

        # Get existing data or create new
        existing = db.get_metadata(item.path)
        if existing:
            data = existing.copy()
        else:
            # Initialize with empty values
            data = {field: None for field in EDITABLE_FIELDS}

        # Update the specific field
        data[field_name] = value

        # Save to database
        db.save_metadata(item.path, data)

        # Update item's cached db_metadata
        item.db_metadata = data

    def _on_status_changed(self, label: str):
        """Handle status combobox change."""
        if not self._current_items:
            return

        value = label if label else None

        for item in self._current_items:
            self._save_field_for_item(item, DBFields.LABEL, value)

    def _on_edit_cancelled(self):
        """Handle edit cancellation."""
        self.edit_finished.emit()
