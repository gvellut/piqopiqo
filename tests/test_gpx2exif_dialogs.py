"""Tests for GPX dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.tools.gpx2exif.dialogs import ApplyGpxDialog


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_apply_gpx_dialog_requires_valid_time_shifts_and_file(qapp, tmp_path):
    folder = "/root/photos/folder-a"
    dialog = ApplyGpxDialog(
        root_folder="/root/photos",
        source_folders=[folder],
        initial_time_shifts={folder: "invalid"},
        previous_time_shift_folders=set(),
        kml_folder="",
    )

    gpx_path = tmp_path / "track.gpx"
    gpx_path.write_text("<gpx></gpx>", encoding="utf-8")
    dialog.gpx_path_edit.setText(str(gpx_path))

    assert dialog._ok_btn.isEnabled() is False

    dialog._time_shift_edits[folder].setText("1m2s")
    assert dialog._ok_btn.isEnabled() is True


def test_apply_gpx_dialog_returns_folder_shift_values(qapp, tmp_path):
    folder_a = "/root/photos/folder-a"
    folder_b = "/root/photos/folder-b"
    dialog = ApplyGpxDialog(
        root_folder="/root/photos",
        source_folders=[folder_a, folder_b],
        initial_time_shifts={folder_a: "1s", folder_b: ""},
        previous_time_shift_folders=set(),
        kml_folder="",
    )

    gpx_path = tmp_path / "track.gpx"
    gpx_path.write_text("<gpx></gpx>", encoding="utf-8")
    dialog.gpx_path_edit.setText(str(gpx_path))

    path, _mode, shifts = dialog.get_values()
    assert path == str(gpx_path)
    assert shifts == {
        folder_a: "1s",
        folder_b: "",
    }


def test_apply_gpx_dialog_previous_label_only_for_state_sourced_values(qapp):
    folder_a = "/root/photos/folder-a"
    folder_b = "/root/photos/folder-b"
    folder_c = "/root/photos/folder-c"
    dialog = ApplyGpxDialog(
        root_folder="/root/photos",
        source_folders=[folder_a, folder_b, folder_c],
        initial_time_shifts={
            folder_a: "1s",
            folder_b: "2s",
            folder_c: "",
        },
        previous_time_shift_folders={folder_a, folder_c},
        kml_folder="",
    )

    assert dialog._previous_labels[folder_a].isHidden() is False
    assert dialog._previous_labels[folder_b].isHidden() is True
    assert dialog._previous_labels[folder_c].isHidden() is True
