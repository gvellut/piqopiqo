"""Tests for hidden manual lens fields in MetadataDB."""

from __future__ import annotations

from piqopiqo.cache_paths import set_cache_base_dir
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDB


def _base_metadata() -> dict:
    return {
        DBFields.TITLE: "Title",
        DBFields.DESCRIPTION: None,
        DBFields.LATITUDE: None,
        DBFields.LONGITUDE: None,
        DBFields.KEYWORDS: None,
        DBFields.TIME_TAKEN: None,
        DBFields.LABEL: None,
        DBFields.ORIENTATION: 1,
    }


def _table_columns(db: MetadataDB) -> set[str]:
    conn = db._ensure_db()  # noqa: SLF001
    cursor = conn.execute("PRAGMA table_info(photo_metadata)")
    return {str(row["name"]) for row in cursor.fetchall()}


def test_manual_lens_columns_are_created_lazily(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")
    folder = tmp_path / "photos"
    folder.mkdir(parents=True, exist_ok=True)

    db = MetadataDB(str(folder))
    file_path = str(folder / "a.jpg")

    db.save_metadata(file_path, _base_metadata())
    assert DBFields.MANUAL_LENS_MAKE not in _table_columns(db)

    with_lens = _base_metadata()
    with_lens[DBFields.MANUAL_LENS_MAKE] = "Samyang"
    with_lens[DBFields.MANUAL_LENS_MODEL] = "Samyang 12mm f/2.0 NCS CS"
    with_lens[DBFields.MANUAL_FOCAL_LENGTH] = "12"
    with_lens[DBFields.MANUAL_FOCAL_LENGTH_35MM] = "18"
    db.save_metadata(file_path, with_lens)

    columns = _table_columns(db)
    assert set(DBFields.MANUAL_LENS_FIELDS).issubset(columns)

    meta = db.get_metadata(file_path)
    assert meta is not None
    assert meta[DBFields.MANUAL_LENS_MODEL] == "Samyang 12mm f/2.0 NCS CS"

    db.close()


def test_manual_lens_values_are_preserved_on_partial_updates(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")
    folder = tmp_path / "photos"
    folder.mkdir(parents=True, exist_ok=True)

    db = MetadataDB(str(folder))
    file_path = str(folder / "a.jpg")

    with_lens = _base_metadata()
    with_lens[DBFields.MANUAL_LENS_MAKE] = "Sigma"
    with_lens[DBFields.MANUAL_LENS_MODEL] = "Sigma 18-35mm F1.8"
    with_lens[DBFields.MANUAL_FOCAL_LENGTH] = "24,5"
    with_lens[DBFields.MANUAL_FOCAL_LENGTH_35MM] = "36"
    db.save_metadata(file_path, with_lens)

    without_lens = _base_metadata()
    without_lens[DBFields.TITLE] = "Updated title"
    db.save_metadata(file_path, without_lens)

    meta = db.get_metadata(file_path)
    assert meta is not None
    assert meta[DBFields.TITLE] == "Updated title"
    assert meta[DBFields.MANUAL_LENS_MAKE] == "Sigma"
    assert meta[DBFields.MANUAL_LENS_MODEL] == "Sigma 18-35mm F1.8"
    assert meta[DBFields.MANUAL_FOCAL_LENGTH] == "24,5"
    assert meta[DBFields.MANUAL_FOCAL_LENGTH_35MM] == "36"

    db.close()
