"""Tests for the Save EXIF tool dialog."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.components.summary_text_edit import SummaryTextEdit
from piqopiqo.model import ImageItem
from piqopiqo.tools.save_exif import SaveExifDialog


class _FakeMediaManager(QObject):
    write_progress = Signal(int, int)
    write_file_completed = Signal(str, bool, str)
    write_all_completed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.write_calls: list[list[tuple[str, dict]]] = []
        self.stop_write_calls = 0
        self.progress = (0, 0)

    def write_exif(self, items: list[tuple[str, dict]]) -> None:
        self.write_calls.append(list(items))

    def stop_write(self) -> None:
        self.stop_write_calls += 1

    def get_write_progress(self) -> tuple[int, int]:
        return self.progress


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_save_exif_confirm_label_gets_enough_height_for_wrapped_text(qapp):
    items = [
        ImageItem(path=f"/tmp/{index}.jpg", name=f"{index}.jpg", created="2025-01-01")
        for index in range(1238)
    ]
    dialog = SaveExifDialog(items, _FakeMediaManager())

    dialog.show()
    qapp.processEvents()

    required_height = dialog.confirm_label.sizeHint().height()
    if dialog.confirm_label.hasHeightForWidth():
        required_height = dialog.confirm_label.heightForWidth(
            dialog.confirm_label.width()
        )

    assert dialog.confirm_label.height() >= required_height
    assert dialog.height() < 260


def test_save_exif_confirm_buttons_are_cancel_then_launch(qapp):
    items = [ImageItem(path="/tmp/a.jpg", name="a.jpg", created="2025-01-01")]
    dialog = SaveExifDialog(items, _FakeMediaManager())

    dialog.show()
    qapp.processEvents()

    assert dialog.button("cancel").x() < dialog.button("launch").x()


@pytest.mark.parametrize("cancelled", [False, True])
def test_save_exif_result_uses_shared_summary_and_hides_progress(qapp, cancelled):
    manager = _FakeMediaManager()
    manager.progress = (2, 3)
    dialog = SaveExifDialog([], manager)
    dialog._finish(cancelled=cancelled)

    assert isinstance(dialog.summary_text, SummaryTextEdit)
    expected = (
        "Operation stopped. 2 of 3 files processed."
        if cancelled
        else "Complete. 2 files processed."
    )
    assert dialog.summary_text.toPlainText() == expected
    assert dialog.progress_row.isHidden()
    assert dialog.progress_bar.isHidden()
    assert dialog.error_text.isHidden()
    assert dialog.button("ok").isEnabled()


def test_save_exif_error_result_preserves_multiline_details(qapp):
    manager = _FakeMediaManager()
    manager.progress = (1, 1)
    dialog = SaveExifDialog([], manager)
    dialog.transition_to("writing")
    dialog._on_file_completed(
        "/tmp/<a>.jpg", False, "First failure\nMore details & text"
    )
    dialog._finish(cancelled=False)

    assert isinstance(dialog.error_text, SummaryTextEdit)
    assert (
        dialog.summary_text.toPlainText()
        == "Complete. 1 files processed, 1 with errors."
    )
    assert dialog.error_text.toPlainText() == (
        "1 file(s) with errors\n<a>.jpg: First failure\nMore details & text"
    )
    assert dialog.error_text.document().find(
        "1 file(s)"
    ).charFormat().foreground().color() == QColor("red")
