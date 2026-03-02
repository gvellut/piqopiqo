"""Column number selector component."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QWidget,
)


class ColumnNumberSelector(QWidget):
    """Compact ``- [count] +`` selector with bounded increment/decrement."""

    decrement_requested = Signal()
    increment_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("column_number_selector")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.decrement_button = QToolButton(self)
        self.decrement_button.setObjectName("column_selector_decrement")
        self.decrement_button.setAutoRaise(True)
        self.decrement_button.setText("-")
        self.decrement_button.setFixedSize(20, 18)
        self.decrement_button.clicked.connect(self.decrement_requested.emit)
        layout.addWidget(self.decrement_button)

        self.value_label = QLabel("0", self)
        self.value_label.setObjectName("column_selector_value")
        self.value_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self.value_label.setMinimumWidth(24)
        self.value_label.setFixedHeight(18)
        layout.addWidget(self.value_label)

        self.increment_button = QToolButton(self)
        self.increment_button.setObjectName("column_selector_increment")
        self.increment_button.setAutoRaise(True)
        self.increment_button.setText("+")
        self.increment_button.setFixedSize(20, 18)
        self.increment_button.clicked.connect(self.increment_requested.emit)
        layout.addWidget(self.increment_button)

    def set_value(self, value: int, min_value: int, max_value: int) -> None:
        min_cols = max(1, int(min_value))
        max_cols = max(1, int(max_value))
        if max_cols < min_cols:
            max_cols = min_cols

        cols = max(min_cols, min(int(value), max_cols))
        self.value_label.setText(str(cols))
        self.decrement_button.setEnabled(cols > min_cols)
        self.increment_button.setEnabled(cols < max_cols)
