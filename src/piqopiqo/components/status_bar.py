"""Status bar with loading progress."""

from PySide6.QtCore import Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QLabel,
    QProgressBar,
    QPushButton,
    QStatusBar,
)


class LoadingStatusBar(QStatusBar):
    """Status bar with photo count and loading progress."""

    show_errors_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

        self._thumb_total = 0
        self._thumb_completed = 0
        self._exif_total = 0
        self._exif_completed = 0
        self._photo_count = 0
        self._filtered_count = 0
        self._has_errors = False

    def _setup_ui(self):
        # Photo count label (left side)
        self.count_label = QLabel("0 photos")
        self.addWidget(self.count_label, 1)

        # Progress bar (center, hidden when complete)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        self.addWidget(self.progress_bar)

        # Error button (right side, hidden when no errors)
        self.error_btn = QPushButton()
        self.error_btn.setIcon(QIcon.fromTheme("dialog-warning"))
        self.error_btn.setText("Errors")
        self.error_btn.setToolTip("There were errors during loading")
        self.error_btn.setFlat(True)
        self.error_btn.clicked.connect(self.show_errors_requested.emit)
        self.error_btn.hide()
        self.addPermanentWidget(self.error_btn)

        self.setSizeGripEnabled(False)

    def set_photo_count(self, total: int, filtered: int | None = None):
        """Set the photo count display."""
        self._photo_count = total
        self._filtered_count = filtered if filtered is not None else total

        if filtered is not None and filtered != total:
            self.count_label.setText(f"{filtered} of {total} photos")
        else:
            self.count_label.setText(f"{total} photos")

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
