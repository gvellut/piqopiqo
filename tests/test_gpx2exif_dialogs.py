"""Tests for GPX dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QFileDialog
import pytest

from piqopiqo.ssf.settings_state import init_qsettings_store
from piqopiqo.tools.gpx2exif.dialogs import (
    ApplyGpxDialog,
    ApplyGpxProgressDialog,
    ExtractGpsTimeShiftProgressDialog,
)
from piqopiqo.tools.gpx2exif.service import ApplyGpxResult, ApplyGpxUnmatchedPhoto


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


def test_apply_gpx_dialog_is_compact_after_show(qapp, tmp_path):
    folder_a = "/root/photos/folder-a"
    folder_b = "/root/photos/folder-b"
    gpx_path = tmp_path / "track.gpx"
    gpx_path.write_text("<gpx></gpx>", encoding="utf-8")

    dialog = ApplyGpxDialog(
        root_folder="/root/photos",
        source_folders=[folder_a, folder_b],
        initial_time_shifts={folder_a: "1s", folder_b: "-2s"},
        previous_time_shift_folders=set(),
        initial_gpx_path=str(gpx_path),
        kml_folder="",
    )

    dialog.show()
    qapp.processEvents()

    assert dialog.height() < 360
    assert dialog.minimumHeight() == dialog.maximumHeight() == dialog.height()


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
    init_qsettings_store(dyn=True)
    dialog = ExtractGpsTimeShiftProgressDialog()
    dialog.show()
    qapp.processEvents()

    dialog._on_success("12:34:56", "-1m4s")
    qapp.processEvents()

    assert dialog.result_shift == "-1m4s"
    assert dialog.result_label.isHidden() is False
    assert dialog.result_label.text() == (
        "Extracted clock: 12:34:56\nComputed time shift: -1m4s"
    )
    assert dialog.progress_row.isHidden() is True
    assert dialog.progress_bar.isHidden() is True
    assert dialog.result_label.geometry().x() == 0


def test_extract_time_shift_progress_running_screen_has_no_body_gap(qapp):
    init_qsettings_store(dyn=True)
    dialog = ExtractGpsTimeShiftProgressDialog()
    dialog.show()
    qapp.processEvents()

    assert dialog._content_host.isHidden() is True
    assert dialog.progress_bar.isHidden() is False


def test_extract_time_shift_progress_uses_apple_status_text_by_default(
    qapp, monkeypatch
):
    monkeypatch.delenv("PIQO_OCR_TIME_SHIFT_PROVIDER", raising=False)
    init_qsettings_store(dyn=True)

    dialog = ExtractGpsTimeShiftProgressDialog()

    assert (
        dialog.status_label.text()
        == "Extracting clock time with Apple Vision..."
    )


def test_extract_time_shift_progress_uses_apple_status_text_when_selected(
    qapp, monkeypatch
):
    monkeypatch.setenv("PIQO_OCR_TIME_SHIFT_PROVIDER", "APPLE_VISION")
    init_qsettings_store(dyn=True)

    dialog = ExtractGpsTimeShiftProgressDialog()

    assert dialog.status_label.text() == "Extracting clock time with Apple Vision..."


def test_apply_gpx_progress_folder_label_hidden_until_first_folder(qapp):
    dialog = ApplyGpxProgressDialog(total=2)

    assert dialog.folder_label.isHidden() is True

    dialog.set_folder("a/b")
    assert dialog.folder_label.isHidden() is False
    assert dialog.folder_label.text() == "Folder: a/b"


def test_apply_gpx_progress_dialog_initially_compact_and_expands_on_details(qapp):
    dialog = ApplyGpxProgressDialog(total=1)
    dialog.show()
    qapp.processEvents()

    initial_height = dialog.height()
    assert initial_height < 300
    assert dialog.minimumHeight() == dialog.maximumHeight() == initial_height

    dialog.finish(
        ApplyGpxResult(
            processed=1,
            kml_paths=["/tmp/out.kml"],
            errors=["Some folder failed"],
        )
    )
    qapp.processEvents()

    final_height = dialog.height()
    assert dialog.minimumHeight() == dialog.maximumHeight() == final_height
    assert final_height > initial_height
    assert dialog.progress_bar.isHidden() is True
    assert dialog.status_label.text() == (
        "Processed 1 photo(s).\nGeoreferenced: 0 / 1"
    )


def test_apply_gpx_progress_no_match_shows_compact_warning_only(qapp):
    dialog = ApplyGpxProgressDialog(total=1)
    dialog.set_folder("a/b")
    dialog.show()
    qapp.processEvents()

    dialog.finish(ApplyGpxResult(processed=1, matched=0))
    qapp.processEvents()

    assert dialog.no_match_warning_row.isHidden() is False
    assert (
        dialog.no_match_warning_label.text()
        == "The GPX did not match any image"
    )
    assert dialog.no_match_warning_icon.pixmap().isNull() is False
    assert dialog.details_text.isHidden() is True
    assert dialog.folder_label.isHidden() is True
    assert dialog.progress_row.isHidden() is True
    assert dialog.progress_bar.isHidden() is True
    assert dialog.show_finder_btn.isHidden() is True
    assert dialog.height() < 240
    assert dialog.minimumHeight() == dialog.maximumHeight() == dialog.height()


def test_apply_gpx_progress_mixed_result_shows_kml_then_red_unmatched(qapp):
    dialog = ApplyGpxProgressDialog(total=24)
    dialog.show()
    qapp.processEvents()

    unmatched = [
        ApplyGpxUnmatchedPhoto(
            path=f"/tmp/photo-{index}.jpg",
            name=f"photo-{index}.jpg",
            datetime_display=f"2026-01-01 09:{index:02d}:00",
        )
        for index in range(24)
    ]
    dialog.finish(
        ApplyGpxResult(
            processed=25,
            matched=1,
            kml_paths=["/tmp/out.kml"],
            unmatched_photos=unmatched,
        )
    )
    qapp.processEvents()

    plain_text = dialog.details_text.toPlainText()
    assert plain_text.startswith("KML output:\n/tmp/out.kml")
    assert (
        "Images without georeferencing:\n"
        "photo-0.jpg - 2026-01-01 09:00:00"
    ) in plain_text
    assert "#b00020" in dialog.details_text.toHtml().lower()
    assert dialog.details_text.height() == 140
    assert dialog.details_text.verticalScrollBar().maximum() > 0
    assert dialog.no_match_warning_row.isHidden() is True
    assert dialog.progress_bar.isHidden() is True
    assert dialog.status_label.text() == (
        "Processed 25 photo(s).\nGeoreferenced: 1 / 24"
    )
