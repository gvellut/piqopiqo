"""Tests for folder-scoped metadata in MetadataDB."""

from __future__ import annotations

from piqopiqo.cache_paths import set_cache_base_dir
from piqopiqo.metadata.metadata_db import MetadataDB


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


def test_time_shift_helpers(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")

    source_folder = tmp_path / "photos" / "folder_b"
    source_folder.mkdir(parents=True, exist_ok=True)

    db = MetadataDB(str(source_folder))

    assert db.get_time_shift() is None

    db.set_time_shift("-1h16m5s")
    assert db.get_time_shift() == "-1h16m5s"

    db.set_time_shift("")
    assert db.get_time_shift() is None

    db.close()
