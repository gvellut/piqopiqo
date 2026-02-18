"""Tests for Flickr album helper logic."""

from __future__ import annotations

import pytest

from piqopiqo.flickr_upload.albums import (
    FlickrAlbumPlan,
    extract_album_id,
    fetch_album_info,
    find_album_by_exact_title,
    resolve_album_plan,
)


def test_extract_album_id_from_numeric() -> None:
    assert extract_album_id("72177720318026202") == "72177720318026202"


def test_extract_album_id_from_url() -> None:
    assert (
        extract_album_id("https://www.flickr.com/photos/o_0/albums/72177720318026202")
        == "72177720318026202"
    )


def test_fetch_album_info_parses_response(monkeypatch) -> None:
    class _FakeFlickr:
        def photosets_get_info(self):
            return None

        class photosets:
            @staticmethod
            def getInfo(photoset_id: str, timeout: int):  # noqa: ARG004
                assert photoset_id == "721"
                return {
                    "photoset": {
                        "id": "721",
                        "owner": "22539273@N00",
                        "title": {"_content": "Trip"},
                    }
                }

    monkeypatch.setattr("piqopiqo.flickr_upload.albums.API_RETRIES", 1)
    info = fetch_album_info(_FakeFlickr(), "721")
    assert info.album_id == "721"
    assert info.title == "Trip"
    assert info.user_nsid == "22539273@N00"
    assert info.url.endswith("/22539273@N00/albums/721")


def test_fetch_album_info_not_found_raises(monkeypatch) -> None:
    class _FakeFlickr:
        class photosets:
            @staticmethod
            def getInfo(photoset_id: str, timeout: int):  # noqa: ARG004
                raise RuntimeError("not found")

    monkeypatch.setattr("piqopiqo.flickr_upload.albums.API_RETRIES", 1)
    with pytest.raises(RuntimeError):
        fetch_album_info(_FakeFlickr(), "721")


def test_find_album_by_exact_title_first_page_match(monkeypatch) -> None:
    class _FakeFlickr:
        class photosets:
            @staticmethod
            def getList(per_page: int, page: int, timeout: int):  # noqa: ARG004
                assert per_page == 100
                assert page == 1
                return {
                    "photosets": {
                        "owner": "22539273@N00",
                        "photoset": [
                            {"id": "11", "title": {"_content": "A"}},
                            {"id": "22", "title": {"_content": "Trip"}},
                        ],
                    }
                }

    monkeypatch.setattr("piqopiqo.flickr_upload.albums.API_RETRIES", 1)
    info = find_album_by_exact_title(_FakeFlickr(), "Trip")
    assert info is not None
    assert info.album_id == "22"
    assert info.title == "Trip"


def test_resolve_album_plan_title_miss_creates_album(monkeypatch) -> None:
    class _FakeFlickr:
        class photosets:
            @staticmethod
            def getList(per_page: int, page: int, timeout: int):  # noqa: ARG004
                return {"photosets": {"owner": "x", "photoset": []}}

    monkeypatch.setattr("piqopiqo.flickr_upload.albums.API_RETRIES", 1)
    plan = resolve_album_plan(_FakeFlickr(), "New Album")
    assert plan.is_create is True
    assert plan.album_title == "New Album"
    assert plan.album_id == ""


def test_resolve_album_plan_uses_cached_existing_plan(monkeypatch) -> None:  # noqa: ARG001
    cached = FlickrAlbumPlan(
        raw_text="72177720318026202",
        album_id="72177720318026202",
        album_title="Existing",
        user_nsid="22539273@N00",
        album_url="https://flickr.com/photos/22539273@N00/albums/72177720318026202",
        is_create=False,
    )

    class _FakeFlickr:
        class photosets:
            @staticmethod
            def getInfo(photoset_id: str, timeout: int):  # noqa: ARG004
                raise AssertionError("Should not call API when cached plan is reused")

    plan = resolve_album_plan(
        _FakeFlickr(),
        "72177720318026202",
        cached_plan=cached,
    )
    assert plan == cached
