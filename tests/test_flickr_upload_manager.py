"""Tests for FlickrUploadManager stage orchestration."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.tools.flickr_upload.albums import FlickrAlbumPlan
from piqopiqo.tools.flickr_upload.constants import MAX_NUM_CHECKS, FlickrStage
from piqopiqo.tools.flickr_upload.manager import FlickrUploadManager


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _mk_manager() -> FlickrUploadManager:
    return FlickrUploadManager(
        api_key="k",
        api_secret="s",
        exiftool_path="/opt/homebrew/bin/exiftool",
        token_cache_dir="/tmp",
        max_workers=2,
    )


def test_manager_stage_sequence_success(qapp, monkeypatch) -> None:  # noqa: ARG001
    manager = _mk_manager()
    items = [
        {"file_path": "/a.jpg", "order": 0, "db_metadata": None},
        {"file_path": "/b.jpg", "order": 1, "db_metadata": None},
    ]

    stages: list[str] = []
    statuses: list[str] = []
    finished = []

    manager.stage_changed.connect(stages.append)
    manager.status.connect(statuses.append)
    manager.finished.connect(finished.append)

    def _fake_pool(_func, payloads, *, stage, progress_total, result):
        assert progress_total == len(payloads)
        if stage == FlickrStage.STAGE_UPLOAD.label:
            return [
                {"ok": True, "file_path": "/a.jpg", "order": 0, "ticket_id": "t1"},
                {"ok": True, "file_path": "/b.jpg", "order": 1, "ticket_id": "t2"},
            ]
        if stage == FlickrStage.STAGE_RESET_DATE.label:
            return [{"ok": True}, {"ok": True}]
        if stage == FlickrStage.STAGE_MAKE_PUBLIC.label:
            return [{"ok": True}, {"ok": True}]
        raise AssertionError(stage)

    monkeypatch.setattr(manager, "_run_parallel_pool", _fake_pool)

    def _fake_resolve(_payload, check_progress_callback=None):
        if check_progress_callback is not None:
            check_progress_callback(1, MAX_NUM_CHECKS)
            check_progress_callback(2, MAX_NUM_CHECKS)
        return {"ok": True, "photo_ids": ["p1", "p2"], "failures": []}

    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.manager.run_resolve_tickets_task",
        _fake_resolve,
    )

    manager._run(items)

    assert stages == [
        FlickrStage.STAGE_UPLOAD.label,
        FlickrStage.STAGE_CHECK_UPLOAD_STATUS.label,
        FlickrStage.STAGE_RESET_DATE.label,
        FlickrStage.STAGE_MAKE_PUBLIC.label,
    ]
    assert f"Check 0/{MAX_NUM_CHECKS}" in statuses
    assert f"Check 1/{MAX_NUM_CHECKS}" in statuses
    assert f"Check 2/{MAX_NUM_CHECKS}" in statuses
    assert len(finished) == 1
    result = finished[0]
    assert result.fatal_error == ""
    assert result.cancelled is False
    assert result.uploaded_count == 2
    assert result.reset_date_count == 2
    assert result.made_public_count == 2


def test_manager_continues_and_aggregates_failures(qapp, monkeypatch) -> None:  # noqa: ARG001
    manager = _mk_manager()
    items = [
        {"file_path": "/a.jpg", "order": 0, "db_metadata": None},
        {"file_path": "/b.jpg", "order": 1, "db_metadata": None},
    ]

    stages: list[str] = []
    finished = []

    manager.stage_changed.connect(stages.append)
    manager.finished.connect(finished.append)

    def _fake_pool(_func, payloads, *, stage, progress_total, result):  # noqa: ARG001
        if stage == FlickrStage.STAGE_UPLOAD.label:
            return [
                {"ok": True, "file_path": "/a.jpg", "order": 0, "ticket_id": "t1"},
                {
                    "ok": False,
                    "file_path": "/b.jpg",
                    "order": 1,
                    "error": "upload boom",
                },
            ]
        if stage == FlickrStage.STAGE_RESET_DATE.label:
            return [{"ok": False, "file_path": "/a.jpg", "error": "set date boom"}]
        if stage == FlickrStage.STAGE_MAKE_PUBLIC.label:
            return [{"ok": True, "file_path": "/a.jpg"}]
        raise AssertionError(stage)

    monkeypatch.setattr(manager, "_run_parallel_pool", _fake_pool)
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.manager.run_resolve_tickets_task",
        lambda _payload, check_progress_callback=None: {
            "ok": True,
            "photo_ids": ["p1"],
            "failures": [
                {
                    "stage": FlickrStage.STAGE_UPLOAD.label,
                    "file_path": "/a.jpg",
                    "error": "tag mismatch, replaced",
                }
            ],
        },
    )

    manager._run(items)

    assert stages == [
        FlickrStage.STAGE_UPLOAD.label,
        FlickrStage.STAGE_CHECK_UPLOAD_STATUS.label,
        FlickrStage.STAGE_RESET_DATE.label,
        FlickrStage.STAGE_MAKE_PUBLIC.label,
    ]
    assert len(finished) == 1
    result = finished[0]
    assert result.fatal_error == ""
    assert result.cancelled is False
    assert result.uploaded_count == 1
    assert result.reset_date_count == 0
    assert result.made_public_count == 1
    assert len(result.failures) == 3


def test_manager_cancellation_short_circuit(qapp, monkeypatch) -> None:  # noqa: ARG001
    manager = _mk_manager()
    items = [{"file_path": "/a.jpg", "order": 0, "db_metadata": None}]

    stages: list[str] = []
    finished = []

    manager.stage_changed.connect(stages.append)
    manager.finished.connect(finished.append)

    manager.request_cancel()

    def _fake_pool(_func, payloads, *, stage, progress_total, result):  # noqa: ARG001
        result.cancelled = True
        return []

    monkeypatch.setattr(manager, "_run_parallel_pool", _fake_pool)

    manager._run(items)

    assert stages == [FlickrStage.STAGE_UPLOAD.label]
    assert len(finished) == 1
    result = finished[0]
    assert result.cancelled is True


def test_manager_album_stage_create_then_add(qapp, monkeypatch) -> None:  # noqa: ARG001
    saved_album_ids: list[str] = []
    manager = FlickrUploadManager(
        api_key="k",
        api_secret="s",
        exiftool_path="/opt/homebrew/bin/exiftool",
        token_cache_dir="/tmp",
        max_workers=2,
        album_plan=FlickrAlbumPlan(
            raw_text="Trip 2026",
            album_title="Trip 2026",
            is_create=True,
        ),
        on_album_id_resolved=saved_album_ids.append,
    )
    items = [
        {"file_path": "/a.jpg", "order": 0, "db_metadata": None},
        {"file_path": "/b.jpg", "order": 1, "db_metadata": None},
    ]

    stages: list[str] = []
    finished = []
    manager.stage_changed.connect(stages.append)
    manager.finished.connect(finished.append)

    def _fake_pool(_func, payloads, *, stage, progress_total, result):  # noqa: ARG001
        if stage == FlickrStage.STAGE_UPLOAD.label:
            return [
                {"ok": True, "file_path": "/a.jpg", "order": 0, "ticket_id": "t1"},
                {"ok": True, "file_path": "/b.jpg", "order": 1, "ticket_id": "t2"},
            ]
        if stage == FlickrStage.STAGE_RESET_DATE.label:
            return [{"ok": True}, {"ok": True}]
        if stage == FlickrStage.STAGE_MAKE_PUBLIC.label:
            return [{"ok": True}, {"ok": True}]
        raise AssertionError(stage)

    monkeypatch.setattr(manager, "_run_parallel_pool", _fake_pool)
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.manager.run_resolve_tickets_task",
        lambda _payload, check_progress_callback=None: {
            "ok": True,
            "photo_ids": ["p1", "p2"],
            "failures": [],
        },
    )
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.manager.run_create_album_task",
        lambda _payload: {
            "ok": True,
            "album_id": "72177720331888267",
            "album_title": "Trip 2026",
            "user_nsid": "22539273@N00",
            "album_url": (
                "https://flickr.com/photos/22539273@N00/albums/72177720331888267"
            ),
        },
    )
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.manager.run_add_to_album_task",
        lambda _payload: {"ok": True, "added_count": 2},
    )

    manager._run(items)

    assert stages == [
        FlickrStage.STAGE_UPLOAD.label,
        FlickrStage.STAGE_CHECK_UPLOAD_STATUS.label,
        FlickrStage.STAGE_RESET_DATE.label,
        FlickrStage.STAGE_MAKE_PUBLIC.label,
        FlickrStage.STAGE_ADD_TO_ALBUM.label,
    ]
    assert saved_album_ids == ["72177720331888267"]
    assert len(finished) == 1
    result = finished[0]
    assert result.album_created is True
    assert result.album_id == "72177720331888267"
    assert result.album_added_count == 2


def test_manager_album_stage_add_failure_is_reported(qapp, monkeypatch) -> None:  # noqa: ARG001
    manager = FlickrUploadManager(
        api_key="k",
        api_secret="s",
        exiftool_path="/opt/homebrew/bin/exiftool",
        token_cache_dir="/tmp",
        max_workers=2,
        album_plan=FlickrAlbumPlan(
            raw_text="72177720331888267",
            album_id="72177720331888267",
            album_title="Trip 2026",
            is_create=False,
        ),
    )
    items = [{"file_path": "/a.jpg", "order": 0, "db_metadata": None}]

    finished = []
    manager.finished.connect(finished.append)

    def _fake_pool(_func, payloads, *, stage, progress_total, result):  # noqa: ARG001
        if stage == FlickrStage.STAGE_UPLOAD.label:
            return [{"ok": True, "file_path": "/a.jpg", "order": 0, "ticket_id": "t1"}]
        if stage == FlickrStage.STAGE_RESET_DATE.label:
            return [{"ok": True}]
        if stage == FlickrStage.STAGE_MAKE_PUBLIC.label:
            return [{"ok": True}]
        raise AssertionError(stage)

    monkeypatch.setattr(manager, "_run_parallel_pool", _fake_pool)
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.manager.run_resolve_tickets_task",
        lambda _payload, check_progress_callback=None: {
            "ok": True,
            "photo_ids": ["p1"],
            "failures": [],
        },
    )
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.manager.run_add_to_album_task",
        lambda _payload: {"ok": False, "error": "Album update failed"},
    )

    manager._run(items)

    assert len(finished) == 1
    result = finished[0]
    assert result.album_id == "72177720331888267"
    assert result.album_added_count == 0
    assert any(
        failure.stage == FlickrStage.STAGE_ADD_TO_ALBUM.label
        and "Album update failed" in failure.message
        for failure in result.failures
    )
