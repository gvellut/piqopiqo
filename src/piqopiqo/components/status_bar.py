"""Status bar with loading progress and counts."""

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


class LoadingStatusBar(QStatusBar):
    """Status bar with photo count and loading progress."""

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
        self.error_btn.hide()
        right_layout.addWidget(self.error_btn)
        self.addPermanentWidget(self._right_cluster)

        self.setSizeGripEnabled(False)

    def _read_side_padding(self) -> int:
        try:
            padding = int(get_runtime_setting(RuntimeSettingKey.STATUS_BAR_SIDE_PADDING))
        except Exception:
            padding = 10
        return max(0, padding)

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
