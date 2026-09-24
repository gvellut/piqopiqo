"""Tests for the shared read-only summary control."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QTextEdit
import pytest

from piqopiqo.components.summary_text_edit import SummaryTextEdit


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.mark.parametrize("line_count", [1, 5, 8])
def test_long_line_does_not_create_a_small_vertical_scroll_range(
    qapp, line_count: int
) -> None:
    lines = [*(f"Line {index}" for index in range(line_count - 1)), "x" * 500]
    summary = SummaryTextEdit("\n".join(lines))
    summary.resize(520, summary.height())
    summary.show()
    qapp.processEvents()

    assert summary.isReadOnly()
    assert summary.lineWrapMode() == QTextEdit.LineWrapMode.NoWrap
    assert summary.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    assert summary.palette().color(QPalette.ColorRole.Base) == summary.palette().color(
        QPalette.ColorRole.AlternateBase
    )
    assert summary.horizontalScrollBar().maximum() > 0
    assert summary.verticalScrollBar().maximum() == 0


def test_more_than_eight_lines_remain_scrollable(qapp) -> None:
    summary = SummaryTextEdit("\n".join(f"Line {index}" for index in range(12)))
    summary.show()
    qapp.processEvents()

    assert summary.verticalScrollBar().maximum() > 0
