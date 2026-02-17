"""Tests for GPX apply service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import threading

from piqopiqo.cache_paths import set_cache_base_dir
from piqopiqo.gpx2exif.gpx_processing import GpxPoint, compute_position
from piqopiqo.gpx2exif.service import apply_gpx_to_folders
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDBManager


def _write_gpx(path: Path) -> None:
    path.write_text(
        """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<gpx version=\"1.1\" creator=\"pytest\" xmlns=\"http://www.topografix.com/GPX/1/1\">
  <trk>
    <name>Test</name>
    <trkseg>
      <trkpt lat=\"45.0000\" lon=\"7.0000\"><time>2026-01-01T10:00:00Z</time></trkpt>
      <trkpt lat=\"45.1000\" lon=\"7.1000\"><time>2026-01-01T10:01:00Z</time></trkpt>
      <trkpt lat=\"45.2000\" lon=\"7.2000\"><time>2026-01-01T10:02:00Z</time></trkpt>
    </trkseg>
  </trk>
</gpx>
""",
        encoding="utf-8",
    )


def _save_metadata(
    dbm: MetadataDBManager, file_path: str, time_taken: datetime
) -> None:
    db = dbm.get_db_for_image(file_path)
    db.save_metadata(
        file_path,
        {
            DBFields.TIME_TAKEN: time_taken,
            DBFields.LATITUDE: 1.0,
            DBFields.LONGITUDE: 2.0,
            DBFields.TITLE: None,
            DBFields.DESCRIPTION: None,
            DBFields.KEYWORDS: None,
            DBFields.LABEL: None,
            DBFields.ORIENTATION: 1,
        },
    )


def test_apply_gpx_update_mode_updates_db_and_clears_missing(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")

    root = tmp_path / "session"
    folder = root / "cam"
    folder.mkdir(parents=True)

    p1 = folder / "img1.jpg"
    p2 = folder / "img2.jpg"
    p1.write_bytes(b"")
    p2.write_bytes(b"")

    gpx_path = tmp_path / "track.gpx"
    _write_gpx(gpx_path)

    dbm = MetadataDBManager()
    _save_metadata(dbm, str(p1), datetime(2026, 1, 1, 10, 0, 30))
    _save_metadata(dbm, str(p2), datetime(2026, 1, 1, 9, 0, 0))
    dbm.get_db_for_folder(str(folder)).set_time_shift("30s")

    result = apply_gpx_to_folders(
        root_folder=str(root),
        folder_to_files={str(folder): [str(p1), str(p2)]},
        gpx_path=str(gpx_path),
        db_manager=dbm,
        timezone_name="",
        ignore_offset=True,
        kml_folder="",
        update_db=True,
        exiftool_path="",
    )

    assert result.cancelled is False
    assert result.processed == 2
    assert result.updated == 2
    assert len(result.kml_paths) == 1
    assert Path(result.kml_paths[0]).exists()

    db = dbm.get_db_for_folder(str(folder))
    m1 = db.get_metadata(str(p1))
    m2 = db.get_metadata(str(p2))

    assert m1 is not None
    assert m1[DBFields.TIME_TAKEN] == datetime(2026, 1, 1, 10, 1, 0)
    assert round(float(m1[DBFields.LATITUDE]), 4) == 45.1
    assert round(float(m1[DBFields.LONGITUDE]), 4) == 7.1

    assert m2 is not None
    assert m2[DBFields.TIME_TAKEN] == datetime(2026, 1, 1, 9, 0, 30)
    assert m2[DBFields.LATITUDE] is None
    assert m2[DBFields.LONGITUDE] is None

    dbm.close_all()


def test_apply_gpx_no_update_mode_keeps_db(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")

    root = tmp_path / "session"
    folder = root / "cam"
    folder.mkdir(parents=True)

    p1 = folder / "img1.jpg"
    p1.write_bytes(b"")

    gpx_path = tmp_path / "track.gpx"
    _write_gpx(gpx_path)

    dbm = MetadataDBManager()
    original_time = datetime(2026, 1, 1, 10, 0, 30)
    _save_metadata(dbm, str(p1), original_time)
    dbm.get_db_for_folder(str(folder)).set_time_shift("30s")

    result = apply_gpx_to_folders(
        root_folder=str(root),
        folder_to_files={str(folder): [str(p1)]},
        gpx_path=str(gpx_path),
        db_manager=dbm,
        timezone_name="",
        ignore_offset=True,
        kml_folder="",
        update_db=False,
        exiftool_path="",
    )

    assert result.cancelled is False
    assert result.updated == 0
    assert len(result.kml_paths) == 1

    db = dbm.get_db_for_folder(str(folder))
    meta = db.get_metadata(str(p1))
    assert meta is not None
    assert meta[DBFields.TIME_TAKEN] == original_time
    assert meta[DBFields.LATITUDE] == 1.0
    assert meta[DBFields.LONGITUDE] == 2.0

    dbm.close_all()


def test_apply_gpx_folder_scoped_rollback_on_cancel(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")

    root = tmp_path / "session"
    folder_a = root / "a"
    folder_b = root / "b"
    folder_a.mkdir(parents=True)
    folder_b.mkdir(parents=True)

    a1 = folder_a / "a1.jpg"
    b1 = folder_b / "b1.jpg"
    b2 = folder_b / "b2.jpg"
    for p in (a1, b1, b2):
        p.write_bytes(b"")

    gpx_path = tmp_path / "track.gpx"
    _write_gpx(gpx_path)

    dbm = MetadataDBManager()
    _save_metadata(dbm, str(a1), datetime(2026, 1, 1, 10, 0, 0))
    _save_metadata(dbm, str(b1), datetime(2026, 1, 1, 10, 0, 0))
    _save_metadata(dbm, str(b2), datetime(2026, 1, 1, 10, 0, 0))

    dbm.get_db_for_folder(str(folder_a)).set_time_shift("1s")
    dbm.get_db_for_folder(str(folder_b)).set_time_shift("2s")

    cancel_event = threading.Event()

    def progress_cb(completed: int, _total: int) -> None:
        if completed >= 2:
            cancel_event.set()

    result = apply_gpx_to_folders(
        root_folder=str(root),
        folder_to_files={
            str(folder_a): [str(a1)],
            str(folder_b): [str(b1), str(b2)],
        },
        gpx_path=str(gpx_path),
        db_manager=dbm,
        timezone_name="",
        ignore_offset=True,
        kml_folder="",
        update_db=True,
        exiftool_path="",
        cancel_event=cancel_event,
        progress_callback=progress_cb,
    )

    assert result.cancelled is True
    assert len(result.kml_paths) == 1
    assert result.updated_paths == [str(a1)]

    a_meta = dbm.get_db_for_folder(str(folder_a)).get_metadata(str(a1))
    b1_meta = dbm.get_db_for_folder(str(folder_b)).get_metadata(str(b1))
    b2_meta = dbm.get_db_for_folder(str(folder_b)).get_metadata(str(b2))

    assert a_meta is not None and a_meta[DBFields.TIME_TAKEN] == datetime(
        2026, 1, 1, 10, 0, 1
    )
    assert b1_meta is not None and b1_meta[DBFields.TIME_TAKEN] == datetime(
        2026, 1, 1, 10, 0, 0
    )
    assert b2_meta is not None and b2_meta[DBFields.TIME_TAKEN] == datetime(
        2026, 1, 1, 10, 0, 0
    )

    dbm.close_all()


def test_apply_gpx_kml_name_uses_relative_folder_token(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")

    root = tmp_path / "20251108_arve"
    folder = root / "sub1" / "sub2"
    folder.mkdir(parents=True)

    photo = folder / "img.jpg"
    photo.write_bytes(b"")

    gpx_path = tmp_path / "track.gpx"
    _write_gpx(gpx_path)

    dbm = MetadataDBManager()
    _save_metadata(dbm, str(photo), datetime(2026, 1, 1, 10, 0, 0))

    result = apply_gpx_to_folders(
        root_folder=str(root),
        folder_to_files={str(folder): [str(photo)]},
        gpx_path=str(gpx_path),
        db_manager=dbm,
        timezone_name="",
        ignore_offset=True,
        kml_folder="",
        update_db=False,
        exiftool_path="",
    )

    assert len(result.kml_paths) == 1
    kml_path = Path(result.kml_paths[0])
    assert kml_path.parent == root
    assert kml_path.name == "photos_20251108_arve_sub1_sub2.kml"

    dbm.close_all()


def test_compute_position_interpolates_between_points() -> None:
    points = [
        GpxPoint(
            time=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
            latitude=45.0,
            longitude=7.0,
        ),
        GpxPoint(
            time=datetime(2026, 1, 1, 10, 1, 0, tzinfo=UTC),
            latitude=45.1,
            longitude=7.1,
        ),
    ]
    match = compute_position(
        datetime(2026, 1, 1, 10, 0, 30, tzinfo=UTC),
        [points],
        timedelta(seconds=10),
    )
    assert match is not None
    lat, lon = match
    assert round(lat, 4) == 45.05
    assert round(lon, 4) == 7.05


def test_compute_position_checks_later_segments_when_first_is_out_of_range() -> None:
    segments = [
        [
            GpxPoint(
                time=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
                latitude=50.0,
                longitude=10.0,
            )
        ],
        [
            GpxPoint(
                time=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
                latitude=45.0,
                longitude=7.0,
            )
        ],
    ]
    match = compute_position(
        datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
        segments,
        timedelta(seconds=10),
    )
    assert match == (45.0, 7.0)
