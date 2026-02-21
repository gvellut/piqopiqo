"""Tests for folder-scoped metadata in MetadataDB."""

from __future__ import annotations

from piqopiqo.cache_paths import set_cache_base_dir
from piqopiqo.metadata.metadata_db import MetadataDB
from piqopiqo.tools.flickr_upload.constants import FOLDER_STATE_LAST_FLICKR_ALBUM_ID
from piqopiqo.tools.gpx2exif.constants import (
    FOLDER_STATE_LAST_GPX_PATH,
    FOLDER_STATE_LAST_TIME_SHIFT,
)


def test_folder_metadata_roundtrip(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")

    source_folder = tmp_path / "photos" / "folder_a"
    source_folder.mkdir(parents=True, exist_ok=True)

    db = MetadataDB(str(source_folder))

    assert db.get_folder_value("SOME_KEY") is None

    db.set_folder_value("SOME_KEY", "value")
    assert db.get_folder_value("SOME_KEY") == "value"

    db.set_folder_value("SOME_KEY", None)
    assert db.get_folder_value("SOME_KEY") is None

    db.close()


def test_folder_metadata_time_shift_key_roundtrip(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")

    source_folder = tmp_path / "photos" / "folder_b"
    source_folder.mkdir(parents=True, exist_ok=True)

    db = MetadataDB(str(source_folder))

    assert db.get_folder_value(FOLDER_STATE_LAST_TIME_SHIFT) is None

    db.set_folder_value(FOLDER_STATE_LAST_TIME_SHIFT, "-1h16m5s")
    assert db.get_folder_value(FOLDER_STATE_LAST_TIME_SHIFT) == "-1h16m5s"

    db.set_folder_value(FOLDER_STATE_LAST_TIME_SHIFT, None)
    assert db.get_folder_value(FOLDER_STATE_LAST_TIME_SHIFT) is None

    db.close()


def test_folder_metadata_flickr_album_id_roundtrip(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")

    source_folder = tmp_path / "photos" / "folder_c"
    source_folder.mkdir(parents=True, exist_ok=True)

    db = MetadataDB(str(source_folder))

    assert db.get_folder_value(FOLDER_STATE_LAST_FLICKR_ALBUM_ID) is None

    db.set_folder_value(FOLDER_STATE_LAST_FLICKR_ALBUM_ID, "72177720331888267")
    assert db.get_folder_value(FOLDER_STATE_LAST_FLICKR_ALBUM_ID) == "72177720331888267"

    db.set_folder_value(FOLDER_STATE_LAST_FLICKR_ALBUM_ID, None)
    assert db.get_folder_value(FOLDER_STATE_LAST_FLICKR_ALBUM_ID) is None

    db.close()


def test_folder_metadata_gpx_path_roundtrip(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")

    source_folder = tmp_path / "photos" / "folder_d"
    source_folder.mkdir(parents=True, exist_ok=True)

    db = MetadataDB(str(source_folder))

    assert db.get_folder_value(FOLDER_STATE_LAST_GPX_PATH) is None

    db.set_folder_value(FOLDER_STATE_LAST_GPX_PATH, "/tmp/track.gpx")
    assert db.get_folder_value(FOLDER_STATE_LAST_GPX_PATH) == "/tmp/track.gpx"

    db.set_folder_value(FOLDER_STATE_LAST_GPX_PATH, None)
    assert db.get_folder_value(FOLDER_STATE_LAST_GPX_PATH) is None

    db.close()
