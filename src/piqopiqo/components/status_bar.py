"""Status bar with loading progress."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QWidget,
)

from piqopiqo.ssf.settings_state import RuntimeSettingKey, get_runtime_setting


class _ColumnCountControl(QWidget):
    """Compact - [count] + control used in the status bar center."""

    decrement_requested = Signal()
    increment_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.decrement_button = QPushButton("-")
        self.decrement_button.setObjectName("status_bar_columns_decrement")
        self.decrement_button.setFixedWidth(24)
        self.decrement_button.clicked.connect(self.decrement_requested.emit)
        layout.addWidget(self.decrement_button)

        self.value_label = QLabel("0")
        self.value_label.setObjectName("status_bar_columns_value")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setMinimumWidth(28)
        layout.addWidget(self.value_label)

        self.increment_button = QPushButton("+")
        self.increment_button.setObjectName("status_bar_columns_increment")
        self.increment_button.setFixedWidth(24)
        self.increment_button.clicked.connect(self.increment_requested.emit)
        layout.addWidget(self.increment_button)

    def set_count(self, value: int, min_value: int, max_value: int) -> None:
        self.value_label.setText(str(int(value)))
        self.decrement_button.setEnabled(int(value) > int(min_value))
        self.increment_button.setEnabled(int(value) < int(max_value))


class LoadingStatusBar(QStatusBar):
    """Status bar with photo count, column controls, and loading progress."""

    show_errors_requested = Signal()
    decrement_columns_requested = Signal()
    increment_columns_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._thumb_total = 0
        self._thumb_completed = 0
        self._exif_total = 0
        self._exif_completed = 0
        self._photo_count = 0
        self._filtered_count = 0
        self._selected_count = 0
        self._has_errors = False

        self._setup_ui()

    def _setup_ui(self):
        side_padding = self._read_side_padding()

        self._left_cluster = QWidget(self)
        left_layout = QHBoxLayout(self._left_cluster)
        left_layout.setContentsMargins(side_padding, 0, 0, 0)
        left_layout.setSpacing(0)
        self.count_label = QLabel("0 photos / 0 selected")
        self.count_label.setObjectName("status_bar_count_label")
        left_layout.addWidget(self.count_label)
        left_layout.addStretch(1)
        self.addWidget(self._left_cluster, 1)

        self._right_cluster = QWidget(self)
        right_layout = QHBoxLayout(self._right_cluster)
        right_layout.setContentsMargins(0, 0, side_padding, 0)
        right_layout.setSpacing(8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        right_layout.addWidget(self.progress_bar)

        self.error_btn = QPushButton()
        self.error_btn.setIcon(QIcon.fromTheme("dialog-warning"))
        self.error_btn.setText("Errors")
        self.error_btn.setToolTip("There were errors during loading")
        self.error_btn.setFlat(True)
        self.error_btn.clicked.connect(self.show_errors_requested.emit)
        self.error_btn.hide()
        right_layout.addWidget(self.error_btn)
        self.addPermanentWidget(self._right_cluster)

        self._column_control = _ColumnCountControl(self)
        self.columns_decrement_btn = self._column_control.decrement_button
        self.columns_value_label = self._column_control.value_label
        self.columns_increment_btn = self._column_control.increment_button
        self._column_control.decrement_requested.connect(
            self.decrement_columns_requested.emit
        )
        self._column_control.increment_requested.connect(
            self.increment_columns_requested.emit
        )
        self._column_control.show()
        self._position_column_control()

        self.setSizeGripEnabled(False)

    def _read_side_padding(self) -> int:
        try:
            padding = int(get_runtime_setting(RuntimeSettingKey.STATUS_BAR_SIDE_PADDING))
        except Exception:
            padding = 10
        return max(0, padding)

    def _position_column_control(self) -> None:
        if not self._column_control.isVisible():
            return
        hint = self._column_control.sizeHint()
        width = hint.width()
        height = hint.height()
        x = max(0, (self.width() - width) // 2)
        y = max(0, (self.height() - height) // 2)
        self._column_control.setGeometry(x, y, width, height)
        self._column_control.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_column_control()

    def showEvent(self, event):
        super().showEvent(event)
        self._position_column_control()

    def set_column_count(self, value: int, min_value: int, max_value: int) -> None:
        min_cols = max(1, int(min_value))
        max_cols = max(1, int(max_value))
        if max_cols < min_cols:
            max_cols = min_cols
        cols = max(min_cols, min(int(value), max_cols))
        self._column_control.set_count(cols, min_cols, max_cols)
        self._position_column_control()

    def set_photo_count(
        self,
        total: int,
        filtered: int | None = None,
        selected: int = 0,
    ):
        """Set the photo/selection count display."""
        self._photo_count = int(total)
        self._filtered_count = int(filtered) if filtered is not None else int(total)
        self._selected_count = max(0, int(selected))

        if filtered is not None and int(filtered) != int(total):
            self.count_label.setText(
                f"{int(filtered)} of {int(total)} photos / {self._selected_count} selected"
            )
        else:
            self.count_label.setText(f"{int(total)} photos / {self._selected_count} selected")

    def set_thumb_progress(self, completed: int, total: int):
        """Update thumbnail loading progress."""
        self._thumb_completed = completed
        self._thumb_total = total
        self._update_progress()

    def set_exif_progress(self, completed: int, total: int):
        """Update EXIF loading progress."""
        self._exif_completed = completed
        self._exif_total = total
        self._update_progress()

    def _update_progress(self):
        """Update the combined progress bar."""
        total = self._thumb_total + self._exif_total
        completed = self._thumb_completed + self._exif_completed

        if total == 0:
            self.progress_bar.hide()
            return

        if completed >= total:
            self.progress_bar.hide()
        else:
            self.progress_bar.show()
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(completed)
            self.progress_bar.setFormat(f"{completed}/{total}")

    def set_has_errors(self, has_errors: bool):
        """Show or hide the error button."""
        self._has_errors = has_errors
        self.error_btn.setVisible(has_errors)

    def reset(self):
        """Reset all progress for new folder load."""
        self._thumb_total = 0
        self._thumb_completed = 0
        self._exif_total = 0
        self._exif_completed = 0
        self._has_errors = False
        self.progress_bar.hide()
        self.error_btn.hide()
