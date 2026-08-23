"""Timeout routing tests for Flickr upload API operations."""

from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement

import piqopiqo.tools.flickr_tools.upload.media_worker as media_worker


def test_upload_uses_quick_client_and_heavy_request_timeout(monkeypatch) -> None:
    client_timeouts: list[float] = []
    upload_timeouts: list[float] = []

    class _Flickr:
        def upload(self, **kwargs):
            upload_timeouts.append(kwargs["timeout"])
            response = Element("rsp")
            SubElement(response, "ticketid").text = "ticket-1"
            return response

    def create_client(*_args, **kwargs):
        client_timeouts.append(kwargs["timeout_s"])
        return _Flickr()

    monkeypatch.setattr(media_worker, "create_flickr_client", create_client)
    monkeypatch.setattr(
        media_worker,
        "_create_temp_copy",
        lambda _path: "/tmp/piqopiqo-flickr-timeout-test.jpg",
    )
    monkeypatch.setattr(media_worker.os, "remove", lambda _path: None)
    monkeypatch.setattr(media_worker, "API_RETRIES", 1)

    result = media_worker.run_upload_task({
        "file_path": "/photos/a.jpg",
        "api_key": "k",
        "api_secret": "s",
        "token_cache_dir": "/tmp",
        "quick_timeout_s": 5.0,
        "heavy_timeout_s": 30.0,
    })

    assert result["ok"] is True
    assert client_timeouts == [5.0]
    assert upload_timeouts == [30.0]


def test_upload_fallback_calls_use_quick_and_heavy_timeouts(monkeypatch) -> None:
    search_timeouts: list[float] = []
    replace_timeouts: list[float] = []
    add_tags_timeouts: list[float] = []

    class _Photos:
        def search(self, **kwargs):
            search_timeouts.append(kwargs["timeout"])
            return {
                "photos": {
                    "page": 1,
                    "pages": 1,
                    "photo": [{"id": "p1", "datetaken": "2026-01-01", "tags": ""}],
                }
            }

        def addTags(self, **kwargs):
            add_tags_timeouts.append(kwargs["timeout"])

    class _Flickr:
        photos = _Photos()

        def replace(self, *_args, **kwargs):
            replace_timeouts.append(kwargs["timeout"])

    flickr = _Flickr()
    uploaded, not_found = media_worker._get_uploaded_photos_indirect(
        flickr,
        1,
        1_700_000_000,
        timeout_s=5.0,
    )
    monkeypatch.setattr(
        media_worker,
        "_create_temp_copy",
        lambda _path: "/tmp/piqopiqo-flickr-timeout-test.jpg",
    )
    monkeypatch.setattr(media_worker.os, "remove", lambda _path: None)
    monkeypatch.setattr(media_worker, "API_RETRIES", 1)
    failures = media_worker._reupload_photos_without_tags(
        flickr,
        [
            {
                "file_path": "/photos/a.jpg",
                "order": 0,
                "api_tags": '"tag"',
                "db_metadata": None,
            }
        ],
        uploaded,
        exiftool_path="",
        quick_timeout_s=5.0,
        heavy_timeout_s=30.0,
    )

    assert not_found is False
    assert failures == []
    assert search_timeouts == [5.0]
    assert replace_timeouts == [30.0]
    assert add_tags_timeouts == [5.0]


def test_ticket_check_uses_quick_timeout(monkeypatch) -> None:
    client_timeouts: list[float] = []
    ticket_timeouts: list[float] = []

    class _Upload:
        def checkTickets(self, **kwargs):
            ticket_timeouts.append(kwargs["timeout"])
            return {
                "uploader": {
                    "ticket": [{"id": "ticket-1", "complete": 1, "photoid": "photo-1"}]
                }
            }

    class _Photos:
        upload = _Upload()

    class _Flickr:
        photos = _Photos()

    def create_client(*_args, **kwargs):
        client_timeouts.append(kwargs["timeout_s"])
        return _Flickr()

    monkeypatch.setattr(media_worker, "create_flickr_client", create_client)
    monkeypatch.setattr(media_worker, "API_RETRIES", 1)

    result = media_worker.run_resolve_tickets_task({
        "api_key": "k",
        "api_secret": "s",
        "token_cache_dir": "/tmp",
        "quick_timeout_s": 5.0,
        "heavy_timeout_s": 30.0,
        "upload_ts": 1_700_000_000,
        "upload_entries": [
            {
                "ticket_id": "ticket-1",
                "file_path": "/photos/a.jpg",
                "order": 0,
            }
        ],
    })

    assert result["ok"] is True
    assert result["photo_ids"] == ["photo-1"]
    assert client_timeouts == [5.0]
    assert ticket_timeouts == [5.0]


def test_album_update_uses_heavy_and_very_long_timeouts(monkeypatch) -> None:
    get_photos_timeouts: list[float] = []
    edit_timeouts: list[float] = []
    reorder_timeouts: list[float] = []

    class _Photosets:
        def getPhotos(self, **kwargs):
            get_photos_timeouts.append(kwargs["timeout"])
            return {
                "photoset": {
                    "page": 1,
                    "pages": 1,
                    "photo": [
                        {
                            "id": "p1",
                            "isprimary": 1,
                            "datetaken": "2026-01-01 12:00:00",
                        },
                        {
                            "id": "p2",
                            "isprimary": 0,
                            "datetaken": "2026-01-02 12:00:00",
                        },
                    ],
                }
            }

        def editPhotos(self, **kwargs):
            edit_timeouts.append(kwargs["timeout"])

        def reorderPhotos(self, **kwargs):
            reorder_timeouts.append(kwargs["timeout"])

    class _Flickr:
        photosets = _Photosets()

    monkeypatch.setattr(media_worker, "API_RETRIES", 1)
    media_worker._add_to_album(
        _Flickr(),
        "album-1",
        ["p2"],
        heavy_timeout_s=30.0,
        very_long_timeout_s=120.0,
    )

    assert get_photos_timeouts == [30.0, 30.0]
    assert edit_timeouts == [30.0]
    assert reorder_timeouts == [120.0]
