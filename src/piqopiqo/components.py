from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel


class EllidedLabel(QLabel):
    """QLabel subclass that automatically adds ellipsis on the right
    when text is too long."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._full_text = text
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)

    def setText(self, text: str):
        self._full_text = text
        self._update_elided_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elided_text()

    def _update_elided_text(self):
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._full_text, Qt.ElideRight, self.width())
        super().setText(elided)
