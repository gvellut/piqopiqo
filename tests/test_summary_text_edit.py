"""Shared summary widget text and formatting behavior."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QTextCharFormat
from PySide6.QtWidgets import QApplication, QTextEdit
import pytest

from piqopiqo.components.summary_text_edit import SummaryLine, SummaryTextEdit


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_summary_accepts_plain_text_and_mixed_formatted_lines(qapp) -> None:  # noqa: ARG001
    summary = SummaryTextEdit("First\nSecond")
    assert summary.toPlainText() == "First\nSecond"
    assert summary.isReadOnly()
    assert summary.lineWrapMode() == QTextEdit.LineWrapMode.NoWrap

    warning_format = QTextCharFormat()
    warning_format.setForeground(QBrush(Qt.GlobalColor.red))
    summary.set_lines([
        "Before",
        SummaryLine("Warning", warning_format),
        "After",
    ])

    assert summary.toPlainText() == "Before\nWarning\nAfter"
    document = summary.document()
    assert document.find("Warning").charFormat().foreground().color() == QColor(
        Qt.GlobalColor.red
    )
    assert document.find("Before").charFormat().foreground().color() != QColor(
        Qt.GlobalColor.red
    )
    assert document.find("After").charFormat().foreground().color() != QColor(
        Qt.GlobalColor.red
    )

    summary.set_lines([SummaryLine("Unformatted"), "<b>Literal & plain</b>"])
    assert summary.toPlainText() == "Unformatted\n<b>Literal & plain</b>"
    assert summary.document().find(
        "Unformatted"
    ).charFormat().foreground().color() != QColor(Qt.GlobalColor.red)
    summary.set_lines("Plain text after formatting")
    assert summary.document().find(
        "Plain text"
    ).charFormat().foreground().color() != QColor(Qt.GlobalColor.red)


def test_summary_height_updates_with_new_lines(qapp) -> None:  # noqa: ARG001
    summary = SummaryTextEdit("One")
    short_height = summary.height()

    summary.set_lines([f"Line {index}" for index in range(10)])
    tall_height = summary.height()
    summary.set_lines(["One"])

    assert tall_height > short_height
    assert summary.height() == short_height


@pytest.mark.parametrize(
    "content",
    ["One\nTwo\nThree\nFour\n", ["One\nTwo", SummaryLine("Three\nFour\n")]],
)
def test_summary_counts_embedded_newlines_for_height(qapp, content) -> None:  # noqa: ARG001
    summary = SummaryTextEdit(content)
    explicit_lines = SummaryTextEdit(["One", "Two", "Three", "Four", ""])

    assert summary.toPlainText() == explicit_lines.toPlainText()
    assert summary.height() == explicit_lines.height()
