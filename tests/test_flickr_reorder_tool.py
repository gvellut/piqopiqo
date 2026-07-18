"""Tests for Flickr album reorder planning and backups."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json

from piqopiqo.tools.flickr_tools.reorder import (
    BACKUP_FOLDER_NAME,
    FlickrAlbumOrderEntry,
    FlickrReorderWorker,
    build_reordered_album_ids,
    save_album_order_backup,
)


def test_reorder_sorts_prefix_and_preserves_tail_and_stable_ties() -> None:
    albums = [
        FlickrAlbumOrderEntry("a", "A"),
        FlickrAlbumOrderEntry("b", "B"),
        FlickrAlbumOrderEntry("c", "C"),
        FlickrAlbumOrderEntry("d", "D"),
    ]
    dates = {
        "a": date(2024, 1, 1),
        "b": date(2026, 1, 1),
        "c": date(2026, 1, 1),
    }
    assert build_reordered_album_ids(
        albums,
        dates,
        through_album_id="c",
    ) == ["b", "c", "a", "d"]


def test_backup_is_json_id_array_and_retains_newest(tmp_path) -> None:
    first_time = datetime(2026, 1, 1, 12, 0, 0)
    for index in range(4):
        save_album_order_backup(
            [str(index), "tail"],
            support_dir=tmp_path,
            keep=3,
            now=first_time + timedelta(seconds=index),
        )

    backups = sorted((tmp_path / BACKUP_FOLDER_NAME).glob("*.json"))
    assert len(backups) == 3
    assert json.loads(backups[-1].read_text(encoding="utf-8")) == ["3", "tail"]


def test_worker_aborts_before_order_sets_for_undated_album(
    monkeypatch, tmp_path
) -> None:
    order_calls: list[str] = []

    class _PhotoSets:
        def getList(self, **_kwargs):
            return {
                "photosets": {
                    "page": 1,
                    "pages": 1,
                    "photoset": [{"id": "a", "title": {"_content": "A"}}],
                }
            }

        def getPhotos(self, **_kwargs):
            return {
                "photoset": {
                    "page": 1,
                    "pages": 1,
                    "photo": [],
                }
            }

        def orderSets(self, photoset_ids: str, **_kwargs):
            order_calls.append(photoset_ids)

    class _Flickr:
        photosets = _PhotoSets()

    monkeypatch.setattr(
        "piqopiqo.tools.flickr_tools.reorder.create_flickr_client",
        lambda *_args, **_kwargs: _Flickr(),
    )
    monkeypatch.setattr("piqopiqo.tools.flickr_tools.reorder.API_RETRIES", 1)

    worker = FlickrReorderWorker(
        api_key="k",
        api_secret="s",
        through_album_id="",
        save_existing_order=True,
        support_dir=tmp_path,
        backup_limit=3,
    )
    results = []
    worker.signals.finished.connect(results.append)
    worker.run()

    assert order_calls == []
    assert results[0].undated_albums == ["A"]
    assert "No albums were reordered" in results[0].error_message
