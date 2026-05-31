"""Status bar with loading progress and counts."""

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QWidget,
)

from piqopiqo.components.ellided_label import EllidedLabel
from piqopiqo.ssf.settings_state import RuntimeSettingKey, get_runtime_setting

NO_FOLDER_LOADED_TEXT = "No folder loaded"
_FOLDER_LABEL_SIDE_GAP = 8


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
        self._selection_progress_active = False
        self._folder_label_max_width_ratio = self._read_folder_label_max_width_ratio()
        self._has_temporary_message = False

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
        self._right_cluster.setMinimumHeight(
            max(
                self.progress_bar.sizeHint().height(),
                self.error_btn.sizeHint().height(),
            )
        )
        self.addPermanentWidget(self._right_cluster)

        self.folder_label = EllidedLabel(NO_FOLDER_LOADED_TEXT, self)
        self.folder_label.setObjectName("status_bar_folder_label")
        self.folder_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self.folder_label.setToolTip(NO_FOLDER_LOADED_TEXT)
        self.folder_label.raise_()

        self.setSizeGripEnabled(False)
        self.messageChanged.connect(self._on_message_changed)
        self._schedule_folder_label_geometry_update()

    def _read_side_padding(self) -> int:
        try:
            padding = int(
                get_runtime_setting(RuntimeSettingKey.STATUS_BAR_SIDE_PADDING)
            )
        except Exception:
            padding = 10
        return max(0, padding)

    def _read_folder_label_max_width_ratio(self) -> float:
        try:
            ratio = float(
                get_runtime_setting(
                    RuntimeSettingKey.STATUS_BAR_FOLDER_LABEL_MAX_WIDTH_RATIO
                )
            )
        except Exception:
            ratio = 0.5
        return max(0.0, min(1.0, ratio))

    def set_folder_label(self, text: str | None):
        """Set the centered folder label display."""
        display_text = str(text or "").strip() or NO_FOLDER_LOADED_TEXT
        self.folder_label.setText(display_text)
        self.folder_label.setToolTip(display_text)
        self._schedule_folder_label_geometry_update()

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
                f"{int(filtered)} of {int(total)} photos / "
                f"{self._selected_count} selected"
            )
        else:
            self.count_label.setText(
                f"{int(total)} photos / {self._selected_count} selected"
            )
        self._schedule_folder_label_geometry_update()

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

    def set_selection_progress_active(self, active: bool) -> None:
        """Show an indeterminate progress bar while selection panels aggregate."""
        next_active = bool(active)
        if self._selection_progress_active == next_active:
            return
        self._selection_progress_active = next_active
        self._update_progress()

    def _update_progress(self):
        """Update the combined progress bar."""
        total = self._thumb_total + self._exif_total
        completed = self._thumb_completed + self._exif_completed
        loading_active = total > 0 and completed < total

        if loading_active:
            self.progress_bar.show()
            self.progress_bar.setTextVisible(True)
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(completed)
            self.progress_bar.setFormat(f"{completed}/{total}")
        elif self._selection_progress_active:
            self.progress_bar.show()
            self.progress_bar.setTextVisible(False)
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setTextVisible(True)
            self.progress_bar.hide()
        self._schedule_folder_label_geometry_update()

    def set_has_errors(self, has_errors: bool):
        """Show or hide the error button."""
        self._has_errors = has_errors
        self.error_btn.setVisible(has_errors)
        self._schedule_folder_label_geometry_update()

    def reset(self):
        """Reset all progress for new folder load."""
        self._thumb_total = 0
        self._thumb_completed = 0
        self._exif_total = 0
        self._exif_completed = 0
        self._has_errors = False
        self._selection_progress_active = False
        self.progress_bar.hide()
        self.progress_bar.setTextVisible(True)
        self.error_btn.hide()
        self._schedule_folder_label_geometry_update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_folder_label_geometry()

    def _on_message_changed(self, message: str) -> None:
        self._has_temporary_message = bool(message)
        self.folder_label.setVisible(not self._has_temporary_message)
        if not self._has_temporary_message:
            self._schedule_folder_label_geometry_update()

    def _schedule_folder_label_geometry_update(self) -> None:
        self._update_folder_label_geometry()
        QTimer.singleShot(0, self._update_folder_label_geometry)

    def _update_folder_label_geometry(self) -> None:
        if not hasattr(self, "folder_label") or self._has_temporary_message:
            return

        status_rect = self.contentsRect()
        if status_rect.width() <= 0 or status_rect.height() <= 0:
            return

        center_x = status_rect.x() + status_rect.width() // 2
        max_ratio_width = int(status_rect.width() * self._folder_label_max_width_ratio)

        left_limit = status_rect.left()
        if self.count_label.isVisible():
            count_pos = self.count_label.mapTo(self, QPoint(0, 0))
            left_limit = max(
                left_limit,
                count_pos.x() + self.count_label.width() + _FOLDER_LABEL_SIDE_GAP,
            )

        right_limit = status_rect.right() + 1
        visible_right_widgets = [
            widget
            for widget in (self.progress_bar, self.error_btn)
            if widget.isVisible()
        ]
        for widget in visible_right_widgets:
            widget_pos = widget.mapTo(self, QPoint(0, 0))
            right_limit = min(right_limit, widget_pos.x() - _FOLDER_LABEL_SIDE_GAP)

        centered_available = max(
            0,
            2 * min(center_x - left_limit, right_limit - center_x),
        )
        metrics = self.folder_label.fontMetrics()
        text_width = metrics.size(
            Qt.TextFlag.TextSingleLine,
            self.folder_label.full_text,
        ).width()
        label_width = max(0, min(text_width, max_ratio_width, centered_available))
        label_height = min(self.folder_label.sizeHint().height(), status_rect.height())
        label_x = center_x - label_width // 2
        label_y = status_rect.y() + max(0, (status_rect.height() - label_height) // 2)

        self.folder_label.setGeometry(label_x, label_y, label_width, label_height)
        self.folder_label.raise_()
