"""Tests for fullscreen metadata sync policy."""

from __future__ import annotations

from piqopiqo.main_window import MainWindow
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDBManager
from piqopiqo.model import (
    FilterCriteria,
    ImageItem,
    OnFullscreenExitMultipleSelected,
)
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


class _FakeFullscreenOverlay:
    def __init__(
        self,
        *,
        current_path: str | None,
        loop_paths: list[str],
        all_paths: list[str],
        ejected_paths: list[str] | None = None,
    ) -> None:
        self.current_path = current_path
        self.loop_paths = list(loop_paths)
        self.all_paths = list(all_paths)
        self.ejected_paths = list(ejected_paths or [])
        self.close_calls = 0

    def get_current_path(self) -> str | None:
        return self.current_path

    def get_visible_paths(self) -> list[str]:
        return list(self.loop_paths)

    def get_all_paths(self) -> list[str]:
        return list(self.all_paths)

    def get_ejected_paths(self) -> list[str]:
        return list(self.ejected_paths)

    def eject_current_from_loop(self) -> dict[str, object] | None:
        current_path = self.current_path
        if current_path is None:
            return None

        if current_path not in self.ejected_paths:
            self.ejected_paths.append(current_path)

        current_index = self.loop_paths.index(current_path)
        self.loop_paths.pop(current_index)
        if not self.loop_paths:
            self.current_path = None
            return {"auto_close": True, "ejected_path": current_path}

        next_index = min(current_index, len(self.loop_paths) - 1)
        self.current_path = self.loop_paths[next_index]
        return {
            "auto_close": False,
            "ejected_path": current_path,
            "current_path": self.current_path,
        }

    def close(self) -> None:
        self.close_calls += 1


class _FakeGridFullscreenSync:
    def __init__(self) -> None:
        self.items_data: list[ImageItem] = []
        self.set_data_calls: list[tuple[list[ImageItem], bool]] = []
        self.anchor_indices: list[int] = []

    def set_data(self, items, *, fast_first_paint: bool = False):
        self.items_data = list(items)
        self.set_data_calls.append((list(items), fast_first_paint))

    def get_index_for_path(self, path: str) -> int | None:
        for index, item in enumerate(self.items_data):
            if item.path == path:
                return index
        return None

    def _set_selection_anchor(self, index: int) -> None:
        self.anchor_indices.append(index)


class _FullscreenSelectionWindow:
    def __init__(
        self,
        photo_model: PhotoListModel,
        overlay: _FakeFullscreenOverlay,
        *,
        started_with_multi_selection: bool,
    ) -> None:
        self.photo_model = photo_model
        self.grid = _FakeGridFullscreenSync()
        self.grid.set_data(photo_model.photos)
        self._fullscreen_overlay = overlay
        self._fullscreen_started_with_multi_selection = (
            started_with_multi_selection
        )
        self._pending_model_sync_after_fullscreen = False
        self._pending_model_sync_fields: set[str] = set()
        self._pending_metadata_reselection_context = None
        self._fullscreen_exit_snapshot_override = None
        self._next_model_change_fast_first_paint = False
        self._last_model_change_grid_ms = None
        self.execute_calls: list[tuple[set[str], str, bool]] = []
        self.selection_calls: list[tuple[list[str], str | None, str | None]] = []
        self.visible_paths: list[str] = []
        self.clear_calls = 0
        self.status_updates = 0
        self.panel_reconciles = 0
        self.photo_model.photos_changed.connect(lambda: MainWindow._on_model_changed(self))

    @property
    def images_data(self) -> list[ImageItem]:
        return self.photo_model.photos

    def _capture_metadata_reselection_context(self) -> dict | None:
        return None

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

    def _capture_fullscreen_exit_snapshot(
        self,
        overlay: _FakeFullscreenOverlay,
        *,
        current_path_override: str | None = None,
    ) -> dict:
        return MainWindow._capture_fullscreen_exit_snapshot(
            self,
            overlay,
            current_path_override=current_path_override,
        )

    def _resolve_grid_selection_for_fullscreen_snapshot(
        self,
        snapshot: dict | None,
        *,
        keep_multi_selection: bool,
    ) -> tuple[list[str], str | None]:
        return MainWindow._resolve_grid_selection_for_fullscreen_snapshot(
            self,
            snapshot,
            keep_multi_selection=keep_multi_selection,
        )

    def _pick_next_path_in_loop(
        self,
        loop_paths: list[str],
        valid_paths: set[str],
        current_path: str | None,
    ) -> str | None:
        return MainWindow._pick_next_path_in_loop(
            self,
            loop_paths,
            valid_paths,
            current_path,
        )

    def _sync_grid_selection_with_fullscreen(self) -> None:
        MainWindow._sync_grid_selection_with_fullscreen(self)

    def _restore_grid_after_fullscreen_exit(self, snapshot: dict | None) -> None:
        MainWindow._restore_grid_after_fullscreen_exit(self, snapshot)

    def _update_status_bar_count(self) -> None:
        self.status_updates += 1

    def _reconcile_selection_and_panels(self) -> None:
        self.panel_reconciles += 1

    def _ensure_grid_path_visible(self, path: str | None) -> bool:
        if path is None:
            return False
        self.visible_paths.append(path)
        return any(item.path == path for item in self.images_data)

    def _clear_grid_selection(self) -> None:
        self.clear_calls += 1
        for item in self.images_data:
            item.is_selected = False

    def select_paths_in_grid(
        self,
        paths: list[str],
        *,
        anchor_path: str | None = None,
        reveal_path: str | None = None,
    ) -> None:
        current_paths = {item.path for item in self.images_data}
        visible_paths = [path for path in paths if path in current_paths]
        selected = set(visible_paths)
        for item in self.images_data:
            item.is_selected = item.path in selected

        self.selection_calls.append((list(visible_paths), anchor_path, reveal_path))

        anchor_index = (
            self.grid.get_index_for_path(anchor_path)
            if anchor_path is not None
            else -1
        )
        if anchor_index is not None:
            self.grid._set_selection_anchor(anchor_index)
        if reveal_path is not None:
            self._ensure_grid_path_visible(reveal_path)


def _selected_paths(items: list[ImageItem]) -> list[str]:
    return [item.path for item in items if item.is_selected]


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


def test_fullscreen_index_change_uses_current_path_after_filtered_grid_shrinks():
    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/a.jpg", label="Approved")
    current = _item("/photos/c.jpg", label="Approved")
    model.set_photos([first, current], ["/photos"])

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/c.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSelectionWindow(
        model,
        overlay,
        started_with_multi_selection=False,
    )

    MainWindow._on_fullscreen_index_changed(window, 2)

    assert window.selection_calls == [
        (["/photos/c.jpg"], "/photos/c.jpg", "/photos/c.jpg")
    ]
    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]


def test_single_fullscreen_grid_selection_is_restored_before_exit_when_label_returns(
    monkeypatch,
):
    monkeypatch.setattr(
        "piqopiqo.main_window.get_user_setting",
        lambda key: False if key == UserSettingKey.FILTER_IN_FULLSCREEN else None,
    )

    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/a.jpg", label="Approved")
    current = _item("/photos/b.jpg", label="Approved")
    third = _item("/photos/c.jpg", label="Approved")
    model.set_photos([first, current, third], ["/photos"])
    model.set_filter(FilterCriteria(labels={"Approved"}))

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/b.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSelectionWindow(
        model,
        overlay,
        started_with_multi_selection=False,
    )

    current.db_metadata[DBFields.LABEL] = "Rejected"
    MainWindow.sync_model_after_metadata_update(
        window,
        {DBFields.LABEL},
        source="label_out",
        allow_fullscreen_filter=True,
    )

    assert [item.path for item in window.images_data] == [
        "/photos/a.jpg",
        "/photos/c.jpg",
    ]
    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]

    current.db_metadata[DBFields.LABEL] = "Approved"
    MainWindow.sync_model_after_metadata_update(
        window,
        {DBFields.LABEL},
        source="label_back_in",
        allow_fullscreen_filter=True,
    )

    assert [item.path for item in window.images_data] == [
        "/photos/a.jpg",
        "/photos/b.jpg",
        "/photos/c.jpg",
    ]
    assert _selected_paths(window.images_data) == ["/photos/b.jpg"]
    assert window.selection_calls[-1] == (
        ["/photos/b.jpg"],
        "/photos/b.jpg",
        "/photos/b.jpg",
    )


def test_multi_fullscreen_visible_selection_matches_exit_state_before_close(
    monkeypatch,
):
    monkeypatch.setattr(
        "piqopiqo.main_window.get_user_setting",
        lambda key: (
            False
            if key == UserSettingKey.FILTER_IN_FULLSCREEN
            else OnFullscreenExitMultipleSelected.KEEP_SELECTION
        ),
    )

    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/a.jpg", label="Approved")
    current = _item("/photos/b.jpg", label="Approved")
    third = _item("/photos/c.jpg", label="Approved")
    model.set_photos([first, current, third], ["/photos"])
    model.set_filter(FilterCriteria(labels={"Approved"}))

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/b.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSelectionWindow(
        model,
        overlay,
        started_with_multi_selection=True,
    )
    window.select_paths_in_grid(
        ["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        anchor_path="/photos/b.jpg",
        reveal_path="/photos/b.jpg",
    )
    window.selection_calls.clear()

    current.db_metadata[DBFields.LABEL] = "Rejected"
    MainWindow.sync_model_after_metadata_update(
        window,
        {DBFields.LABEL},
        source="label_out",
        allow_fullscreen_filter=True,
    )

    assert [item.path for item in window.images_data] == [
        "/photos/a.jpg",
        "/photos/c.jpg",
    ]
    assert _selected_paths(window.images_data) == [
        "/photos/a.jpg",
        "/photos/c.jpg",
    ]

    current.db_metadata[DBFields.LABEL] = "Approved"
    MainWindow.sync_model_after_metadata_update(
        window,
        {DBFields.LABEL},
        source="label_back_in",
        allow_fullscreen_filter=True,
    )

    assert [item.path for item in window.images_data] == [
        "/photos/a.jpg",
        "/photos/b.jpg",
        "/photos/c.jpg",
    ]
    assert _selected_paths(window.images_data) == [
        "/photos/a.jpg",
        "/photos/b.jpg",
        "/photos/c.jpg",
    ]

    exit_snapshot = MainWindow._capture_fullscreen_exit_snapshot(window, overlay)
    before_exit_call = window.selection_calls[-1]
    MainWindow._restore_grid_after_fullscreen_exit(window, exit_snapshot)

    assert _selected_paths(window.images_data) == [
        "/photos/a.jpg",
        "/photos/b.jpg",
        "/photos/c.jpg",
    ]
    assert window.selection_calls[-1] == before_exit_call


def test_fullscreen_eject_updates_single_selection_to_next_photo():
    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/a.jpg")
    current = _item("/photos/b.jpg")
    third = _item("/photos/c.jpg")
    model.set_photos([first, current, third], ["/photos"])

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/b.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSelectionWindow(
        model,
        overlay,
        started_with_multi_selection=False,
    )
    window.select_paths_in_grid(
        ["/photos/b.jpg"],
        anchor_path="/photos/b.jpg",
        reveal_path="/photos/b.jpg",
    )
    window.selection_calls.clear()

    MainWindow._on_fullscreen_eject_from_loop_requested(window)

    assert overlay.loop_paths == ["/photos/a.jpg", "/photos/c.jpg"]
    assert overlay.current_path == "/photos/c.jpg"
    assert overlay.ejected_paths == ["/photos/b.jpg"]
    assert overlay.close_calls == 0
    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]
    assert window.selection_calls == [
        (["/photos/c.jpg"], "/photos/c.jpg", "/photos/c.jpg")
    ]


def test_fullscreen_eject_updates_multi_selection_immediately():
    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/a.jpg")
    current = _item("/photos/b.jpg")
    third = _item("/photos/c.jpg")
    model.set_photos([first, current, third], ["/photos"])

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/b.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSelectionWindow(
        model,
        overlay,
        started_with_multi_selection=True,
    )
    window.select_paths_in_grid(
        ["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        anchor_path="/photos/b.jpg",
        reveal_path="/photos/b.jpg",
    )
    window.selection_calls.clear()

    MainWindow._on_fullscreen_eject_from_loop_requested(window)

    assert overlay.loop_paths == ["/photos/a.jpg", "/photos/c.jpg"]
    assert overlay.current_path == "/photos/c.jpg"
    assert overlay.close_calls == 0
    assert _selected_paths(window.images_data) == ["/photos/a.jpg", "/photos/c.jpg"]
    assert window.selection_calls == [
        (
            ["/photos/a.jpg", "/photos/c.jpg"],
            "/photos/c.jpg",
            "/photos/c.jpg",
        )
    ]


def test_fullscreen_eject_last_loop_photo_auto_closes_and_reuses_snapshot(
    monkeypatch,
):
    monkeypatch.setattr(
        "piqopiqo.main_window.get_user_setting",
        lambda key: (
            OnFullscreenExitMultipleSelected.KEEP_SELECTION
            if key == UserSettingKey.ON_FULLSCREEN_EXIT_SELECTION_MODE
            else False
        ),
    )

    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/a.jpg")
    current = _item("/photos/b.jpg")
    third = _item("/photos/c.jpg")
    fourth = _item("/photos/d.jpg")
    model.set_photos([first, current, third, fourth], ["/photos"])

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/b.jpg",
        loop_paths=["/photos/b.jpg"],
        all_paths=[
            "/photos/a.jpg",
            "/photos/b.jpg",
            "/photos/c.jpg",
            "/photos/d.jpg",
        ],
    )
    window = _FullscreenSelectionWindow(
        model,
        overlay,
        started_with_multi_selection=True,
    )
    window.select_paths_in_grid(
        ["/photos/b.jpg"],
        anchor_path="/photos/b.jpg",
        reveal_path="/photos/b.jpg",
    )
    window.selection_calls.clear()

    MainWindow._on_fullscreen_eject_from_loop_requested(window)

    assert overlay.loop_paths == []
    assert overlay.current_path is None
    assert overlay.close_calls == 1
    assert window._fullscreen_exit_snapshot_override == {
        "current_path": "/photos/b.jpg",
        "loop_paths": [],
        "all_paths": [
            "/photos/a.jpg",
            "/photos/b.jpg",
            "/photos/c.jpg",
            "/photos/d.jpg",
        ],
        "ejected_paths": ["/photos/b.jpg"],
        "started_with_multi_selection": True,
    }
    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]
    assert window.selection_calls == [
        (["/photos/c.jpg"], "/photos/c.jpg", "/photos/c.jpg")
    ]

    before_close_call = window.selection_calls[-1]
    MainWindow._restore_grid_after_fullscreen_exit(
        window, window._fullscreen_exit_snapshot_override
    )

    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]
    assert window.selection_calls[-1] == before_close_call


def test_fullscreen_exit_select_last_viewed_excludes_ejected_photos(monkeypatch):
    monkeypatch.setattr(
        "piqopiqo.main_window.get_user_setting",
        lambda key: (
            OnFullscreenExitMultipleSelected.SELECT_LAST_VIEWED
            if key == UserSettingKey.ON_FULLSCREEN_EXIT_SELECTION_MODE
            else False
        ),
    )

    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/a.jpg")
    ejected = _item("/photos/b.jpg")
    current = _item("/photos/c.jpg")
    model.set_photos([first, ejected, current], ["/photos"])

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/c.jpg",
        loop_paths=["/photos/a.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        ejected_paths=["/photos/b.jpg"],
    )
    window = _FullscreenSelectionWindow(
        model,
        overlay,
        started_with_multi_selection=True,
    )

    MainWindow._restore_grid_after_fullscreen_exit(
        window,
        MainWindow._capture_fullscreen_exit_snapshot(window, overlay),
    )

    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]
    assert window.selection_calls == [
        (["/photos/c.jpg"], "/photos/c.jpg", "/photos/c.jpg")
    ]
