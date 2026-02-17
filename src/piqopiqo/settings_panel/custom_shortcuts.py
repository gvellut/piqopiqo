"""Custom editor widget for keyboard shortcuts."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFormLayout, QLineEdit, QWidget

from ..shortcuts import Shortcut


class ShortcutsEditor(QWidget):
    """Manual shortcut editor (text input, no key listener capture)."""

    value_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inputs: dict[Shortcut, QLineEdit] = {}

        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        for shortcut in Shortcut:
            line_edit = QLineEdit()
            line_edit.setPlaceholderText("e.g. ctrl+a")
            line_edit.editingFinished.connect(self.value_changed)
            layout.addRow(shortcut.value, line_edit)
            self._inputs[shortcut] = line_edit

    def set_value(self, value: dict[Shortcut, str] | dict[str, str] | None) -> None:
        mapping = value or {}
        for key, line_edit in self._inputs.items():
            text = ""
            if key in mapping:
                text = str(mapping[key])
            elif key.value in mapping:
                text = str(mapping[key.value])
            elif key.name in mapping:
                text = str(mapping[key.name])
            line_edit.setText(text)

    def get_value(self) -> dict[Shortcut, str]:
        out: dict[Shortcut, str] = {}
        for key, line_edit in self._inputs.items():
            text = line_edit.text().strip()
            if text:
                out[key] = text
        return out
