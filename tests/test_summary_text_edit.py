"""Shared summary widget text and formatting behavior."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QTextCharFormat
from PySide6.QtWidgets import QApplication, QLineEdit, QTextEdit, QVBoxLayout, QWidget
import pytest

from piqopiqo.components.summary_text_edit import SummaryLine, SummaryTextEdit


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(params=["text", "strings", "mixed"])
def scrollable_content(request, qapp):  # noqa: ARG001
    lines = [f"Line {index}" for index in range(12)]
    lines.append("Backup: /tmp/" + "long-folder-name/" * 40 + "order.json")
    if request.param == "text":
        return "\n".join(lines)
    if request.param == "mixed":
        warning_format = QTextCharFormat()
        warning_format.setForeground(QColor("red"))
        return [*lines[:-1], SummaryLine(lines[-1], warning_format)]
    return lines


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


def test_summary_starts_at_top_left_and_resets_after_updates_and_show(
    qapp, scrollable_content
) -> None:
    summary = SummaryTextEdit(scrollable_content)
    summary.resize(480, summary.height())
    assert summary.textCursor().position() == 0
    summary.show()
    qapp.processEvents()

    horizontal = summary.horizontalScrollBar()
    vertical = summary.verticalScrollBar()
    assert horizontal.maximum() > 0
    assert vertical.maximum() > 0
    assert horizontal.value() == 0
    assert vertical.value() == 0

    horizontal.setValue(horizontal.maximum())
    vertical.setValue(vertical.maximum())
    qapp.processEvents()
    assert horizontal.value() > 0
    assert vertical.value() > 0

    summary.set_lines(scrollable_content)
    assert summary.textCursor().position() == 0
    assert horizontal.value() == 0
    assert vertical.value() == 0
    qapp.processEvents()
    assert horizontal.value() == 0
    assert vertical.value() == 0

    horizontal.setValue(horizontal.maximum())
    vertical.setValue(vertical.maximum())
    summary.hide()
    summary.show()
    qapp.processEvents()
    assert horizontal.value() == 0
    assert vertical.value() == 0
    summary.close()


def test_manual_summary_scroll_survives_focus_changes_and_resize(
    qapp, scrollable_content
) -> None:
    window = QWidget()
    layout = QVBoxLayout(window)
    summary = SummaryTextEdit(scrollable_content, window)
    other_field = QLineEdit(window)
    layout.addWidget(summary)
    layout.addWidget(other_field)
    window.resize(480, window.sizeHint().height())
    window.show()
    qapp.processEvents()

    other_field.setFocus()
    qapp.processEvents()
    horizontal = summary.horizontalScrollBar()
    vertical = summary.verticalScrollBar()
    horizontal.setValue(horizontal.maximum() // 2)
    vertical.setValue(vertical.maximum() // 2)
    scrolled_position = (horizontal.value(), vertical.value())
    assert all(value > 0 for value in scrolled_position)

    summary.setFocus()
    qapp.processEvents()
    assert (horizontal.value(), vertical.value()) == scrolled_position
    other_field.setFocus()
    window.resize(window.width() + 40, window.height())
    qapp.processEvents()
    assert (horizontal.value(), vertical.value()) == scrolled_position
    window.close()
