"""Editable field widgets for metadata editing."""

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
)

from piqopiqo.config import Config
from piqopiqo.metadata.metadata_db import (
    validate_datetime,
    validate_latitude,
    validate_longitude,
)

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

    def focusInEvent(self, event):
        """Clear Multiple Values placeholder on focus."""
        if self.text() == MULTIPLE_VALUES:
            self.clear()
        super().focusInEvent(event)

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
        """Save on focus out if value changed and not Multiple Values."""
        text = self.text()
        if text == MULTIPLE_VALUES:
            super().focusOutEvent(event)
            return
        if text != self._original_value:
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

    def focusInEvent(self, event):
        """Clear Multiple Values placeholder on focus."""
        if self.toPlainText() == MULTIPLE_VALUES:
            self.clear()
        super().focusInEvent(event)

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
        """Save on focus out if value changed and not Multiple Values."""
        text = self.toPlainText()
        if text == MULTIPLE_VALUES:
            super().focusOutEvent(event)
            return
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

    def focusInEvent(self, event):
        """Clear Multiple Values placeholder on focus."""
        if self.text() == MULTIPLE_VALUES:
            self.clear()
            self._validate()
        super().focusInEvent(event)

    def _validate(self):
        """Validate current value and update styling."""
        text = self.text()
        if text == MULTIPLE_VALUES:
            # Do not show red border for Multiple Values
            self._is_valid = True
            self.setStyleSheet("")
            return
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
        """Save on focus out if value changed, valid, and not Multiple Values."""
        text = self.text()
        if text == MULTIPLE_VALUES:
            super().focusOutEvent(event)
            return
        if self._is_valid and text != self._original_value:
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

    def focusInEvent(self, event):
        """Clear Multiple Values placeholder on focus."""
        if self.toPlainText() == MULTIPLE_VALUES:
            self.clear()
        super().focusInEvent(event)

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
        """Save on focus out if value changed and not Multiple Values."""
        text = self.toPlainText()
        if text == MULTIPLE_VALUES:
            super().focusOutEvent(event)
            return
        if text != self._original_value:
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
        self.setPlaceholderText("YYYY-MM-DD HH:MM:SS")

    def set_value(self, value: datetime | str | None):
        """Set the field value and store as original.

        Accepts a datetime object (from DB) or string (for MULTIPLE_VALUES).
        Displays as ISO format string for editing.
        """
        if isinstance(value, datetime):
            self._original_value = value.strftime("%Y-%m-%d %H:%M:%S")
        else:
            self._original_value = value or ""
        self.setText(self._original_value)
        self._validate()

    def focusInEvent(self, event):
        """Clear Multiple Values placeholder on focus."""
        if self.text() == MULTIPLE_VALUES:
            self.clear()
            self._validate()
        super().focusInEvent(event)

    def _validate(self):
        """Validate current value and update styling."""
        text = self.text()
        if text == MULTIPLE_VALUES:
            # Do not show red border for Multiple Values
            self._is_valid = True
            self.setStyleSheet("")
            return
        valid, _ = validate_datetime(text)
        self._is_valid = valid
        if valid:
            self.setStyleSheet("")
        else:
            self.setStyleSheet("border: 1px solid red;")

    def get_value(self) -> datetime | None:
        """Get the validated value as a datetime object."""
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
        """Save on focus out if value changed, valid, and not Multiple Values."""
        text = self.text()
        if text == MULTIPLE_VALUES:
            super().focusOutEvent(event)
            return
        if self._is_valid and text != self._original_value:
            self.edit_finished.emit()
        super().focusOutEvent(event)
