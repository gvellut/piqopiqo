"""New-album reorder behavior at the end of Flickr upload."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.tools.flickr_tools.album_order import BACKUP_FOLDER_NAME
from piqopiqo.tools.flickr_tools.upload.constants import FlickrStage
from piqopiqo.tools.flickr_tools.upload.manager import (
    FlickrUploadManager,
    FlickrUploadResult,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _manager(tmp_path, *, limit: int = 3, enabled: bool = True):
    return FlickrUploadManager(
        api_key="k",
        api_secret="s",
        exiftool_path="/opt/homebrew/bin/exiftool",
        token_cache_dir=str(tmp_path),
        max_workers=2,
        quick_timeout_s=5.0,
        heavy_timeout_s=30.0,
        very_long_timeout_s=120.0,
        reorder_new_albums=enabled,
        reorder_new_albums_limit=limit,
        reorder_backup_limit=3,
        support_dir=tmp_path,
    )


class _PhotoSets:
    def __init__(self, album_ids: list[str], dates: dict[str, str | None]):
        self.album_ids = album_ids
        self.dates = dates
        self.read_photo_ids: list[str] = []
        self.order_calls: list[tuple[str, float]] = []
        self.order_error: Exception | None = None

    def getList(self, **_kwargs):
        return {
            "photosets": {
                "page": 1,
                "pages": 1,
                "photoset": [
                    {"id": album_id, "title": {"_content": album_id}}
                    for album_id in self.album_ids
                ],
            }
        }

    def getPhotos(self, photoset_id: str, **kwargs):
        assert kwargs["extras"] == "date_taken"
        self.read_photo_ids.append(photoset_id)
        date = self.dates[photoset_id]
        photos = [] if date is None else [{"datetaken": date}]
        return {
            "photoset": {"page": 1, "pages": 1, "photo": photos},
        }

    def orderSets(self, photoset_ids: str, timeout: float):
        self.order_calls.append((photoset_ids, timeout))
        if self.order_error is not None:
            raise self.order_error


def _install_flickr(monkeypatch, album_ids, dates):
    photosets = _PhotoSets(album_ids, dates)

    class _Flickr:
        pass

    flickr = _Flickr()
    flickr.photosets = photosets
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_tools.upload.manager.create_flickr_client",
        lambda *_args, **_kwargs: flickr,
    )
    return photosets


def _reorder(manager):
    result = FlickrUploadResult(
        total_photos=1,
        uploaded_count=1,
        album_id="new",
        album_created=True,
        album_added_count=1,
    )
    manager._run_reorder_new_album_stage(result)
    return result


def test_reorders_unsorted_window_and_preserves_tail_with_full_backup(
    qapp, monkeypatch, tmp_path
) -> None:  # noqa: ARG001
    photosets = _install_flickr(
        monkeypatch,
        ["new", "old", "recent", "tail1", "tail2"],
        {
            "new": "2025-01-01 12:00:00",
            "old": "2024-01-01 12:00:00",
            "recent": "2026-01-01 12:00:00",
        },
    )
    manager = _manager(tmp_path)

    result = _reorder(manager)

    assert photosets.read_photo_ids == ["new", "old", "recent"]
    assert photosets.order_calls == [("recent,new,old,tail1,tail2", 120.0)]
    assert result.album_reordered is True
    assert result.failures == []
    assert json.loads(
        Path(result.album_reorder_backup_path).read_text(encoding="utf-8")
    ) == [
        "new",
        "old",
        "recent",
        "tail1",
        "tail2",
    ]


def test_calls_order_sets_when_new_album_stays_first(
    qapp, monkeypatch, tmp_path
) -> None:  # noqa: ARG001
    photosets = _install_flickr(
        monkeypatch,
        ["new", "a", "b"],
        {
            "new": "2026-01-01 12:00:00",
            "a": "2025-01-01 12:00:00",
            "b": "2024-01-01 12:00:00",
        },
    )

    result = _reorder(_manager(tmp_path))

    assert photosets.order_calls == [("new,a,b", 120.0)]
    assert result.album_reordered is True


def test_skips_oldest_new_album_when_more_albums_follow_window(
    qapp, monkeypatch, tmp_path
) -> None:  # noqa: ARG001
    photosets = _install_flickr(
        monkeypatch,
        ["new", "a", "b", "tail"],
        {
            "new": "2023-01-01 12:00:00",
            "a": "2025-01-01 12:00:00",
            "b": "2024-01-01 12:00:00",
        },
    )

    result = _reorder(_manager(tmp_path))

    assert photosets.order_calls == []
    assert result.album_reordered is False
    assert "first 3 albums" in result.album_reorder_note
    assert result.album_reorder_backup_path == ""
    assert not (tmp_path / BACKUP_FOLDER_NAME).exists()


def test_places_oldest_new_album_last_when_list_fits_window(
    qapp, monkeypatch, tmp_path
) -> None:  # noqa: ARG001
    photosets = _install_flickr(
        monkeypatch,
        ["new", "a", "b"],
        {
            "new": "2023-01-01 12:00:00",
            "a": "2025-01-01 12:00:00",
            "b": "2024-01-01 12:00:00",
        },
    )

    result = _reorder(_manager(tmp_path))

    assert photosets.order_calls == [("a,b,new", 120.0)]
    assert result.album_reordered is True


@pytest.mark.parametrize("album_count", [20, 21])
def test_default_window_boundary_at_twenty_albums(
    qapp, monkeypatch, tmp_path, album_count
) -> None:  # noqa: ARG001
    album_ids = ["new", *(f"a{index}" for index in range(album_count - 1))]
    dates = {album_id: "2024-01-01 12:00:00" for album_id in album_ids[1:]}
    dates["new"] = "2023-01-01 12:00:00"
    photosets = _install_flickr(monkeypatch, album_ids, dates)

    result = _reorder(_manager(tmp_path, limit=20))

    assert len(photosets.read_photo_ids) == 20
    if album_count == 20:
        assert photosets.order_calls == [(",".join([*album_ids[1:], "new"]), 120.0)]
        assert result.album_reordered is True
    else:
        assert photosets.order_calls == []
        assert "first 20 albums" in result.album_reorder_note


def test_undated_album_skips_reorder_and_reports_issue(
    qapp, monkeypatch, tmp_path
) -> None:  # noqa: ARG001
    photosets = _install_flickr(
        monkeypatch,
        ["new", "a", "b"],
        {"new": "2025-01-01 12:00:00", "a": None, "b": "2024-01-01 12:00:00"},
    )

    result = _reorder(_manager(tmp_path))

    assert photosets.order_calls == []
    assert result.album_reordered is False
    assert len(result.failures) == 1
    assert result.failures[0].stage == FlickrStage.STAGE_REORDER_NEW_ALBUM.label
    assert "no valid photo taken dates: a" in result.failures[0].message


@pytest.mark.parametrize("failure_at", ["backup", "api"])
def test_backup_or_api_failure_keeps_upload_result_and_reports_issue(
    qapp, monkeypatch, tmp_path, failure_at
) -> None:  # noqa: ARG001
    photosets = _install_flickr(
        monkeypatch,
        ["new", "a"],
        {"new": "2025-01-01 12:00:00", "a": "2024-01-01 12:00:00"},
    )
    if failure_at == "backup":

        def _fail_backup(*_args, **_kwargs):
            raise OSError("backup unavailable")

        monkeypatch.setattr(
            "piqopiqo.tools.flickr_tools.upload.manager.save_album_order_backup",
            _fail_backup,
        )
    else:
        photosets.order_error = TimeoutError("order timeout")

    result = _reorder(_manager(tmp_path))

    assert result.uploaded_count == 1
    assert result.album_created is True
    assert result.album_added_count == 1
    assert result.album_reordered is False
    assert len(result.failures) == 1
    expected_message = (
        "backup unavailable" if failure_at == "backup" else "order timeout"
    )
    assert expected_message in result.failures[0].message
    assert len(photosets.order_calls) == (0 if failure_at == "backup" else 1)


@pytest.mark.parametrize(
    ("enabled", "created", "added", "expected"),
    [
        (False, True, 1, False),
        (True, False, 1, False),
        (True, True, 0, False),
        (True, True, 1, True),
    ],
)
def test_reorder_stage_runs_only_after_successful_new_album_addition(
    qapp, monkeypatch, tmp_path, enabled, created, added, expected
) -> None:  # noqa: ARG001
    manager = _manager(tmp_path, enabled=enabled)
    called = []
    monkeypatch.setattr(
        manager,
        "_run_upload_stage",
        lambda _ts, _items, _result: [{"photo_id": "p1", "file_path": "/a.jpg"}],
    )
    monkeypatch.setattr(
        manager, "_run_reset_date_stage", lambda _ts, _pairs, _result: None
    )
    monkeypatch.setattr(manager, "_run_make_public_stage", lambda _pairs, _result: None)

    def _add(_pairs, result):
        result.album_created = created
        result.album_added_count = added

    monkeypatch.setattr(manager, "_run_add_to_album_stage", _add)
    monkeypatch.setattr(
        manager,
        "_run_reorder_new_album_stage",
        lambda _result: called.append(True),
    )

    manager._run([{"file_path": "/a.jpg"}])

    assert called == ([True] if expected else [])
