"""Read-only multiline summary with room for a horizontal scrollbar."""

from collections.abc import Sequence

from attrs import define
from PySide6.QtGui import QPalette, QTextCharFormat
from PySide6.QtWidgets import QTextEdit, QWidget


@define(frozen=True)
class SummaryLine:
    text: str
    text_format: QTextCharFormat | None = None


class SummaryTextEdit(QTextEdit):
    """Show up to eight unwrapped lines without clipping the last visible line."""

    def __init__(
        self,
        content: str | Sequence[str | SummaryLine],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        palette = self.palette()
        palette.setColor(
            QPalette.ColorRole.Base,
            palette.color(QPalette.ColorRole.AlternateBase),
        )
        self.setPalette(palette)

        self.set_lines(content)

    def set_lines(self, content: str | Sequence[str | SummaryLine]) -> None:
        """Display plain text or lines with optional character formatting."""
        if isinstance(content, str):
            self.setPlainText(content)
            line_count = len(content.splitlines())
        else:
            self.clear()
            cursor = self.textCursor()
            normal_format = QTextCharFormat()
            for index, line in enumerate(content):
                if index:
                    cursor.insertBlock()
                if isinstance(line, str):
                    cursor.insertText(line, normal_format)
                else:
                    line_format = (
                        line.text_format
                        if line.text_format is not None
                        else normal_format
                    )
                    cursor.insertText(line.text, line_format)
            line_count = len(content)

        visible_lines = min(max(line_count, 2), 8)
        # The extra line leaves room when a long line adds a horizontal scrollbar.
        text_height = self.fontMetrics().lineSpacing() * (visible_lines + 1)
        frame_height = self.frameWidth() * 2
        self.setFixedHeight(text_height + frame_height + 16)
