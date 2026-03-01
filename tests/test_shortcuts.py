"""Tests for shortcut enum metadata."""

from piqopiqo.model import StatusLabel
from piqopiqo.shortcuts import (
    FULLSCREEN_VIEW_CONFIGURABLE_SHORTCUTS,
    FULLSCREEN_VIEW_HARDCODED_SHORTCUTS,
    GRID_VIEW_CONFIGURABLE_SHORTCUTS,
    GRID_VIEW_HARDCODED_SHORTCUTS,
    LABEL_SHORTCUTS,
    Shortcut,
    build_label_shortcut_bindings,
)


def test_shortcut_values_stay_uppercase_constants():
    for shortcut in Shortcut:
        assert shortcut.value == shortcut.name


def test_shortcut_labels_are_human_readable():
    assert Shortcut.ZOOM_IN.label == "Zoom in"
    assert Shortcut.ZOOM_OUT.label == "Zoom out"
    assert Shortcut.ZOOM_RESET.label == "Zoom reset"
    assert Shortcut.LABEL_1.label == "Label 1"
    assert Shortcut.LABEL_NONE.label == "No label"
    assert Shortcut.SELECT_ALL.label == "Select all"
    assert Shortcut.COLLAPSE_TO_LAST_SELECTED.label == "Keep last selected (grid)"


def test_configurable_shortcut_view_registries_cover_all_shortcuts():
    assert Shortcut.SELECT_ALL in GRID_VIEW_CONFIGURABLE_SHORTCUTS
    assert Shortcut.SELECT_ALL not in FULLSCREEN_VIEW_CONFIGURABLE_SHORTCUTS
    assert Shortcut.COLLAPSE_TO_LAST_SELECTED in GRID_VIEW_CONFIGURABLE_SHORTCUTS
    assert Shortcut.COLLAPSE_TO_LAST_SELECTED not in FULLSCREEN_VIEW_CONFIGURABLE_SHORTCUTS

    assert Shortcut.ZOOM_IN in FULLSCREEN_VIEW_CONFIGURABLE_SHORTCUTS
    assert Shortcut.ZOOM_IN not in GRID_VIEW_CONFIGURABLE_SHORTCUTS
    assert Shortcut.ZOOM_OUT in FULLSCREEN_VIEW_CONFIGURABLE_SHORTCUTS
    assert Shortcut.ZOOM_RESET in FULLSCREEN_VIEW_CONFIGURABLE_SHORTCUTS

    for label_shortcut in LABEL_SHORTCUTS:
        assert label_shortcut in GRID_VIEW_CONFIGURABLE_SHORTCUTS
        assert label_shortcut in FULLSCREEN_VIEW_CONFIGURABLE_SHORTCUTS

    union = set(GRID_VIEW_CONFIGURABLE_SHORTCUTS) | set(
        FULLSCREEN_VIEW_CONFIGURABLE_SHORTCUTS
    )
    assert union == set(Shortcut)


def test_hardcoded_shortcut_reference_lists_are_non_empty():
    assert GRID_VIEW_HARDCODED_SHORTCUTS
    assert FULLSCREEN_VIEW_HARDCODED_SHORTCUTS


def test_build_label_shortcut_bindings_resolves_status_labels_and_label_none():
    bindings = build_label_shortcut_bindings(
        {
            Shortcut.LABEL_1: "1",
            Shortcut.LABEL_2.value: "2",
            Shortcut.LABEL_NONE.name: "`",
        },
        [
            StatusLabel(name="Pick", color="#00ff00", index=1),
            StatusLabel(name="Review", color="#ff0000", index=2),
        ],
    )

    assert bindings == [("1", "Pick"), ("2", "Review"), ("`", None)]


def test_build_label_shortcut_bindings_skips_missing_labels_and_empty_shortcuts():
    bindings = build_label_shortcut_bindings(
        {
            Shortcut.LABEL_1: "",
            Shortcut.LABEL_3: "3",
            Shortcut.LABEL_NONE: "   ",
        },
        [
            StatusLabel(name="OnlyLabel1", color="#111111", index=1),
        ],
    )

    assert bindings == []
