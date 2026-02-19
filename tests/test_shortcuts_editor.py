"""Tests for shortcuts editor widget."""

from __future__ import annotations

from typing import cast

from PySide6.QtWidgets import QApplication, QFormLayout
import pytest

from piqopiqo.settings_panel.shortcuts_editor import ShortcutsEditor
from piqopiqo.shortcuts import Shortcut


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_shortcuts_editor_uses_human_labels(qapp):
    editor = ShortcutsEditor()
    layout = cast(QFormLayout, editor.layout())

    labels = []
    for row in range(layout.rowCount()):
        label_item = layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
        assert label_item is not None
        labels.append(label_item.widget().text())

    assert labels == [shortcut.label for shortcut in Shortcut]


def test_shortcuts_editor_accepts_enum_and_string_keys(qapp):
    editor = ShortcutsEditor()
    editor.set_value(
        {
            Shortcut.ZOOM_IN: "=",
            Shortcut.ZOOM_OUT.name: "-",
            Shortcut.SELECT_ALL.value: "ctrl+a",
        }
    )

    value = editor.get_value()
    assert value[Shortcut.ZOOM_IN] == "="
    assert value[Shortcut.ZOOM_OUT] == "-"
    assert value[Shortcut.SELECT_ALL] == "ctrl+a"
