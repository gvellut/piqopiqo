"""Custom editor widget for keyboard shortcuts."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFormLayout, QGridLayout, QGroupBox, QLineEdit, QWidget

from piqopiqo.shortcuts import Shortcut


class ShortcutsEditor(QWidget):
    """Manual shortcut editor (text input, no key listener capture)."""

    value_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inputs: dict[Shortcut, QLineEdit] = {}

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(12)

        section_specs: list[tuple[str, tuple[Shortcut, ...]]] = [
            (
                "Set Labels",
                (
                    Shortcut.LABEL_1,
                    Shortcut.LABEL_2,
                    Shortcut.LABEL_3,
                    Shortcut.LABEL_4,
                    Shortcut.LABEL_5,
                    Shortcut.LABEL_6,
                    Shortcut.LABEL_7,
                    Shortcut.LABEL_8,
                    Shortcut.LABEL_9,
                    Shortcut.LABEL_NONE,
                ),
            ),
            (
                "Filter Shortcuts",
                (
                    Shortcut.FILTER_LABEL_1,
                    Shortcut.FILTER_LABEL_2,
                    Shortcut.FILTER_LABEL_3,
                    Shortcut.FILTER_LABEL_4,
                    Shortcut.FILTER_LABEL_5,
                    Shortcut.FILTER_LABEL_6,
                    Shortcut.FILTER_LABEL_7,
                    Shortcut.FILTER_LABEL_8,
                    Shortcut.FILTER_LABEL_9,
                    Shortcut.FILTER_LABEL_NONE,
                    Shortcut.FILTER_FOLDER_ALL,
                    Shortcut.FILTER_FOLDER_NEXT,
                    Shortcut.FILTER_FOLDER_PREV,
                    Shortcut.FILTER_CLEAR_ALL,
                    Shortcut.FILTER_FOCUS_SEARCH,
                ),
            ),
            (
                "Grid Shortcuts",
                (
                    Shortcut.SELECT_ALL,
                    Shortcut.COLLAPSE_TO_LAST_SELECTED,
                ),
            ),
            (
                "Fullscreen Shortcuts",
                (
                    Shortcut.ZOOM_IN,
                    Shortcut.ZOOM_OUT,
                    Shortcut.ZOOM_RESET,
                ),
            ),
        ]

        for i, (section_title, section_shortcuts) in enumerate(section_specs):
            row = i // 2
            col = i % 2
            section_box = QGroupBox(section_title, self)
            section_layout = QFormLayout(section_box)
            section_layout.setContentsMargins(8, 8, 8, 8)

            for shortcut in section_shortcuts:
                line_edit = QLineEdit()
                line_edit.setPlaceholderText("e.g. ctrl+a")
                line_edit.editingFinished.connect(self.value_changed)
                section_layout.addRow(shortcut.label, line_edit)
                self._inputs[shortcut] = line_edit

            layout.addWidget(section_box, row, col)

        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)

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
