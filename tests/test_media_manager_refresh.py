"""Tests for media refresh queue semantics."""

from __future__ import annotations

from datetime import datetime
import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

import piqopiqo.background.media_man as media_man
from piqopiqo.background.media_man import MediaManager, _FileInfo
from piqopiqo.cache_paths import set_cache_base_dir
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDBManager
from piqopiqo.ssf.settings_state import init_qsettings_store


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
