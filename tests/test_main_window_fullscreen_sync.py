"""Tests for fullscreen metadata sync policy."""

from __future__ import annotations

from piqopiqo.main_window import MainWindow
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDBManager
from piqopiqo.model import FilterCriteria, ImageItem
from piqopiqo.photo_model import PhotoListModel
from piqopiqo.ssf.settings_state import UserSettingKey


def _item(path: str, *, label: str | None = None) -> ImageItem:
    return ImageItem(
        path=path,
        name=path.split("/")[-1],
        created="2020-01-01 00:00:00",
        source_folder="/photos",
        db_metadata={DBFields.LABEL: label},
    )


class _SyncPolicyWindow:
    def __init__(self) -> None:
        self._fullscreen_overlay = object()
        self._pending_model_sync_after_fullscreen = False
        self._pending_model_sync_fields: set[str] = set()
        self.execute_calls: list[tuple[set[str], str, bool]] = []

    def _execute_metadata_model_sync(
        self,
        changed_fields: set[str],
        *,
        source: str,
        rebind_fullscreen_loop: bool,
    ) -> None:
        self.execute_calls.append(
            (set(changed_fields), source, rebind_fullscreen_loop)
        )


class _SequenceWindow:
    def __init__(self, photo_model: PhotoListModel) -> None:
        self.photo_model = photo_model
        self._fullscreen_overlay = object()
        self._pending_model_sync_after_fullscreen = False
        self._pending_model_sync_fields: set[str] = set()
        self._pending_metadata_reselection_context = None
        self.execute_calls: list[tuple[set[str], str, bool]] = []

    @property
    def images_data(self) -> list[ImageItem]:
        return self.photo_model.photos

    def _capture_metadata_reselection_context(self) -> dict | None:
        return MainWindow._capture_metadata_reselection_context(self)

    def _rebind_fullscreen_loop_after_model_sync(
        self,
        old_loop_paths: list[str],
        old_current_path: str | None,
    ) -> None:
        raise AssertionError(
            "Fullscreen loop should not be rebound when filter-in-fullscreen is off"
        )

    def _execute_metadata_model_sync(
        self,
        changed_fields: set[str],
        *,
        source: str,
        rebind_fullscreen_loop: bool,
    ) -> None:
        self.execute_calls.append(
            (set(changed_fields), source, rebind_fullscreen_loop)
        )
        MainWindow._execute_metadata_model_sync(
            self,
            changed_fields,
            source=source,
            rebind_fullscreen_loop=rebind_fullscreen_loop,
        )


def test_fullscreen_label_sync_runs_immediately_when_filter_in_fullscreen_is_off(
    monkeypatch,
):
    window = _SyncPolicyWindow()
    monkeypatch.setattr(
        "piqopiqo.main_window.get_user_setting",
        lambda key: False if key == UserSettingKey.FILTER_IN_FULLSCREEN else None,
    )

    MainWindow.sync_model_after_metadata_update(
        window,
        {DBFields.LABEL},
        source="test_label_fullscreen",
        allow_fullscreen_filter=True,
    )

    assert window.execute_calls == [
        ({DBFields.LABEL}, "test_label_fullscreen", False)
    ]
    assert window._pending_model_sync_after_fullscreen is False
    assert window._pending_model_sync_fields == set()


def test_fullscreen_label_sync_rebinds_loop_when_filter_in_fullscreen_is_on(
    monkeypatch,
):
    window = _SyncPolicyWindow()
    monkeypatch.setattr(
        "piqopiqo.main_window.get_user_setting",
        lambda key: True if key == UserSettingKey.FILTER_IN_FULLSCREEN else None,
    )

    MainWindow.sync_model_after_metadata_update(
        window,
        {DBFields.LABEL},
        source="test_label_fullscreen",
        allow_fullscreen_filter=True,
    )

    assert window.execute_calls == [
        ({DBFields.LABEL}, "test_label_fullscreen", True)
    ]
    assert window._pending_model_sync_after_fullscreen is False
    assert window._pending_model_sync_fields == set()


def test_fullscreen_non_label_sync_still_defers_until_exit(monkeypatch):
    window = _SyncPolicyWindow()
    monkeypatch.setattr(
        "piqopiqo.main_window.get_user_setting",
        lambda key: False if key == UserSettingKey.FILTER_IN_FULLSCREEN else None,
    )

    MainWindow.sync_model_after_metadata_update(
        window,
        {DBFields.TITLE},
        source="test_title_fullscreen",
        allow_fullscreen_filter=False,
    )

    assert window.execute_calls == []
    assert window._pending_model_sync_after_fullscreen is True
    assert window._pending_model_sync_fields == {DBFields.TITLE}


def test_fullscreen_label_out_then_back_in_updates_grid_without_deferring(
    monkeypatch,
):
    monkeypatch.setattr(
        "piqopiqo.main_window.get_user_setting",
        lambda key: False if key == UserSettingKey.FILTER_IN_FULLSCREEN else None,
    )

    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/a.jpg", label="Approved")
    second = _item("/photos/b.jpg", label="Rejected")
    model.set_photos([first, second], ["/photos"])
    model.set_filter(FilterCriteria(labels={"Approved"}))

    window = _SequenceWindow(model)

    assert [item.path for item in window.images_data] == ["/photos/a.jpg"]

    first.db_metadata[DBFields.LABEL] = "Rejected"
    MainWindow.sync_model_after_metadata_update(
        window,
        {DBFields.LABEL},
        source="label_out",
        allow_fullscreen_filter=True,
    )

    assert [item.path for item in window.images_data] == []
    assert window.execute_calls[-1] == ({DBFields.LABEL}, "label_out", False)
    assert window._pending_model_sync_after_fullscreen is False
    assert window._pending_model_sync_fields == set()

    first.db_metadata[DBFields.LABEL] = "Approved"
    MainWindow.sync_model_after_metadata_update(
        window,
        {DBFields.LABEL},
        source="label_back_in",
        allow_fullscreen_filter=True,
    )

    assert [item.path for item in window.images_data] == ["/photos/a.jpg"]
    assert window.execute_calls[-1] == ({DBFields.LABEL}, "label_back_in", False)
    assert window._pending_model_sync_after_fullscreen is False
    assert window._pending_model_sync_fields == set()
