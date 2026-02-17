"""Tests for FlickrUploadManager stage orchestration."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.flickr_upload.constants import (
    STAGE_MAKE_PUBLIC,
    STAGE_RESET_DATE,
    STAGE_UPLOAD,
)
from piqopiqo.flickr_upload.manager import FlickrUploadManager


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
    finished = []

    manager.stage_changed.connect(stages.append)
    manager.finished.connect(finished.append)

    def _fake_pool(_func, payloads, *, stage, progress_total, result):
        assert progress_total == len(payloads)
        if stage == STAGE_UPLOAD:
            return [
                {"ok": True, "file_path": "/a.jpg", "order": 0, "ticket_id": "t1"},
                {"ok": True, "file_path": "/b.jpg", "order": 1, "ticket_id": "t2"},
            ]
        if stage == STAGE_RESET_DATE:
            return [{"ok": True}, {"ok": True}]
        if stage == STAGE_MAKE_PUBLIC:
            return [{"ok": True}, {"ok": True}]
        raise AssertionError(stage)

    monkeypatch.setattr(manager, "_run_parallel_pool", _fake_pool)
    monkeypatch.setattr(
        "piqopiqo.flickr_upload.manager.run_resolve_tickets_task",
        lambda _payload: {"ok": True, "photo_ids": ["p1", "p2"], "failures": []},
    )

    manager._run(items)

    assert stages == [STAGE_UPLOAD, STAGE_RESET_DATE, STAGE_MAKE_PUBLIC]
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
        if stage == STAGE_UPLOAD:
            return [
                {"ok": True, "file_path": "/a.jpg", "order": 0, "ticket_id": "t1"},
                {
                    "ok": False,
                    "file_path": "/b.jpg",
                    "order": 1,
                    "error": "upload boom",
                },
            ]
        if stage == STAGE_RESET_DATE:
            return [{"ok": False, "file_path": "/a.jpg", "error": "set date boom"}]
        if stage == STAGE_MAKE_PUBLIC:
            return [{"ok": True, "file_path": "/a.jpg"}]
        raise AssertionError(stage)

    monkeypatch.setattr(manager, "_run_parallel_pool", _fake_pool)
    monkeypatch.setattr(
        "piqopiqo.flickr_upload.manager.run_resolve_tickets_task",
        lambda _payload: {
            "ok": True,
            "photo_ids": ["p1"],
            "failures": [
                {
                    "stage": STAGE_UPLOAD,
                    "file_path": "/a.jpg",
                    "error": "tag mismatch, replaced",
                }
            ],
        },
    )

    manager._run(items)

    assert stages == [STAGE_UPLOAD, STAGE_RESET_DATE, STAGE_MAKE_PUBLIC]
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

    assert stages == [STAGE_UPLOAD]
    assert len(finished) == 1
    result = finished[0]
    assert result.cancelled is True
