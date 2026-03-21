"""Tests for metadata DB reconnect/retry behavior."""

from __future__ import annotations

import sqlite3

from piqopiqo.cache_paths import set_cache_base_dir
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDB


class _FailingConnection:
    def execute(self, *_args, **_kwargs):
        raise sqlite3.DatabaseError("database disk image is malformed")


def test_get_metadata_retries_after_reopening_connection(tmp_path, monkeypatch) -> None:
    set_cache_base_dir(tmp_path / "cache")

    source_folder = tmp_path / "photos" / "folder_a"
    source_folder.mkdir(parents=True, exist_ok=True)
    file_path = str(source_folder / "image.jpg")

    db = MetadataDB(str(source_folder))
    db.save_metadata(file_path, {DBFields.TITLE: "Recovered"})

    original_get_connection = db._get_connection
    call_count = {"value": 0}

    def _flaky_get_connection(create: bool):
        if call_count["value"] == 0:
            call_count["value"] += 1
            return _FailingConnection()
        return original_get_connection(create)

    monkeypatch.setattr(db, "_get_connection", _flaky_get_connection)

    metadata = db.get_metadata(file_path)

    assert metadata is not None
    assert metadata[DBFields.TITLE] == "Recovered"
    assert call_count["value"] == 1
