"""Tests for Flickr album reorder planning and backups."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json

from PySide6.QtWidgets import QApplication, QWidget
import pytest

from piqopiqo.ssf.settings_state import init_qsettings_store
import piqopiqo.tools.flickr_tools.reorder as reorder_module
from piqopiqo.tools.flickr_tools.reorder import (
    BACKUP_FOLDER_NAME,
    FlickrAlbumOrderEntry,
    FlickrReorderDialog,
    FlickrReorderWorker,
    build_reordered_album_ids,
    save_album_order_backup,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    init_qsettings_store(dyn=True)
    return app


def test_reorder_sorts_prefix_and_preserves_tail_and_stable_ties() -> None:
    albums = [
        FlickrAlbumOrderEntry("a", "A"),
        FlickrAlbumOrderEntry("b", "B"),
        FlickrAlbumOrderEntry("c", "C"),
        FlickrAlbumOrderEntry("d", "D"),
        FlickrAlbumOrderEntry("e", "E"),
    ]
    dates = {
        "a": date(2024, 1, 1),
        "b": date(2026, 1, 1),
        "c": date(2026, 1, 1),
    }
    assert build_reordered_album_ids(
        albums,
        dates,
        from_album_id="c",
    ) == ["b", "c", "a", "d", "e"]


def test_reorder_rejects_unknown_from_album() -> None:
    albums = [
        FlickrAlbumOrderEntry("a", "A"),
        FlickrAlbumOrderEntry("b", "B"),
    ]

    with pytest.raises(ValueError, match="missing"):
        build_reordered_album_ids(
            albums,
            {},
            from_album_id="missing",
        )


def test_empty_from_album_reorders_complete_list() -> None:
    albums = [
        FlickrAlbumOrderEntry("a", "A"),
        FlickrAlbumOrderEntry("b", "B"),
        FlickrAlbumOrderEntry("c", "C"),
    ]
    dates = {
        "a": date(2024, 1, 1),
        "b": date(2026, 1, 1),
        "c": date(2025, 1, 1),
    }

    assert build_reordered_album_ids(albums, dates) == ["b", "c", "a"]


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
        from_album_id="",
        save_existing_order=True,
        support_dir=tmp_path,
        backup_limit=3,
        apply_timeout_s=120.0,
    )
    results = []
    worker.signals.finished.connect(results.append)
    worker.run()

    assert order_calls == []
    assert results[0].undated_albums == ["A"]
    assert "No albums were reordered" in results[0].error_message


def test_worker_rejects_unknown_from_album_before_reading_photos_or_reordering(
    monkeypatch, tmp_path
) -> None:
    photo_calls: list[str] = []
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

        def getPhotos(self, photoset_id: str, **_kwargs):
            photo_calls.append(photoset_id)

        def orderSets(self, photoset_ids: str, **_kwargs):
            order_calls.append(photoset_ids)

    class _Flickr:
        photosets = _PhotoSets()

    monkeypatch.setattr(
        reorder_module,
        "create_flickr_client",
        lambda *_args, **_kwargs: _Flickr(),
    )

    worker = FlickrReorderWorker(
        api_key="k",
        api_secret="s",
        from_album_id="missing",
        save_existing_order=False,
        support_dir=tmp_path,
        backup_limit=3,
        apply_timeout_s=120.0,
    )
    results = []
    worker.signals.finished.connect(results.append)
    worker.run()

    assert photo_calls == []
    assert order_calls == []
    assert results[0].error_message == "Album missing is not in your album list."


@pytest.mark.parametrize(
    ("order_error", "expected_error"),
    [
        (None, ""),
        (TimeoutError("read timeout"), "read timeout"),
    ],
)
def test_worker_uses_indeterminate_progress_and_does_not_retry_applying(
    monkeypatch,
    tmp_path,
    order_error: Exception | None,
    expected_error: str,
) -> None:
    order_calls: list[tuple[str, float]] = []

    class _PhotoSets:
        def getList(self, **_kwargs):
            return {
                "photosets": {
                    "page": 1,
                    "pages": 1,
                    "photoset": [
                        {"id": "a", "title": {"_content": "A"}},
                        {"id": "b", "title": {"_content": "B"}},
                    ],
                }
            }

        def getPhotos(self, photoset_id: str, **_kwargs):
            date_taken = (
                "2024-01-01 12:00:00" if photoset_id == "a" else "2025-01-01 12:00:00"
            )
            return {
                "photoset": {
                    "page": 1,
                    "pages": 1,
                    "photo": [{"datetaken": date_taken}],
                }
            }

        def orderSets(self, photoset_ids: str, timeout: float, **_kwargs):
            order_calls.append((photoset_ids, timeout))
            if order_error is not None:
                raise order_error

    class _Flickr:
        photosets = _PhotoSets()

    monkeypatch.setattr(
        reorder_module,
        "create_flickr_client",
        lambda *_args, **_kwargs: _Flickr(),
    )
    monkeypatch.setattr(reorder_module, "API_RETRIES", 1)

    worker = FlickrReorderWorker(
        api_key="k",
        api_secret="s",
        from_album_id="b",
        save_existing_order=False,
        support_dir=tmp_path,
        backup_limit=3,
        apply_timeout_s=120.0,
    )
    progress_events: list[tuple[int, int, str]] = []
    results = []
    worker.signals.progress.connect(
        lambda completed, total, status: progress_events.append((
            completed,
            total,
            status,
        ))
    )
    worker.signals.finished.connect(results.append)
    worker.run()

    assert order_calls == [("b,a", 120.0)]
    assert progress_events[:2] == [
        (0, 2, "Reading A..."),
        (1, 2, "Reading B..."),
    ]
    assert progress_events[-1] == (0, 0, "Applying the new album order...")
    assert results[0].error_message == expected_error
    assert results[0].reordered is (order_error is None)


def test_dialog_requires_from_album_before_authentication(qapp, monkeypatch) -> None:
    parent = QWidget()
    dialog = FlickrReorderDialog(
        window=parent,
        api_key="k",
        api_secret="s",
        parent=parent,
    )
    warnings: list[str] = []
    authentication_calls: list[bool] = []
    monkeypatch.setattr(
        reorder_module.QMessageBox,
        "warning",
        lambda _parent, _title, text: warnings.append(text),
    )
    monkeypatch.setattr(
        reorder_module,
        "ensure_flickr_authenticated",
        lambda *_args, **_kwargs: authentication_calls.append(True),
    )

    dialog._start()

    assert dialog.from_album_edit.placeholderText() == "Flickr album ID or URL"
    assert warnings == ["Enter a Flickr album ID or URL."]
    assert authentication_calls == []


def test_dialog_allows_empty_from_album_when_runtime_setting_is_disabled(
    qapp, monkeypatch
) -> None:
    original_get_runtime_setting = reorder_module.get_runtime_setting

    def get_runtime_setting(key):
        if key is reorder_module.RuntimeSettingKey.FLICKR_REORDER_FROM_ALBUM_REQUIRED:
            return False
        return original_get_runtime_setting(key)

    monkeypatch.setattr(
        reorder_module,
        "get_runtime_setting",
        get_runtime_setting,
    )
    parent = QWidget()
    dialog = FlickrReorderDialog(
        window=parent,
        api_key="k",
        api_secret="s",
        parent=parent,
    )
    authentication_calls: list[bool] = []
    monkeypatch.setattr(
        reorder_module,
        "ensure_flickr_authenticated",
        lambda *_args, **_kwargs: authentication_calls.append(True) and False,
    )

    dialog._start()

    assert dialog.from_album_edit.placeholderText() == "Optional Flickr album ID or URL"
    assert authentication_calls == [True]


def test_dialog_checkbox_has_bottom_padding_and_applying_progress_is_busy(
    qapp,
) -> None:
    parent = QWidget()
    dialog = FlickrReorderDialog(
        window=parent,
        api_key="k",
        api_secret="s",
        parent=parent,
    )
    dialog.show()
    qapp.processEvents()

    assert (
        dialog.save_order_check.geometry().bottom()
        < dialog._content_widget.rect().bottom()
    )

    dialog.transition_to("progress")
    dialog._on_progress(1, 3, "Reading B...")
    assert dialog.progress_count_label.text() == "1/3"
    assert dialog.progress_count_label.isHidden() is False

    dialog._on_progress(0, 0, "Applying the new album order...")
    assert dialog.status_label.text() == "Applying the new album order..."
    assert dialog.progress_bar.minimum() == 0
    assert dialog.progress_bar.maximum() == 0
    assert dialog.progress_count_label.isHidden() is True
