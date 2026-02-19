"""Tests for shortcut enum metadata."""

from piqopiqo.shortcuts import Shortcut


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
