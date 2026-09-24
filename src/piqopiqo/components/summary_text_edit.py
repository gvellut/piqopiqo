"""Read-only multiline summary with room for a horizontal scrollbar."""

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QTextEdit, QWidget


class SummaryTextEdit(QTextEdit):
    """Show up to eight unwrapped lines without clipping the last visible line."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setPlainText(text)

        palette = self.palette()
        palette.setColor(
            QPalette.ColorRole.Base,
            palette.color(QPalette.ColorRole.AlternateBase),
        )
        self.setPalette(palette)

        visible_lines = min(max(len(text.splitlines()), 2), 8)
        # The extra line leaves room when a long line adds a horizontal scrollbar.
        text_height = self.fontMetrics().lineSpacing() * (visible_lines + 1)
        frame_height = self.frameWidth() * 2
        self.setFixedHeight(text_height + frame_height + 16)
