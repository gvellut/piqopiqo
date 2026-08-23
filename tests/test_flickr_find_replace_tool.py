"""Tests for Flickr Find & Replace scope and per-photo error handling."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QTextEdit, QWidget
import pytest

from piqopiqo.tools.edit_tools.service import FindReplaceSpec
from piqopiqo.tools.flickr_tools.find_replace import (
    NO_TITLE_TEXT,
    FlickrFindReplaceDialog,
    FlickrFindReplaceOptions,
    FlickrFindReplaceResult,
    FlickrFindReplaceWorker,
    slice_photo_range,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def flickr_dialog(qapp):  # noqa: ARG001
    window = QWidget()
    dialog = FlickrFindReplaceDialog(
        window=window,
        api_key="key",
        api_secret="secret",
    )
    yield dialog
    dialog.close()
    window.close()


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
    timeout_calls: list[float] = []
    progress_updates: list[tuple[int, int, str, str]] = []

    class _Photosets:
        def getPhotos(self, **kwargs):
            timeout_calls.append(kwargs["timeout"])
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
        def setMeta(self, photo_id: str, title: str, **kwargs):
            timeout_calls.append(kwargs["timeout"])
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
        quick_timeout_s=5.0,
    )
    results = []
    worker.signals.progress.connect(
        lambda completed, total, photo_id, title: progress_updates.append((
            completed,
            total,
            photo_id,
            title,
        ))
    )
    worker.signals.finished.connect(results.append)
    worker.run()

    result = results[0]
    assert result.processed == 2
    assert result.failed_photo_ids == {"1"}
    assert title_calls == [("2", "New two")]
    assert timeout_calls == [5.0, 5.0, 5.0]
    assert result.title_changed == 1
    assert progress_updates == [
        (0, 2, "1", "Old one"),
        (1, 2, "2", "Old two"),
    ]


def test_result_summary_is_read_only_and_uses_one_value_per_line(
    flickr_dialog,
) -> None:
    flickr_dialog._result = FlickrFindReplaceResult(
        retrieved=12,
        in_scope=11,
        processed=10,
        eligible=9,
        title_changed=8,
        tags_removed=7,
        tags_added=6,
        photos_changed=5,
        unchanged=4,
        cancelled=True,
        error_message="Connection failed",
        failed_photo_ids={"1", "2", "3"},
    )

    flickr_dialog.transition_to("result")
    summary = flickr_dialog.findChild(QTextEdit, "flickrFindReplaceSummaryText")

    assert summary is not None
    assert summary.isReadOnly() is True
    assert summary.lineWrapMode() == QTextEdit.LineWrapMode.NoWrap
    assert summary.toPlainText().splitlines() == [
        "Canceled.",
        "Retrieved photos: 12",
        "Photos in exact requested range: 11",
        "Processed: 10",
        "Eligible: 9",
        "Changed photos: 5",
        "Titles changed: 8",
        "Tags removed: 7",
        "Tags added: 6",
        "Unchanged: 4",
        "Failed photos: 3",
        "Error: Connection failed",
    ]


def test_progress_uses_fixed_two_line_status_with_elided_title(
    qapp,
    flickr_dialog,
) -> None:
    flickr_dialog.transition_to("progress")
    flickr_dialog.show()
    qapp.processEvents()

    flickr_dialog._on_progress(0, 2, "123", "Short title")
    qapp.processEvents()
    short_title_height = flickr_dialog.height()

    assert flickr_dialog.status_label.text() == "Photo 123"
    assert flickr_dialog.progress_title_label.full_text == "Short title"

    flickr_dialog._on_progress(1, 2, "456", "")
    qapp.processEvents()

    assert flickr_dialog.status_label.text() == "Photo 456"
    assert flickr_dialog.progress_title_label.full_text == NO_TITLE_TEXT

    long_title = ("A very long Flickr photo title " * 30) + "line one\nline two"
    flickr_dialog._on_progress(1, 2, "789", long_title)
    qapp.processEvents()

    assert flickr_dialog.status_label.text() == "Photo 789"
    assert "\n" not in flickr_dialog.progress_title_label.full_text
    assert flickr_dialog.progress_title_label.text().endswith("…")
    assert flickr_dialog.height() == short_title_height
