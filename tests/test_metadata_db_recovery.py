"""Tests for metadata DB reconnect/retry behavior."""

from __future__ import annotations

import sqlite3

from piqopiqo.cache_paths import set_cache_base_dir
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDB
from piqopiqo.storage import StorageWriteFault


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


def test_database_full_has_distinct_fault_classification(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")
    source_folder = tmp_path / "photos"
    source_folder.mkdir()
    db = MetadataDB(str(source_folder))

    fault = db._classify_open_failure(
        operation="save_metadata",
        exc=sqlite3.OperationalError("database or disk is full"),
        during_write=True,
        path_available=True,
    )

    assert fault.classification == "storage_full"
    assert fault.is_storage_full is True
    assert fault.is_transient is False


def test_ambiguous_sqlite_open_uses_storage_probe(tmp_path, monkeypatch) -> None:
    set_cache_base_dir(tmp_path / "cache")
    source_folder = tmp_path / "photos"
    source_folder.mkdir()
    db = MetadataDB(str(source_folder))
    detected = StorageWriteFault(
        target_path=str(db.db_path.parent),
        operation="save_metadata",
        error_message="No space left on device",
    )
    monkeypatch.setattr(
        "piqopiqo.metadata.metadata_db.storage_full_fault_from_error",
        lambda *_args, **_kwargs: detected,
    )

    fault = db._classify_open_failure(
        operation="save_metadata",
        exc=sqlite3.OperationalError("unable to open database file"),
        during_write=True,
        path_available=True,
    )

    assert fault.classification == "storage_full"


def test_health_probe_can_require_a_rolled_back_database_write(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")
    source_folder = tmp_path / "photos"
    source_folder.mkdir()
    image_path = str(source_folder / "image.jpg")
    db = MetadataDB(str(source_folder))
    db.save_metadata(image_path, {DBFields.TITLE: "Keep"})

    healthy, fault = db.probe_health(require_write=True)

    assert healthy is True
    assert fault is None
    assert db.get_metadata(image_path)[DBFields.TITLE] == "Keep"


def test_required_write_probe_reports_storage_full(tmp_path, monkeypatch) -> None:
    set_cache_base_dir(tmp_path / "cache")
    source_folder = tmp_path / "photos"
    source_folder.mkdir()
    image_path = str(source_folder / "image.jpg")
    db = MetadataDB(str(source_folder))
    db.save_metadata(image_path, {DBFields.TITLE: "Keep"})
    monkeypatch.setattr(
        db,
        "_probe_write_connection",
        lambda _connection: (_ for _ in ()).throw(
            sqlite3.OperationalError("database or disk is full")
        ),
    )

    healthy, fault = db.probe_health(require_write=True)

    assert healthy is False
    assert fault is not None
    assert fault.is_storage_full is True
