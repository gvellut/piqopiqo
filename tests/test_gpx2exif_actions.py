"""Tests for GPX action helpers."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from PySide6.QtWidgets import QDialog, QMessageBox

from piqopiqo.cache_paths import set_cache_base_dir
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDBManager
from piqopiqo.ssf.settings_state import StateKey
import piqopiqo.tools.gpx2exif.actions as gpx_actions
from piqopiqo.tools.gpx2exif.actions import (
    _get_first_folder_gpx_path,
    _set_gpx_path_for_folders,
    launch_clear_gps,
)
from piqopiqo.tools.gpx2exif.constants import FOLDER_STATE_LAST_GPX_PATH
import piqopiqo.tools.gpx2exif.dialogs as gpx_dialogs
import piqopiqo.tools.gpx2exif.workers as gpx_workers


def test_set_gpx_path_for_folders_writes_trimmed_value(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")

    folder_a = tmp_path / "photos" / "a"
    folder_b = tmp_path / "photos" / "b"
    folder_a.mkdir(parents=True, exist_ok=True)
    folder_b.mkdir(parents=True, exist_ok=True)
    source_folders = [str(folder_a), str(folder_b)]

    dbm = MetadataDBManager()
    window = SimpleNamespace(db_manager=dbm)

    _set_gpx_path_for_folders(window, source_folders, "  /tmp/track.gpx  ")

    assert (
        dbm.get_db_for_folder(str(folder_a)).get_folder_value(
            FOLDER_STATE_LAST_GPX_PATH
        )
        == "/tmp/track.gpx"
    )
    assert (
        dbm.get_db_for_folder(str(folder_b)).get_folder_value(
            FOLDER_STATE_LAST_GPX_PATH
        )
        == "/tmp/track.gpx"
    )

    dbm.close_all()


def test_set_gpx_path_for_folders_empty_clears_value(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")

    folder = tmp_path / "photos" / "a"
    folder.mkdir(parents=True, exist_ok=True)
    source_folders = [str(folder)]

    dbm = MetadataDBManager()
    dbm.get_db_for_folder(str(folder)).set_folder_value(
        FOLDER_STATE_LAST_GPX_PATH, "/tmp/old.gpx"
    )
    window = SimpleNamespace(db_manager=dbm)

    _set_gpx_path_for_folders(window, source_folders, "   ")

    assert (
        dbm.get_db_for_folder(str(folder)).get_folder_value(FOLDER_STATE_LAST_GPX_PATH)
        is None
    )

    dbm.close_all()


def test_get_first_folder_gpx_path_returns_first_non_empty_value(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")

    folder_a = tmp_path / "photos" / "a"
    folder_b = tmp_path / "photos" / "b"
    folder_c = tmp_path / "photos" / "c"
    for folder in (folder_a, folder_b, folder_c):
        folder.mkdir(parents=True, exist_ok=True)

    source_folders = [str(folder_a), str(folder_b), str(folder_c)]
    dbm = MetadataDBManager()
    dbm.get_db_for_folder(str(folder_a)).set_folder_value(
        FOLDER_STATE_LAST_GPX_PATH, " "
    )
    dbm.get_db_for_folder(str(folder_b)).set_folder_value(
        FOLDER_STATE_LAST_GPX_PATH, " /tmp/first.gpx "
    )
    dbm.get_db_for_folder(str(folder_c)).set_folder_value(
        FOLDER_STATE_LAST_GPX_PATH, "/tmp/second.gpx"
    )
    window = SimpleNamespace(db_manager=dbm)

    assert _get_first_folder_gpx_path(window, source_folders) == "/tmp/first.gpx"

    dbm.close_all()


def test_launch_apply_gpx_passes_last_folder_and_persists_browse_selection(
    monkeypatch,
) -> None:
    state_values = {StateKey.LAST_GPX_FOLDER: " /tmp/last-gpx-folder "}
    state_set_calls: list[tuple[StateKey, str]] = []

    class _StateStub:
        def get(self, key: StateKey):
            return state_values.get(key)

        def set(self, key: StateKey, value: object) -> None:
            state_set_calls.append((key, str(value)))

    captured_last_folder: list[str] = []

    class _DialogStub:
        def __init__(self, *args, **kwargs):
            captured_last_folder.append(kwargs["last_gpx_folder"])
            kwargs["on_browse_selected_folder"]("/tmp/chosen")

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(gpx_actions, "get_state", lambda: _StateStub())
    monkeypatch.setattr(gpx_actions, "get_user_setting", lambda _key: "")
    monkeypatch.setattr(gpx_actions, "_get_first_folder_gpx_path", lambda *_: "")
    monkeypatch.setattr(
        gpx_actions,
        "_resolve_apply_gpx_initial_time_shifts",
        lambda *_: ({}, set()),
    )
    monkeypatch.setattr(gpx_dialogs, "ApplyGpxDialog", _DialogStub)

    window = SimpleNamespace(
        root_folder="/root/photos",
        photo_model=SimpleNamespace(source_folders=["/root/photos/a"]),
        _active_apply_gpx_worker=None,
    )

    gpx_actions.launch_apply_gpx(window)

    assert captured_last_folder == ["/tmp/last-gpx-folder"]
    assert state_set_calls == [(StateKey.LAST_GPX_FOLDER, "/tmp/chosen")]


def test_launch_clear_gpx_clears_lat_lon_restores_time_and_syncs_model(
    monkeypatch,
    tmp_path,
) -> None:
    set_cache_base_dir(tmp_path / "cache")

    photos_root = tmp_path / "photos"
    folder = photos_root / "a"
    folder.mkdir(parents=True, exist_ok=True)

    file_a = str(folder / "a.jpg")
    file_b = str(folder / "b.jpg")

    dbm = MetadataDBManager()
    db = dbm.get_db_for_folder(str(folder))

    metadata_a = {
        DBFields.TITLE: "A",
        DBFields.LATITUDE: 48.1,
        DBFields.LONGITUDE: 2.3,
        DBFields.TIME_TAKEN: datetime(2026, 2, 1, 12, 0, 0),
    }
    metadata_b = {
        DBFields.TITLE: "B",
        DBFields.LATITUDE: 49.1,
        DBFields.LONGITUDE: 3.3,
        DBFields.TIME_TAKEN: datetime(2026, 2, 2, 12, 0, 0),
    }
    db.save_metadata(file_a, metadata_a)
    db.save_metadata(file_b, metadata_b)
    db.save_exif_fields(
        file_a,
        {"EXIF:DateTimeOriginal": "2026:02:01 10:30:00"},
    )
    db.save_exif_fields(
        file_b,
        {"EXIF:DateTimeOriginal": "2026:02:02 10:30:00"},
    )

    sync_calls: list[tuple[set[str], str]] = []

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(gpx_actions, "get_user_setting", lambda _key: "")

    item_a = SimpleNamespace(path=file_a, db_metadata=metadata_a.copy())
    item_b = SimpleNamespace(path=file_b, db_metadata=None)
    window = SimpleNamespace(
        root_folder=str(photos_root),
        photo_model=SimpleNamespace(
            source_folders=[str(folder)],
            all_photos=[item_a, item_b],
        ),
        _active_apply_gpx_worker=None,
        db_manager=dbm,
        sync_model_after_metadata_update=lambda fields, source: sync_calls.append((
            set(fields),
            source,
        )),
    )

    launch_clear_gps(window)

    meta_a = db.get_metadata(file_a)
    meta_b = db.get_metadata(file_b)
    assert meta_a is not None
    assert meta_b is not None

    assert meta_a[DBFields.LATITUDE] is None
    assert meta_a[DBFields.LONGITUDE] is None
    assert meta_b[DBFields.LATITUDE] is None
    assert meta_b[DBFields.LONGITUDE] is None

    assert meta_a[DBFields.TIME_TAKEN] == datetime(2026, 2, 1, 10, 30, 0)
    assert meta_b[DBFields.TIME_TAKEN] == datetime(2026, 2, 2, 10, 30, 0)

    assert item_a.db_metadata[DBFields.LATITUDE] is None
    assert item_a.db_metadata[DBFields.LONGITUDE] is None
    assert item_a.db_metadata[DBFields.TIME_TAKEN] == datetime(2026, 2, 1, 10, 30, 0)
    assert item_b.db_metadata is not None
    assert item_b.db_metadata[DBFields.LATITUDE] is None
    assert item_b.db_metadata[DBFields.LONGITUDE] is None
    assert item_b.db_metadata[DBFields.TIME_TAKEN] == datetime(2026, 2, 2, 10, 30, 0)

    assert sync_calls == [
        ({DBFields.TIME_TAKEN, DBFields.LATITUDE, DBFields.LONGITUDE}, "clear_gpx"),
    ]

    dbm.close_all()


def test_clear_gps_worker_clears_lat_lon_and_restores_exif_time(
    monkeypatch,
    tmp_path,
) -> None:
    set_cache_base_dir(tmp_path / "cache")

    folder = tmp_path / "photos"
    folder.mkdir(parents=True, exist_ok=True)
    file_a = str(folder / "a.jpg")
    file_b = str(folder / "b.jpg")

    dbm = MetadataDBManager()
    db = dbm.get_db_for_folder(str(folder))
    shifted_time = datetime(2026, 2, 1, 12, 0, 0)
    original_time_a = datetime(2026, 2, 1, 10, 30, 0)
    original_time_b = datetime(2026, 2, 2, 10, 30, 0)
    for file_path in (file_a, file_b):
        db.save_metadata(
            file_path,
            {
                DBFields.TITLE: "A",
                DBFields.LATITUDE: 48.1,
                DBFields.LONGITUDE: 2.3,
                DBFields.TIME_TAKEN: shifted_time,
            },
        )

    exif_calls: list[list[str]] = []

    def _read_original_time_taken_from_exif(
        file_paths: list[str],
        _exiftool_path: str | None,
    ) -> dict[str, datetime | None]:
        exif_calls.append(list(file_paths))
        return {
            file_a: original_time_a,
            file_b: original_time_b,
        }

    monkeypatch.setattr(
        gpx_workers,
        "_read_original_time_taken_from_exif",
        _read_original_time_taken_from_exif,
    )

    worker = gpx_workers.ClearGpsWorker(
        db_manager=dbm,
        file_paths=[file_a, file_b],
        exiftool_path=None,
    )
    worker.run()

    meta_a = db.get_metadata(file_a)
    meta_b = db.get_metadata(file_b)
    assert meta_a is not None
    assert meta_b is not None
    assert meta_a[DBFields.LATITUDE] is None
    assert meta_a[DBFields.LONGITUDE] is None
    assert meta_a[DBFields.TIME_TAKEN] == original_time_a
    assert meta_b[DBFields.LATITUDE] is None
    assert meta_b[DBFields.LONGITUDE] is None
    assert meta_b[DBFields.TIME_TAKEN] == original_time_b
    assert exif_calls == [[file_a, file_b]]

    dbm.close_all()
