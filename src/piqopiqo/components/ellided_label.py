"""Ellided label that truncates text with ellipsis."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel


class EllidedLabel(QLabel):
    """QLabel subclass that truncates long text in the chosen direction."""

    def __init__(self, text="", parent=None, *, elide_mode=Qt.ElideRight):
        super().__init__(text, parent)
        self._full_text = text
        self._elide_mode = elide_mode
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)

    @property
    def full_text(self) -> str:
        return self._full_text

    def setText(self, text: str):
        self._full_text = text
        self._update_elided_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elided_text()

    def _update_elided_text(self):
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._full_text, self._elide_mode, self.width())
        super().setText(elided)
