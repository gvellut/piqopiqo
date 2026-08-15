"""Tests for metadata DB reconnect/retry behavior."""

from __future__ import annotations

from datetime import datetime
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


def test_bulk_metadata_matches_scalar_metadata_for_all_fields(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")
    source_folder = tmp_path / "photos"
    source_folder.mkdir()
    first_path = str(source_folder / "first.jpg")
    second_path = str(source_folder / "second.jpg")
    time_taken = datetime(2026, 8, 15, 11, 36, 29)
    db = MetadataDB(str(source_folder))
    db.save_metadata(
        first_path,
        {
            DBFields.TITLE: "First",
            DBFields.DESCRIPTION: "Description",
            DBFields.LATITUDE: 48.1,
            DBFields.LONGITUDE: -1.7,
            DBFields.KEYWORDS: "one,two",
            DBFields.TIME_TAKEN: time_taken,
            DBFields.LABEL: "Green",
            DBFields.ORIENTATION: 6,
            DBFields.MANUAL_LENS_MAKE: "Example",
            DBFields.MANUAL_LENS_MODEL: "Prime",
            DBFields.MANUAL_FOCAL_LENGTH: "35",
            DBFields.MANUAL_FOCAL_LENGTH_35MM: "52.5",
        },
    )
    db.save_metadata(second_path, {DBFields.ORIENTATION: 1})

    all_metadata = db.get_all_metadata()

    assert all_metadata == {
        first_path: db.get_metadata(first_path),
        second_path: db.get_metadata(second_path),
    }
    assert all_metadata[first_path][DBFields.TIME_TAKEN] == time_taken


def test_bulk_exif_coverage_counts_null_rows_as_present(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")
    source_folder = tmp_path / "photos"
    source_folder.mkdir()
    complete_path = str(source_folder / "complete.jpg")
    null_path = str(source_folder / "null.jpg")
    incomplete_path = str(source_folder / "incomplete.jpg")
    db = MetadataDB(str(source_folder))
    db.save_exif_fields(complete_path, {"EXIF:A": "a", "EXIF:B": "b"})
    db.save_exif_fields(null_path, {"EXIF:A": None, "EXIF:B": None})
    db.save_exif_fields(incomplete_path, {"EXIF:A": "a"})

    complete_paths = db.get_paths_with_exif_fields(["EXIF:A", "EXIF:B"])

    assert complete_paths == {complete_path, null_path}
    assert db.get_paths_with_exif_fields([]) == set()


def test_missing_database_returns_empty_bulk_read_results(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")
    source_folder = tmp_path / "photos"
    source_folder.mkdir()
    db = MetadataDB(str(source_folder))

    assert db.get_all_metadata() == {}
    assert db.get_paths_with_exif_fields(["EXIF:A"]) == set()


def test_failed_bulk_reads_return_empty_results(tmp_path, monkeypatch) -> None:
    set_cache_base_dir(tmp_path / "cache")
    source_folder = tmp_path / "photos"
    source_folder.mkdir()
    db = MetadataDB(str(source_folder))
    db.save_metadata(str(source_folder / "image.jpg"), {DBFields.TITLE: "Keep"})
    monkeypatch.setattr(db, "_get_connection", lambda create: _FailingConnection())
    monkeypatch.setattr(
        db,
        "_attempt_reopen_after_failure",
        lambda **_kwargs: (None, None),
    )

    assert db.get_all_metadata() == {}
    assert db.get_paths_with_exif_fields(["EXIF:A"]) == set()


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
