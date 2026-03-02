"""Tests for shortcuts editor widget."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QFormLayout, QGridLayout, QGroupBox
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


def _section_group(editor: ShortcutsEditor, title: str) -> QGroupBox:
    groups = editor.findChildren(QGroupBox)
    for group in groups:
        if group.title() == title:
            return group
    raise AssertionError(f"Missing group '{title}'")


def _section_labels(group: QGroupBox) -> list[str]:
    layout = group.layout()
    assert isinstance(layout, QFormLayout)
    labels: list[str] = []
    for row in range(layout.rowCount()):
        label_item = layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
        assert label_item is not None
        labels.append(label_item.widget().text())
    return labels


def test_shortcuts_editor_uses_sectioned_two_column_layout(qapp):
    editor = ShortcutsEditor()
    layout = editor.layout()
    assert isinstance(layout, QGridLayout)

    groups = editor.findChildren(QGroupBox)
    assert {group.title() for group in groups} == {
        "Set Labels",
        "Filter Shortcuts",
        "Grid Shortcuts",
        "Fullscreen Shortcuts",
    }

    set_labels = _section_labels(_section_group(editor, "Set Labels"))
    filter_shortcuts = _section_labels(_section_group(editor, "Filter Shortcuts"))
    grid_shortcuts = _section_labels(_section_group(editor, "Grid Shortcuts"))
    fullscreen_shortcuts = _section_labels(
        _section_group(editor, "Fullscreen Shortcuts")
    )

    assert set_labels == [
        Shortcut.LABEL_1.label,
        Shortcut.LABEL_2.label,
        Shortcut.LABEL_3.label,
        Shortcut.LABEL_4.label,
        Shortcut.LABEL_5.label,
        Shortcut.LABEL_6.label,
        Shortcut.LABEL_7.label,
        Shortcut.LABEL_8.label,
        Shortcut.LABEL_9.label,
        Shortcut.LABEL_NONE.label,
    ]
    assert filter_shortcuts == [
        Shortcut.FILTER_LABEL_1.label,
        Shortcut.FILTER_LABEL_2.label,
        Shortcut.FILTER_LABEL_3.label,
        Shortcut.FILTER_LABEL_4.label,
        Shortcut.FILTER_LABEL_5.label,
        Shortcut.FILTER_LABEL_6.label,
        Shortcut.FILTER_LABEL_7.label,
        Shortcut.FILTER_LABEL_8.label,
        Shortcut.FILTER_LABEL_9.label,
        Shortcut.FILTER_LABEL_NONE.label,
        Shortcut.FILTER_FOLDER_ALL.label,
        Shortcut.FILTER_FOLDER_NEXT.label,
        Shortcut.FILTER_FOLDER_PREV.label,
        Shortcut.FILTER_CLEAR_ALL.label,
        Shortcut.FILTER_FOCUS_SEARCH.label,
    ]
    assert grid_shortcuts == [
        Shortcut.SELECT_ALL.label,
        Shortcut.COLLAPSE_TO_LAST_SELECTED.label,
    ]
    assert fullscreen_shortcuts == [
        Shortcut.ZOOM_IN.label,
        Shortcut.ZOOM_OUT.label,
        Shortcut.ZOOM_RESET.label,
    ]


def test_shortcuts_editor_accepts_enum_and_string_keys(qapp):
    editor = ShortcutsEditor()
    editor.set_value(
        {
            Shortcut.ZOOM_IN: "=",
            Shortcut.ZOOM_OUT.name: "-",
            Shortcut.SELECT_ALL.value: "ctrl+a",
            Shortcut.FILTER_LABEL_1.value: "Alt+1",
        }
    )

    value = editor.get_value()
    assert value[Shortcut.ZOOM_IN] == "="
    assert value[Shortcut.ZOOM_OUT] == "-"
    assert value[Shortcut.SELECT_ALL] == "ctrl+a"
    assert value[Shortcut.FILTER_LABEL_1] == "Alt+1"
    assert set(editor._inputs.keys()) == set(Shortcut)
