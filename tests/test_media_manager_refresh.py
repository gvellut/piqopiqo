"""Tests for media refresh queue semantics."""

from __future__ import annotations

from datetime import datetime
import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

import piqopiqo.background.media_man as media_man
from piqopiqo.background.media_man import MediaManager, _FileInfo
from piqopiqo.cache_paths import ensure_thumb_dir, set_cache_base_dir
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDBManager
from piqopiqo.ssf.settings_state import init_qsettings_store
from piqopiqo.storage import StorageWriteFault


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-media-manager-{uuid.uuid4().hex}")
    return app


@pytest.fixture(autouse=True)
def _test_environment(tmp_path):
    set_cache_base_dir(tmp_path / "cache")
    init_qsettings_store(dyn=True)


@pytest.fixture
def manager(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(
        MediaManager,
        "_ensure_min_idle_workers",
        lambda self: None,
    )
    db_manager = MetadataDBManager()
    media_manager = MediaManager(db_manager)
    yield media_manager
    media_manager.stop()
    db_manager.close_all()


def _register_file(manager: MediaManager, image_path: str, thumb_dir: str) -> None:
    manager._file_infos[image_path] = _FileInfo(
        file_path=image_path,
        source_folder=str(image_path.rsplit("/", 1)[0]),
        thumb_dir=thumb_dir,
        base_name="a",
    )


def test_refresh_files_retries_editable_metadata_when_db_row_missing(manager, tmp_path):
    image_path = str(tmp_path / "a.jpg")
    thumb_dir = str(tmp_path / "thumbs")
    _register_file(manager, image_path, thumb_dir)

    manager.refresh_files([image_path])

    need = manager._pending_combined_other[image_path]
    assert need.want_embedded is True
    assert need.want_panel is True
    assert need.want_editable is True
    assert need.force is True


def test_refresh_files_preserves_existing_editable_metadata(manager, tmp_path):
    image_path = str(tmp_path / "a.jpg")
    thumb_dir = str(tmp_path / "thumbs")
    _register_file(manager, image_path, thumb_dir)
    db = manager._db_manager.get_db_for_folder(str(tmp_path))
    db.save_metadata(image_path, {DBFields.TITLE: "Edited title"})

    manager.refresh_files([image_path])

    need = manager._pending_combined_other[image_path]
    assert need.want_embedded is True
    assert need.want_panel is True
    assert need.want_editable is False
    assert need.force is True


def test_refresh_files_retries_editable_metadata_when_db_row_is_empty(
    manager, tmp_path
):
    image_path = str(tmp_path / "a.jpg")
    thumb_dir = str(tmp_path / "thumbs")
    _register_file(manager, image_path, thumb_dir)
    db = manager._db_manager.get_db_for_folder(str(tmp_path))
    db.save_metadata(image_path, {DBFields.ORIENTATION: 1})

    manager.refresh_files([image_path])

    need = manager._pending_combined_other[image_path]
    assert need.want_embedded is True
    assert need.want_panel is True
    assert need.want_editable is True
    assert need.force is True


def test_startup_retries_editable_metadata_when_cached_db_row_is_empty(
    manager, tmp_path
):
    image_path = str(tmp_path / "a.jpg")
    db = manager._db_manager.get_db_for_folder(str(tmp_path))
    db.save_metadata(image_path, {DBFields.ORIENTATION: 1})

    priming = manager.reset_for_folder([image_path], [str(tmp_path)])

    assert priming.cached_editable_metadata == {}
    assert priming.missing_editable_paths == {image_path}
    need = manager._pending_combined_other[image_path]
    assert need.want_editable is True


def test_startup_bulk_priming_uses_fully_cached_files(manager, tmp_path):
    source_folder = tmp_path / "photos"
    source_folder.mkdir()
    image_paths = [
        str(source_folder / "a.jpg"),
        str(source_folder / "b.jpg"),
    ]
    db = manager._db_manager.get_db_for_folder(str(source_folder))
    thumb_dir = ensure_thumb_dir(str(source_folder))
    for image_path in image_paths:
        base_name = image_path.rsplit("/", 1)[1].rsplit(".", 1)[0]
        db.save_metadata(image_path, {DBFields.TITLE: base_name})
        db.save_exif_fields(
            image_path,
            {key: None for key in manager._panel_field_keys},
        )
        (thumb_dir / "embedded" / f"{base_name}.jpg").write_bytes(b"embedded")
        (thumb_dir / "hq" / f"{base_name}.jpg").write_bytes(b"hq")

    priming = manager.reset_for_folder(image_paths, [str(source_folder)])

    assert set(priming.cached_editable_metadata) == set(image_paths)
    assert priming.missing_editable_paths == set()
    assert manager._editable_done == set(image_paths)
    assert manager._thumb_done == set(image_paths)
    assert manager._pending_combined_other == {}
    assert manager._pending_hq_other == set()


def test_startup_lowres_only_uses_bulk_embedded_cache_snapshot(
    manager, tmp_path, monkeypatch
):
    source_folder = tmp_path / "photos"
    source_folder.mkdir()
    image_path = str(source_folder / "a.jpg")
    db = manager._db_manager.get_db_for_folder(str(source_folder))
    db.save_metadata(image_path, {DBFields.TITLE: "Cached"})
    db.save_exif_fields(
        image_path,
        {key: None for key in manager._panel_field_keys},
    )
    thumb_dir = ensure_thumb_dir(str(source_folder))
    (thumb_dir / "embedded" / "a.jpg").write_bytes(b"embedded")
    monkeypatch.setattr(manager, "_is_lowres_only_mode", lambda: True)

    manager.reset_for_folder([image_path], [str(source_folder)])

    assert manager._thumb_done == {image_path}
    assert manager._pending_combined_other == {}
    assert manager._pending_hq_other == set()


def test_startup_bulk_priming_migrates_known_legacy_thumbnails(manager, tmp_path):
    source_folder = tmp_path / "photos"
    source_folder.mkdir()
    image_path = str(source_folder / "a.jpg")
    thumb_dir = ensure_thumb_dir(str(source_folder))
    (thumb_dir / "a_embedded.jpg").write_bytes(b"embedded")
    (thumb_dir / "a_hq.jpg").write_bytes(b"hq")

    manager.reset_for_folder([image_path], [str(source_folder)])

    assert (thumb_dir / "embedded" / "a.jpg").read_bytes() == b"embedded"
    assert (thumb_dir / "hq" / "a.jpg").read_bytes() == b"hq"
    assert manager._thumb_done == {image_path}
    need = manager._pending_combined_other[image_path]
    assert need.want_embedded is False


def test_startup_failed_legacy_migration_queues_replacement(
    manager, tmp_path, monkeypatch
):
    source_folder = tmp_path / "photos"
    source_folder.mkdir()
    image_path = str(source_folder / "a.jpg")
    thumb_dir = ensure_thumb_dir(str(source_folder))
    (thumb_dir / "a_embedded.jpg").write_bytes(b"embedded")
    (thumb_dir / "a_hq.jpg").write_bytes(b"hq")
    monkeypatch.setattr(
        manager,
        "_migrate_known_legacy_thumb",
        lambda _legacy_path, _new_path: False,
    )

    manager.reset_for_folder([image_path], [str(source_folder)])

    need = manager._pending_combined_other[image_path]
    assert need.want_embedded is True
    assert image_path in manager._pending_hq_other


class _BulkReadDB:
    def __init__(self, file_paths: list[str]):
        self.file_paths = set(file_paths)
        self.metadata_calls = 0
        self.exif_calls = 0

    def get_all_metadata(self) -> dict[str, dict]:
        self.metadata_calls += 1
        return {path: {DBFields.TITLE: "Cached"} for path in self.file_paths}

    def get_paths_with_exif_fields(self, _field_keys: list[str]) -> set[str]:
        self.exif_calls += 1
        return set(self.file_paths)

    def get_metadata(self, _file_path: str):
        raise AssertionError("bulk reset must not use scalar metadata reads")

    def has_exif_fields(self, _file_path: str, _field_keys: list[str]):
        raise AssertionError("bulk reset must not use scalar EXIF checks")


class _BulkReadDBManager:
    def __init__(self, paths_by_folder: dict[str, list[str]]):
        self.databases = {
            folder: _BulkReadDB(paths) for folder, paths in paths_by_folder.items()
        }

    def get_db_for_folder(self, folder: str) -> _BulkReadDB:
        return self.databases[folder]


def test_startup_bulk_priming_batches_storage_checks_per_folder(
    manager, tmp_path, monkeypatch
):
    folders = [str(tmp_path / "folder_a"), str(tmp_path / "folder_b")]
    paths_by_folder = {
        folder: [f"{folder}/image_{index}.jpg" for index in range(20)]
        for folder in folders
    }
    for folder in folders:
        tmp_path.joinpath(folder.rsplit("/", 1)[1]).mkdir()
        ensure_thumb_dir(folder)

    fake_db_manager = _BulkReadDBManager(paths_by_folder)
    manager._db_manager = fake_db_manager

    ensure_calls: list[str] = []
    real_ensure_thumb_dir = media_man.ensure_thumb_dir

    def _counted_ensure_thumb_dir(folder: str):
        ensure_calls.append(folder)
        return real_ensure_thumb_dir(folder)

    scan_calls: list[str] = []
    real_scandir = media_man.os.scandir

    def _counted_scandir(directory):
        scan_calls.append(str(directory))
        return real_scandir(directory)

    monkeypatch.setattr(media_man, "ensure_thumb_dir", _counted_ensure_thumb_dir)
    monkeypatch.setattr(media_man.os, "scandir", _counted_scandir)
    monkeypatch.setattr(
        media_man.os.path,
        "exists",
        lambda _path: (_ for _ in ()).throw(
            AssertionError("bulk reset must not use per-photo exists checks")
        ),
    )

    manager.reset_for_folder(
        [path for paths in paths_by_folder.values() for path in paths],
        folders,
    )

    assert ensure_calls == folders
    for folder, db in fake_db_manager.databases.items():
        assert db.metadata_calls == 1
        assert db.exif_calls == 1
        thumb_dir = real_ensure_thumb_dir(folder)
        assert scan_calls.count(str(thumb_dir)) == 1
        assert scan_calls.count(str(thumb_dir / "embedded")) == 1
        assert scan_calls.count(str(thumb_dir / "hq")) == 1
    assert len(scan_calls) == 3 * len(folders)


def test_incremental_add_keeps_targeted_per_file_checks(manager, tmp_path, monkeypatch):
    source_folder = tmp_path / "photos"
    source_folder.mkdir()
    image_path = str(source_folder / "a.jpg")
    db = manager._db_manager.get_db_for_folder(str(source_folder))
    scalar_calls: list[str] = []
    monkeypatch.setattr(
        db,
        "get_metadata",
        lambda file_path: scalar_calls.append(f"metadata:{file_path}"),
    )
    monkeypatch.setattr(
        db,
        "has_exif_fields",
        lambda file_path, _keys: scalar_calls.append(f"exif:{file_path}") or False,
    )
    monkeypatch.setattr(
        manager,
        "_build_folder_priming_snapshot",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("incremental add must not build a folder snapshot")
        ),
    )

    manager.add_files([image_path])

    assert scalar_calls == [f"metadata:{image_path}", f"exif:{image_path}"]


def test_empty_automatic_editable_result_does_not_update_db(manager, tmp_path):
    image_path = str(tmp_path / "a.jpg")
    thumb_dir = str(tmp_path / "thumbs")
    _register_file(manager, image_path, thumb_dir)

    manager._handle_combined_result({
        "items": [
            {
                "file_path": image_path,
                "editable_metadata": {DBFields.ORIENTATION: 1},
                "allow_empty_editable": False,
            }
        ]
    })

    db = manager._db_manager.get_db_for_folder(str(tmp_path))
    assert db.get_metadata(image_path) is None


def test_non_empty_automatic_editable_result_updates_db(manager, tmp_path):
    image_path = str(tmp_path / "a.jpg")
    thumb_dir = str(tmp_path / "thumbs")
    _register_file(manager, image_path, thumb_dir)
    time_taken = datetime(2026, 1, 1, 10, 0, 0)

    manager._handle_combined_result({
        "items": [
            {
                "file_path": image_path,
                "editable_metadata": {
                    DBFields.TIME_TAKEN: time_taken,
                    DBFields.ORIENTATION: 1,
                },
                "allow_empty_editable": False,
            }
        ]
    })

    db = manager._db_manager.get_db_for_folder(str(tmp_path))
    metadata = db.get_metadata(image_path)
    assert metadata is not None
    assert metadata[DBFields.TIME_TAKEN] == time_taken


def test_explicit_reload_can_update_db_with_empty_editable_result(manager, tmp_path):
    image_path = str(tmp_path / "a.jpg")
    thumb_dir = str(tmp_path / "thumbs")
    _register_file(manager, image_path, thumb_dir)

    manager._handle_combined_result({
        "items": [
            {
                "file_path": image_path,
                "editable_metadata": {DBFields.ORIENTATION: 1},
                "allow_empty_editable": True,
            }
        ]
    })

    db = manager._db_manager.get_db_for_folder(str(tmp_path))
    metadata = db.get_metadata(image_path)
    assert metadata is not None
    assert metadata[DBFields.ORIENTATION] == 1


def test_combined_error_schedules_retry_without_saving_empty_metadata(
    manager, tmp_path, monkeypatch
):
    image_path = str(tmp_path / "a.jpg")
    thumb_dir = str(tmp_path / "thumbs")
    tmp_path.joinpath("a.jpg").write_bytes(b"partial")
    _register_file(manager, image_path, thumb_dir)

    retry_callbacks: list[object] = []
    monkeypatch.setattr(
        media_man.QTimer,
        "singleShot",
        lambda _delay_ms, callback: retry_callbacks.append(callback),
    )

    manager._handle_combined_result({
        "items": [
            {
                "file_path": image_path,
                "want_embedded": True,
                "want_editable": True,
                "want_panel": True,
                "editable_metadata": {DBFields.ORIENTATION: 1},
                "allow_empty_editable": False,
                "panel_fields": {"File:FileName": None},
                "retry_count": 0,
                "error": "exiftool status 1",
            }
        ]
    })

    db = manager._db_manager.get_db_for_folder(str(tmp_path))
    assert db.get_metadata(image_path) is None
    assert image_path not in manager._editable_done
    assert manager.get_exif_errors() == {}
    assert len(retry_callbacks) == 1

    retry_callbacks[0]()

    need = manager._pending_combined_other[image_path]
    assert need.want_embedded is True
    assert need.want_editable is True
    assert need.want_panel is True
    assert need.force is True
    assert need.retry_count == 1


def test_combined_error_records_error_after_retry_limit(manager, tmp_path, monkeypatch):
    image_path = str(tmp_path / "a.jpg")
    thumb_dir = str(tmp_path / "thumbs")
    tmp_path.joinpath("a.jpg").write_bytes(b"partial")
    _register_file(manager, image_path, thumb_dir)
    monkeypatch.setattr(
        media_man.QTimer,
        "singleShot",
        lambda _delay_ms, _callback: (_ for _ in ()).throw(
            AssertionError("retry should not be scheduled")
        ),
    )

    manager._handle_combined_result({
        "items": [
            {
                "file_path": image_path,
                "want_embedded": True,
                "want_editable": True,
                "want_panel": True,
                "editable_metadata": {DBFields.ORIENTATION: 1},
                "allow_empty_editable": False,
                "panel_fields": {"File:FileName": None},
                "retry_count": media_man.COMBINED_MAX_RETRIES,
                "error": "exiftool status 1",
            }
        ]
    })

    assert manager.get_exif_errors() == {image_path: "exiftool status 1"}


def test_reload_exif_still_queues_editable_metadata_overwrite(manager, tmp_path):
    image_path = str(tmp_path / "a.jpg")
    thumb_dir = str(tmp_path / "thumbs")
    _register_file(manager, image_path, thumb_dir)

    manager.reload_exif([image_path])

    need = manager._pending_combined_other[image_path]
    assert need.want_embedded is False
    assert need.want_panel is True
    assert need.want_editable is True
    assert need.force is True
    assert need.allow_empty_editable is True


def test_storage_full_results_pause_scheduling_and_emit_once(manager, tmp_path):
    image_path = str(tmp_path / "a.jpg")
    thumb_dir = str(tmp_path / "thumbs")
    _register_file(manager, image_path, thumb_dir)
    fault = StorageWriteFault(
        target_path=str(tmp_path),
        operation="write_hq_thumbnail",
        error_message="No space left on device",
    )
    reported: list[StorageWriteFault] = []
    manager.storage_full.connect(reported.append)

    result = {
        "file_path": image_path,
        "ok": False,
        "error": fault.error_message,
        "storage_full_fault": fault,
    }
    manager._handle_hq_result(result)
    manager._handle_hq_result(result)

    assert manager._processing_paused is True
    assert reported == [fault]
    assert manager.get_thumb_errors() == {image_path: "No space left on device"}


def test_paused_manager_drains_results_without_scheduling(manager, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(manager, "_drain_results", lambda: calls.append("drain"))
    monkeypatch.setattr(manager, "_schedule_work", lambda: calls.append("schedule"))
    monkeypatch.setattr(
        manager,
        "_stop_extra_idle_workers",
        lambda: calls.append("stop_idle"),
    )
    monkeypatch.setattr(
        manager,
        "_ensure_min_idle_workers",
        lambda: calls.append("ensure_idle"),
    )

    manager.pause_processing()
    manager._tick()

    assert calls == ["drain"]


def test_regenerate_retains_existing_cache_until_replacement(manager, tmp_path):
    image_path = str(tmp_path / "a.jpg")
    thumb_dir = tmp_path / "thumbs"
    _register_file(manager, image_path, str(thumb_dir))
    embedded_path = thumb_dir / "embedded" / "a.jpg"
    hq_path = thumb_dir / "hq" / "a.jpg"
    embedded_path.parent.mkdir(parents=True)
    hq_path.parent.mkdir(parents=True)
    embedded_path.write_bytes(b"old-embedded")
    hq_path.write_bytes(b"old-hq")
    manager._thumb_done.add(image_path)
    manager._thumb_completed = 1

    manager.regenerate_thumbnails([image_path])

    assert embedded_path.read_bytes() == b"old-embedded"
    assert hq_path.read_bytes() == b"old-hq"
    assert manager._thumb_completed == 1
    assert manager._pending_combined_other[image_path].force is True
    assert image_path in manager._pending_hq_other
