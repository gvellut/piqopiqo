"""Tests for GPX dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QFileDialog
import pytest

from piqopiqo.tools.gpx2exif.dialogs import (
    ApplyGpxDialog,
    ExtractGpsTimeShiftProgressDialog,
)


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
        initial_gpx_path="",
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
        initial_gpx_path="",
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
        initial_gpx_path="",
        kml_folder="",
    )

    assert dialog._previous_labels[folder_a].isHidden() is False
    assert dialog._previous_labels[folder_b].isHidden() is True
    assert dialog._previous_labels[folder_c].isHidden() is True


def test_apply_gpx_dialog_prefills_initial_gpx_path(qapp, tmp_path):
    folder = "/root/photos/folder-a"
    gpx_path = tmp_path / "track.gpx"
    gpx_path.write_text("<gpx></gpx>", encoding="utf-8")
    dialog = ApplyGpxDialog(
        root_folder="/root/photos",
        source_folders=[folder],
        initial_time_shifts={folder: ""},
        previous_time_shift_folders=set(),
        initial_gpx_path=f"  {gpx_path}  ",
        kml_folder="",
    )

    path, _mode, _shifts = dialog.get_values()
    assert path == str(gpx_path)


def test_apply_gpx_dialog_browse_uses_last_folder_when_field_empty(
    qapp, tmp_path, monkeypatch
):
    folder = "/root/photos/folder-a"
    last_folder = tmp_path / "last"
    last_folder.mkdir(parents=True, exist_ok=True)

    start_dirs: list[str] = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda _parent, _title, start_dir, _filter: (
            start_dirs.append(start_dir) or ("", "")
        ),
    )

    dialog = ApplyGpxDialog(
        root_folder="/root/photos",
        source_folders=[folder],
        initial_time_shifts={folder: ""},
        previous_time_shift_folders=set(),
        initial_gpx_path="",
        kml_folder="",
        last_gpx_folder=str(last_folder),
    )
    dialog._browse_gpx()

    assert start_dirs == [str(last_folder)]


def test_apply_gpx_dialog_browse_uses_field_folder_when_field_not_empty(
    qapp, tmp_path, monkeypatch
):
    folder = "/root/photos/folder-a"
    start_dirs: list[str] = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda _parent, _title, start_dir, _filter: (
            start_dirs.append(start_dir) or ("", "")
        ),
    )

    gpx_path = tmp_path / "manual.gpx"
    dialog = ApplyGpxDialog(
        root_folder="/root/photos",
        source_folders=[folder],
        initial_time_shifts={folder: ""},
        previous_time_shift_folders=set(),
        initial_gpx_path="",
        kml_folder="",
        last_gpx_folder="/should/not/be/used",
    )
    dialog.gpx_path_edit.setText(str(gpx_path))
    dialog._browse_gpx()

    assert start_dirs == [str(tmp_path)]


def test_apply_gpx_dialog_browse_uses_system_default_when_no_last_folder(
    qapp, monkeypatch
):
    folder = "/root/photos/folder-a"
    start_dirs: list[str] = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda _parent, _title, start_dir, _filter: (
            start_dirs.append(start_dir) or ("", "")
        ),
    )

    dialog = ApplyGpxDialog(
        root_folder="/root/photos",
        source_folders=[folder],
        initial_time_shifts={folder: ""},
        previous_time_shift_folders=set(),
        initial_gpx_path="",
        kml_folder="",
        last_gpx_folder="",
    )
    dialog._browse_gpx()

    assert start_dirs == [""]


def test_apply_gpx_dialog_browse_cancel_keeps_field_and_does_not_call_callback(
    qapp, tmp_path, monkeypatch
):
    folder = "/root/photos/folder-a"
    initial_gpx_path = tmp_path / "current.gpx"
    initial_gpx_path.write_text("<gpx></gpx>", encoding="utf-8")

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda _parent, _title, _start_dir, _filter: ("", ""),
    )
    callback_values: list[str] = []
    dialog = ApplyGpxDialog(
        root_folder="/root/photos",
        source_folders=[folder],
        initial_time_shifts={folder: ""},
        previous_time_shift_folders=set(),
        initial_gpx_path=str(initial_gpx_path),
        kml_folder="",
        on_browse_selected_folder=callback_values.append,
    )

    dialog._browse_gpx()

    assert dialog.gpx_path_edit.text() == str(initial_gpx_path)
    assert callback_values == []


def test_apply_gpx_dialog_browse_accept_updates_field_and_calls_callback(
    qapp, tmp_path, monkeypatch
):
    folder = "/root/photos/folder-a"
    selected_file = tmp_path / "picked" / "track.gpx"
    selected_file.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda _parent, _title, _start_dir, _filter: (str(selected_file), ""),
    )
    callback_values: list[str] = []
    dialog = ApplyGpxDialog(
        root_folder="/root/photos",
        source_folders=[folder],
        initial_time_shifts={folder: ""},
        previous_time_shift_folders=set(),
        initial_gpx_path="",
        kml_folder="",
        on_browse_selected_folder=callback_values.append,
    )

    dialog._browse_gpx()

    assert dialog.gpx_path_edit.text() == str(selected_file)
    assert callback_values == [str(selected_file.parent)]


def test_extract_time_shift_progress_success_shows_clock_and_shift_lines(qapp):
    dialog = ExtractGpsTimeShiftProgressDialog()

    dialog._on_success("12:34:56", "-1m4s")

    assert dialog.status_label.text() == "Extraction done."
    assert dialog.result_shift == "-1m4s"
    assert dialog.result_label.isHidden() is False
    assert dialog.result_label.text() == (
        "Extracted clock: 12:34:56\nComputed time shift: -1m4s"
    )
    assert dialog.progress_bar.minimum() == 0
    assert dialog.progress_bar.maximum() == 1
    assert dialog.progress_bar.value() == 1
