"""Tests for GPX action helpers."""

from __future__ import annotations

from types import SimpleNamespace

from piqopiqo.cache_paths import set_cache_base_dir
from piqopiqo.metadata.metadata_db import MetadataDBManager
from piqopiqo.tools.gpx2exif.actions import (
    _get_first_folder_gpx_path,
    _set_gpx_path_for_folders,
)
from piqopiqo.tools.gpx2exif.constants import FOLDER_STATE_LAST_GPX_PATH


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
