"""Tests for shared unsaved-dialog dismissal confirmation."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)
import pytest

from piqopiqo.dialogs.unsaved_changes_dialog import UnsavedChangesDialog
from piqopiqo.ssf.settings_state import init_qsettings_store
from piqopiqo.tools.tool_flow import ToolFlowDialog, ToolScreen, ToolWorkflow


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.delenv("PIQO_DIALOG_DISCARD_CONFIRMATION_MODE", raising=False)
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    init_qsettings_store(dyn=True)
    return app


class _EditableDialog(UnsavedChangesDialog):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.line_edit = QLineEdit("original", self)
        self.checkbox = QCheckBox(self)
        self.combo = QComboBox(self)
        self.combo.addItems(["First", "Second"])
        layout.addWidget(self.line_edit)
        layout.addWidget(self.checkbox)
        layout.addWidget(self.combo)
        self.items = ["one"]
        self._set_unsaved_changes_state(
            lambda: (
                self.line_edit.text(),
                self.checkbox.isChecked(),
                self.combo.currentIndex(),
                tuple(self.items),
            )
        )


def _escape_event() -> QKeyEvent:
    return QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Escape,
        Qt.KeyboardModifier.NoModifier,
    )


def test_unchanged_and_reverted_input_closes_without_confirmation(
    qapp,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: pytest.fail("unexpected confirmation"),
    )
    dialog = _EditableDialog()
    dialog.line_edit.setText("changed")
    dialog.line_edit.setText("original")
    dialog.show()
    qapp.processEvents()

    dialog.keyPressEvent(_escape_event())

    assert dialog.isHidden() is True


def test_escape_keeps_dirty_dialog_open_when_discard_is_declined(
    qapp,
    monkeypatch,
) -> None:
    calls: list[str] = []

    def decline(*_args, **_kwargs):
        calls.append("question")
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", decline)
    dialog = _EditableDialog()
    dialog.line_edit.setText("changed")
    dialog.show()
    qapp.processEvents()

    dialog.keyPressEvent(_escape_event())

    assert calls == ["question"]
    assert dialog.isVisible() is True


def test_escape_rejects_dirty_dialog_after_single_confirmation(
    qapp,
    monkeypatch,
) -> None:
    calls: list[str] = []

    def confirm(*_args, **_kwargs):
        calls.append("question")
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    dialog = _EditableDialog()
    dialog.checkbox.setChecked(True)
    dialog.show()
    qapp.processEvents()

    dialog.keyPressEvent(_escape_event())

    assert calls == ["question"]
    assert dialog.isHidden() is True


def test_every_editable_state_and_disabled_invalid_text_is_tracked(qapp) -> None:
    dialog = _EditableDialog()

    dialog.line_edit.setEnabled(False)
    dialog.line_edit.setText("")
    assert dialog._has_unsaved_changes() is True
    dialog.line_edit.setText("original")
    assert dialog._has_unsaved_changes() is False

    dialog.checkbox.setChecked(True)
    assert dialog._has_unsaved_changes() is True
    dialog.checkbox.setChecked(False)
    assert dialog._has_unsaved_changes() is False

    dialog.combo.setCurrentIndex(1)
    assert dialog._has_unsaved_changes() is True
    dialog.combo.setCurrentIndex(0)
    assert dialog._has_unsaved_changes() is False

    dialog.items.append("two")
    assert dialog._has_unsaved_changes() is True
    dialog.items.pop()
    assert dialog._has_unsaved_changes() is False


def test_default_mode_does_not_guard_non_escape_rejection(qapp, monkeypatch) -> None:
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: pytest.fail("unexpected confirmation"),
    )
    dialog = _EditableDialog()
    dialog.line_edit.setText("changed")
    dialog.show()
    qapp.processEvents()

    dialog.reject()

    assert dialog.isHidden() is True


def test_every_dismissal_mode_guards_reject_and_window_close_once(
    qapp,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "PIQO_DIALOG_DISCARD_CONFIRMATION_MODE",
        "EVERY_DISMISSAL",
    )
    init_qsettings_store(dyn=True)
    calls: list[str] = []

    def decline(*_args, **_kwargs):
        calls.append("question")
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", decline)
    dialog = _EditableDialog()
    dialog.line_edit.setText("changed")
    dialog.show()
    qapp.processEvents()

    dialog.reject()
    assert calls == ["question"]
    assert dialog.isVisible() is True

    dialog.close()
    assert calls == ["question", "question"]
    assert dialog.isVisible() is True

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: (
            calls.append("question") or QMessageBox.StandardButton.Yes
        ),
    )
    dialog.close()
    assert calls == ["question", "question", "question"]
    assert dialog.isHidden() is True


def test_tool_flow_dirty_state_only_applies_to_captured_screen(
    qapp,
    monkeypatch,
) -> None:
    edit = QLineEdit()
    workflow = ToolWorkflow(
        initial_screen="input",
        screens={
            "input": ToolScreen(id="input", build=lambda _dialog: edit),
            "progress": ToolScreen(id="progress", show_progress=True),
        },
    )
    dialog = ToolFlowDialog(workflow)
    dialog._set_unsaved_changes_state(lambda: edit.text())
    edit.setText("changed")
    assert dialog._has_unsaved_changes() is True

    dialog.transition_to("progress")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: pytest.fail("unexpected confirmation"),
    )
    dialog.show()
    qapp.processEvents()

    dialog.keyPressEvent(_escape_event())

    assert dialog.isHidden() is True
