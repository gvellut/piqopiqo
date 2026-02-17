"""Custom editor widget for status labels."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..model import StatusLabel


class _StatusLabelRow(QWidget):
    remove_requested = Signal(object)
    value_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name")
        self.name_edit.editingFinished.connect(self.value_changed)
        layout.addWidget(self.name_edit, 2)

        self.color_edit = QLineEdit()
        self.color_edit.setPlaceholderText("#RRGGBB")
        self.color_edit.editingFinished.connect(self.value_changed)
        layout.addWidget(self.color_edit, 1)

        self.index_spin = QSpinBox()
        self.index_spin.setRange(1, 9)
        self.index_spin.valueChanged.connect(self.value_changed)
        layout.addWidget(self.index_spin, 0)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(remove_btn, 0)

    def set_value(self, value: StatusLabel) -> None:
        self.name_edit.setText(value.name)
        self.color_edit.setText(value.color)
        self.index_spin.setValue(int(value.index))

    def get_value(self) -> StatusLabel | None:
        name = self.name_edit.text().strip()
        color = self.color_edit.text().strip()
        if not name:
            return None
        if not color:
            color = "#000000"
        return StatusLabel(name=name, color=color, index=int(self.index_spin.value()))


class StatusLabelsEditor(QWidget):
    """Editor for STATUS_LABELS: list of (name, color, index)."""

    value_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[_StatusLabelRow] = []

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        self._layout.addWidget(self._rows_container)

        add_btn = QPushButton("Add Label")
        add_btn.clicked.connect(self._on_add_row)
        self._layout.addWidget(add_btn)

    def _on_add_row(self):
        self._add_row(StatusLabel(name="", color="#000000", index=1))
        self.value_changed.emit()

    def _add_row(self, value: StatusLabel):
        row = _StatusLabelRow()
        row.set_value(value)
        row.remove_requested.connect(self._remove_row)
        row.value_changed.connect(self.value_changed)
        self._rows.append(row)
        self._rows_layout.addWidget(row)

    def _remove_row(self, row: _StatusLabelRow):
        if row not in self._rows:
            return
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.deleteLater()
        self.value_changed.emit()

    def set_value(self, value: list[StatusLabel] | None) -> None:
        for row in self._rows:
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows = []

        for item in value or []:
            self._add_row(item)

    def get_value(self) -> list[StatusLabel]:
        out: list[StatusLabel] = []
        used_indices: set[int] = set()

        for row in self._rows:
            status = row.get_value()
            if status is None:
                continue
            if status.index in used_indices:
                continue
            used_indices.add(status.index)
            out.append(status)

        return out
