"""Tests for Flickr Find & Replace scope and per-photo error handling."""

from __future__ import annotations

from piqopiqo.tools.edit_tools.service import FindReplaceSpec
from piqopiqo.tools.flickr_tools.find_replace import (
    FlickrFindReplaceOptions,
    FlickrFindReplaceWorker,
    slice_photo_range,
)


def test_slice_photo_range_is_inclusive_and_rejects_reversed() -> None:
    photos = [{"id": str(index)} for index in range(1, 6)]
    assert [
        photo["id"]
        for photo in slice_photo_range(
            photos,
            start_photo_id="2",
            end_photo_id="5",
            limit=2,
        )
    ] == ["2", "3"]

    try:
        slice_photo_range(photos, start_photo_id="4", end_photo_id="2")
    except ValueError as ex:
        assert "after end" in str(ex)
    else:
        raise AssertionError("Reversed Flickr range should fail")


def test_worker_continues_after_one_photo_title_failure(monkeypatch) -> None:
    title_calls: list[tuple[str, str]] = []

    class _Photosets:
        def getPhotos(self, **_kwargs):
            return {
                "photoset": {
                    "page": 1,
                    "pages": 1,
                    "photo": [
                        {"id": "1", "title": "Old one"},
                        {"id": "2", "title": "Old two"},
                    ],
                }
            }

    class _Photos:
        def setMeta(self, photo_id: str, title: str, **_kwargs):
            if photo_id == "1":
                raise RuntimeError("blocked")
            title_calls.append((photo_id, title))

    class _Flickr:
        photosets = _Photosets()
        photos = _Photos()

    monkeypatch.setattr(
        "piqopiqo.tools.flickr_tools.find_replace.create_flickr_client",
        lambda *_args, **_kwargs: _Flickr(),
    )
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_tools.find_replace.API_RETRIES",
        1,
    )

    worker = FlickrFindReplaceWorker(
        api_key="k",
        api_secret="s",
        options=FlickrFindReplaceOptions(
            source="album",
            album_id="album",
            start_photo_id="",
            end_photo_id="",
            limit=None,
            sort="date-posted-desc",
            replacement=FindReplaceSpec(
                title_pattern="Old",
                replace_title=True,
                title_replacement="New",
            ),
        ),
    )
    results = []
    worker.signals.finished.connect(results.append)
    worker.run()

    result = results[0]
    assert result.processed == 2
    assert result.failed_photo_ids == {"1"}
    assert title_calls == [("2", "New two")]
    assert result.title_changed == 1
