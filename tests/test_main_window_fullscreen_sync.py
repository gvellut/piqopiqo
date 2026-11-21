"""Tests for live fullscreen/grid synchronization."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor, QKeyEvent, QPixmap
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.fullscreen.overlay import FullscreenOverlay
from piqopiqo.main_window import MainWindow
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDBManager
from piqopiqo.model import (
    FilterCriteria,
    ImageItem,
    OnFullscreenExitMultipleSelected,
)
from piqopiqo.photo_model import PhotoListModel
from piqopiqo.shortcuts import Shortcut
from piqopiqo.ssf.settings_state import (
    UserSettingKey,
    init_qsettings_store,
    set_user_setting,
)


def _item(
    path: str,
    *,
    label: str | None = None,
    selected: bool = False,
) -> ImageItem:
    return ImageItem(
        path=path,
        name=path.split("/")[-1],
        created="2020-01-01 00:00:00",
        source_folder="/photos",
        is_selected=selected,
        db_metadata={DBFields.LABEL: label},
    )


def _selected_paths(items: list[ImageItem]) -> list[str]:
    return [item.path for item in items if item.is_selected]


class _FakeFullscreenOverlay:
    def __init__(
        self,
        *,
        current_path: str | None,
        loop_paths: list[str],
        all_paths: list[str],
        ejected_paths: list[str] | None = None,
        rebind_result: bool = True,
    ) -> None:
        self.current_path = current_path
        self.loop_paths = list(loop_paths)
        self.all_paths = list(all_paths)
        self.ejected_paths = list(ejected_paths or [])
        self.rebind_result = rebind_result
        self.close_calls = 0
        self.rebind_calls: list[tuple[list[str], str | None]] = []

    def get_current_path(self) -> str | None:
        return self.current_path

    def get_visible_paths(self) -> list[str]:
        return list(self.loop_paths)

    def get_all_paths(self) -> list[str]:
        return list(self.all_paths)

    def get_ejected_paths(self) -> list[str]:
        return list(self.ejected_paths)

    def rebind_to_paths(
        self,
        paths: list[str],
        preferred_path: str | None = None,
    ) -> bool:
        self.rebind_calls.append((list(paths), preferred_path))
        if not self.rebind_result or not paths:
            return False
        self.loop_paths = list(paths)
        if preferred_path in self.loop_paths:
            self.current_path = preferred_path
        elif self.current_path in self.loop_paths:
            pass
        else:
            self.current_path = self.loop_paths[0]
        return True

    def eject_current_from_loop(self) -> dict[str, object] | None:
        current_path = self.current_path
        if current_path is None or current_path not in self.loop_paths:
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


class _FakeGrid:
    def __init__(self, owner) -> None:
        self._owner = owner
        self.items_data: list[ImageItem] = []
        self.ensure_visible_paths: list[str] = []
        self.select_calls: list[tuple[list[str], str | None]] = []
        self.focus_calls = 0
        self._last_selected_index = -1
        self._last_selected_path: str | None = None

    def set_data(self, items, *, fast_first_paint: bool = False):
        del fast_first_paint
        previous_anchor_path = self._last_selected_path
        self.items_data = list(items)
        for index, item in enumerate(self.items_data):
            item._global_index = index

        selected = [i for i, item in enumerate(self.items_data) if item.is_selected]
        if selected and previous_anchor_path is not None:
            anchor_idx = self.get_index_for_path(previous_anchor_path)
            if anchor_idx is not None and self.items_data[anchor_idx].is_selected:
                self._set_selection_anchor(anchor_idx)
                return
        self._set_selection_anchor(selected[-1] if selected else -1)

    def get_index_for_path(self, path: str | None) -> int | None:
        if path is None:
            return None
        for index, item in enumerate(self.items_data):
            if item.path == path:
                return index
        return None

    def select_paths(
        self,
        paths: list[str],
        *,
        anchor_path: str | None = None,
    ) -> set[int]:
        self.select_calls.append((list(paths), anchor_path))
        path_set = set(paths)
        selected_indices: set[int] = set()
        for index, item in enumerate(self.items_data):
            item.is_selected = item.path in path_set
            if item.is_selected:
                selected_indices.add(index)

        anchor_index = None
        if anchor_path is not None:
            idx = self.get_index_for_path(anchor_path)
            if idx is not None and idx in selected_indices:
                anchor_index = idx
        if anchor_index is None:
            for path in reversed(paths):
                idx = self.get_index_for_path(path)
                if idx is not None and idx in selected_indices:
                    anchor_index = idx
                    break
        if anchor_index is None:
            anchor_index = max(selected_indices) if selected_indices else -1

        self._set_selection_anchor(anchor_index)
        self._owner.on_selection_changed(selected_indices)
        return selected_indices

    def refresh_item(self, _index: int) -> None:
        return

    def _ensure_visible(self, index: int, *, navigation_activity: bool = True) -> None:
        del navigation_activity
        if 0 <= index < len(self.items_data):
            self.ensure_visible_paths.append(self.items_data[index].path)

    def _set_selection_anchor(self, index: int) -> None:
        if 0 <= index < len(self.items_data):
            self._last_selected_index = index
            self._last_selected_path = self.items_data[index].path
        else:
            self._last_selected_index = -1
            self._last_selected_path = None

    def _choose_anchor_from_current_selection(self) -> int:
        if self._last_selected_path is not None:
            idx = self.get_index_for_path(self._last_selected_path)
            if idx is not None and self.items_data[idx].is_selected:
                return idx
        if 0 <= self._last_selected_index < len(self.items_data):
            if self.items_data[self._last_selected_index].is_selected:
                return self._last_selected_index
        selected = [i for i, item in enumerate(self.items_data) if item.is_selected]
        return selected[-1] if selected else -1

    def setFocus(self) -> None:
        self.focus_calls += 1


class _FullscreenSyncWindow:
    def __init__(
        self,
        photo_model: PhotoListModel,
        overlay: _FakeFullscreenOverlay | FullscreenOverlay | None,
        *,
        started_with_multi_selection: bool,
    ) -> None:
        self.photo_model = photo_model
        self.grid = _FakeGrid(self)
        self.grid.set_data(photo_model.photos)
        self._fullscreen_overlay = overlay
        self._fullscreen_started_with_multi_selection = started_with_multi_selection
        self._pending_metadata_reselection_context = None
        self._next_model_change_fast_first_paint = False
        self._last_model_change_grid_ms = None
        self._selection_changed_since_edit = True
        self.shortcut_refreshes = 0
        self.menu_policy_enabled_states: list[bool] = []
        self.undo_context_refreshes = 0

        selected_items = photo_model.get_selected_photos()
        self._selected_paths_cache = {item.path for item in selected_items}
        self._selected_count_cache = len(selected_items)

        self.photo_model.photos_changed.connect(
            lambda: MainWindow._on_model_changed(self)
        )

    @property
    def images_data(self) -> list[ImageItem]:
        return self.photo_model.photos

    def sync_model_after_metadata_update(
        self,
        changed_fields: set[str],
        source: str,
        allow_fullscreen_filter: bool = False,
    ) -> None:
        MainWindow.sync_model_after_metadata_update(
            self,
            changed_fields,
            source=source,
            allow_fullscreen_filter=allow_fullscreen_filter,
        )

    def _execute_metadata_model_sync(
        self,
        changed_fields: set[str],
        *,
        source: str,
        rebind_fullscreen_loop: bool,
        suppress_metadata_reselection: bool = False,
    ) -> None:
        MainWindow._execute_metadata_model_sync(
            self,
            changed_fields,
            source=source,
            rebind_fullscreen_loop=rebind_fullscreen_loop,
            suppress_metadata_reselection=suppress_metadata_reselection,
        )

    def _capture_metadata_reselection_context(self) -> dict | None:
        return MainWindow._capture_metadata_reselection_context(self)

    def _apply_pending_metadata_reselection(self, context: dict) -> None:
        MainWindow._apply_pending_metadata_reselection(self, context)

    def _capture_fullscreen_selection_state(
        self,
        overlay: _FakeFullscreenOverlay,
        *,
        current_path_override: str | None = None,
    ) -> dict:
        return MainWindow._capture_fullscreen_selection_state(
            self,
            overlay,
            current_path_override=current_path_override,
        )

    def _resolve_grid_selection_for_fullscreen_state(
        self,
        state: dict | None,
        *,
        keep_multi_selection: bool,
    ) -> tuple[list[str], str | None]:
        return MainWindow._resolve_grid_selection_for_fullscreen_state(
            self,
            state,
            keep_multi_selection=keep_multi_selection,
        )

    def _apply_live_grid_selection_from_fullscreen(
        self,
        state: dict | None = None,
    ) -> None:
        MainWindow._apply_live_grid_selection_from_fullscreen(self, state)

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

    def _pick_previous_path_in_list(
        self,
        ordered_paths: list[str],
        valid_paths: set[str],
        current_path: str | None,
    ) -> str | None:
        return MainWindow._pick_previous_path_in_list(
            self,
            ordered_paths,
            valid_paths,
            current_path,
        )

    def _rebind_fullscreen_loop_after_model_sync(
        self,
        old_loop_paths: list[str],
        old_current_path: str | None,
    ) -> None:
        MainWindow._rebind_fullscreen_loop_after_model_sync(
            self,
            old_loop_paths,
            old_current_path,
        )

    def _on_fullscreen_index_changed(self, new_index: int) -> None:
        MainWindow._on_fullscreen_index_changed(self, new_index)

    def _on_fullscreen_overlay_about_to_close(
        self,
        overlay: _FakeFullscreenOverlay,
    ) -> None:
        MainWindow._on_fullscreen_overlay_about_to_close(self, overlay)

    def _on_fullscreen_eject_from_loop_requested(self) -> None:
        MainWindow._on_fullscreen_eject_from_loop_requested(self)

    def _on_fullscreen_flush_loop_requested(self) -> None:
        MainWindow._on_fullscreen_flush_loop_requested(self)

    def select_paths_in_grid(
        self,
        paths: list[str],
        *,
        anchor_path: str | None = None,
        reveal_path: str | None = None,
    ) -> None:
        MainWindow.select_paths_in_grid(
            self,
            paths,
            anchor_path=anchor_path,
            reveal_path=reveal_path,
        )

    def _clear_grid_selection(self) -> None:
        MainWindow._clear_grid_selection(self)

    def _ensure_grid_path_visible(self, path: str | None) -> bool:
        return MainWindow._ensure_grid_path_visible(self, path)

    def on_selection_changed(self, selected_indices: set[int]) -> None:
        self._selection_changed_since_edit = True
        selected_items = [
            self.images_data[i]
            for i in sorted(selected_indices)
            if 0 <= i < len(self.images_data)
        ]
        MainWindow._set_selected_cache_from_items(self, selected_items)

    def _update_status_bar_count(self) -> None:
        return

    def _reconcile_selection_and_panels(self) -> None:
        MainWindow._set_selected_cache_from_items(
            self,
            self.photo_model.get_selected_photos(),
        )

    def _setup_shortcuts(self) -> None:
        self.shortcut_refreshes += 1

    def _set_fullscreen_menu_action_policy(self, enabled: bool) -> None:
        self.menu_policy_enabled_states.append(enabled)

    def _refresh_undo_label_action_enabled_for_context(self) -> None:
        self.undo_context_refreshes += 1


def _make_model(*items: ImageItem) -> PhotoListModel:
    model = PhotoListModel(MetadataDBManager())
    model.set_photos(list(items), ["/photos"])
    return model


def _patch_settings(
    monkeypatch,
    *,
    filter_in_fullscreen: bool = False,
    exit_mode: OnFullscreenExitMultipleSelected = (
        OnFullscreenExitMultipleSelected.KEEP_SELECTION
    ),
) -> None:
    def fake_get_user_setting(key):
        if key == UserSettingKey.FILTER_IN_FULLSCREEN:
            return filter_in_fullscreen
        if key == UserSettingKey.ON_FULLSCREEN_EXIT_SELECTION_MODE:
            return exit_mode
        return None

    monkeypatch.setattr(
        "piqopiqo.main_window.get_user_setting",
        fake_get_user_setting,
    )


@pytest.fixture
def make_flush_window(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setOrganizationName("PiqoPiqoTests")
    app.setApplicationName("piqopiqo-test-fullscreen-flush")
    init_qsettings_store(dyn=True)
    monkeypatch.setattr(
        "piqopiqo.fullscreen.overlay.atexit.register", lambda *_args: None
    )
    monkeypatch.setattr(FullscreenOverlay, "_update_info_panel", lambda self: None)
    pixmap = QPixmap(160, 120)
    pixmap.fill(QColor("white"))
    monkeypatch.setattr(
        FullscreenOverlay,
        "_load_fullscreen_pixmap_with_color_management",
        lambda self: pixmap,
    )
    overlays = []

    def make(model, loop_paths, current_path, *, started_with_multi_selection):
        items = list(model.photos)
        path_to_index = {item.path: index for index, item in enumerate(items)}
        overlay = FullscreenOverlay(
            items,
            [path_to_index[path] for path in loop_paths],
            path_to_index[current_path],
        )
        overlays.append(overlay)
        window = _FullscreenSyncWindow(
            model,
            overlay,
            started_with_multi_selection=started_with_multi_selection,
        )
        overlay.index_changed.connect(window._on_fullscreen_index_changed)
        overlay.about_to_close.connect(
            lambda: window._on_fullscreen_overlay_about_to_close(overlay)
        )
        overlay.flush_loop_requested.connect(window._on_fullscreen_flush_loop_requested)
        overlay.eject_from_loop_requested.connect(
            window._on_fullscreen_eject_from_loop_requested
        )
        window._apply_live_grid_selection_from_fullscreen()
        return window, overlay

    yield make

    for overlay in overlays:
        overlay.close()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_single_selection_navigation_updates_grid_selection_live(monkeypatch):
    _patch_settings(monkeypatch)

    model = _make_model(
        _item("/photos/a.jpg"),
        _item("/photos/b.jpg", selected=True),
        _item("/photos/c.jpg"),
    )
    overlay = _FakeFullscreenOverlay(
        current_path="/photos/b.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSyncWindow(
        model,
        overlay,
        started_with_multi_selection=False,
    )

    window._apply_live_grid_selection_from_fullscreen()
    assert _selected_paths(window.images_data) == ["/photos/b.jpg"]
    assert window.grid._last_selected_path == "/photos/b.jpg"

    overlay.current_path = "/photos/c.jpg"
    window._on_fullscreen_index_changed(2)

    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]
    assert window.grid._last_selected_path == "/photos/c.jpg"
    assert window.grid.ensure_visible_paths[-1] == "/photos/c.jpg"


def test_fullscreen_close_only_tears_down_without_reselecting(monkeypatch):
    _patch_settings(monkeypatch)

    model = _make_model(
        _item("/photos/a.jpg"),
        _item("/photos/b.jpg"),
        _item("/photos/c.jpg", selected=True),
    )
    overlay = _FakeFullscreenOverlay(
        current_path="/photos/c.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSyncWindow(
        model,
        overlay,
        started_with_multi_selection=False,
    )
    window._apply_live_grid_selection_from_fullscreen()
    select_call_count = len(window.grid.select_calls)

    window._on_fullscreen_overlay_about_to_close(overlay)

    assert window._fullscreen_overlay is None
    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]
    assert len(window.grid.select_calls) == select_call_count
    assert window.grid.focus_calls == 1


def test_filtered_out_current_path_moves_grid_to_next_visible_item_live(
    monkeypatch,
):
    _patch_settings(monkeypatch, filter_in_fullscreen=False)

    first = _item("/photos/a.jpg", label="Approved")
    second = _item("/photos/b.jpg", label="Approved", selected=True)
    third = _item("/photos/c.jpg", label="Approved")
    model = _make_model(first, second, third)
    model.set_filter(FilterCriteria(labels={"Approved"}))

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/b.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSyncWindow(
        model,
        overlay,
        started_with_multi_selection=False,
    )

    window._apply_live_grid_selection_from_fullscreen()
    second.db_metadata[DBFields.LABEL] = "Rejected"
    window.sync_model_after_metadata_update(
        {DBFields.LABEL},
        source="test",
        allow_fullscreen_filter=True,
    )

    assert [item.path for item in window.images_data] == [
        "/photos/a.jpg",
        "/photos/c.jpg",
    ]
    assert overlay.get_current_path() == "/photos/b.jpg"
    assert overlay.get_visible_paths() == [
        "/photos/a.jpg",
        "/photos/b.jpg",
        "/photos/c.jpg",
    ]
    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]


def test_filtered_out_last_path_moves_grid_to_previous_visible_item_live(
    monkeypatch,
):
    _patch_settings(monkeypatch, filter_in_fullscreen=False)

    first = _item("/photos/a.jpg", label="Approved")
    second = _item("/photos/b.jpg", label="Approved")
    third = _item("/photos/c.jpg", label="Approved", selected=True)
    model = _make_model(first, second, third)
    model.set_filter(FilterCriteria(labels={"Approved"}))

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/c.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSyncWindow(
        model,
        overlay,
        started_with_multi_selection=False,
    )

    window._apply_live_grid_selection_from_fullscreen()
    third.db_metadata[DBFields.LABEL] = "Rejected"
    window.sync_model_after_metadata_update(
        {DBFields.LABEL},
        source="test",
        allow_fullscreen_filter=True,
    )

    assert [item.path for item in window.images_data] == [
        "/photos/a.jpg",
        "/photos/b.jpg",
    ]
    assert overlay.get_current_path() == "/photos/c.jpg"
    assert _selected_paths(window.images_data) == ["/photos/b.jpg"]


def test_readding_filtered_current_path_reselects_it_live(monkeypatch):
    _patch_settings(monkeypatch, filter_in_fullscreen=False)

    first = _item("/photos/a.jpg", label="Approved")
    second = _item("/photos/b.jpg", label="Approved", selected=True)
    third = _item("/photos/c.jpg", label="Approved")
    model = _make_model(first, second, third)
    model.set_filter(FilterCriteria(labels={"Approved"}))

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/b.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSyncWindow(
        model,
        overlay,
        started_with_multi_selection=False,
    )

    second.db_metadata[DBFields.LABEL] = "Rejected"
    window.sync_model_after_metadata_update(
        {DBFields.LABEL},
        source="test",
        allow_fullscreen_filter=True,
    )
    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]

    second.db_metadata[DBFields.LABEL] = "Approved"
    window.sync_model_after_metadata_update(
        {DBFields.LABEL},
        source="test",
        allow_fullscreen_filter=True,
    )

    assert [item.path for item in window.images_data] == [
        "/photos/a.jpg",
        "/photos/b.jpg",
        "/photos/c.jpg",
    ]
    assert _selected_paths(window.images_data) == ["/photos/b.jpg"]


def test_filter_in_fullscreen_rebinds_loop_and_grid_live(monkeypatch):
    _patch_settings(monkeypatch, filter_in_fullscreen=True)

    first = _item("/photos/a.jpg", label="Approved")
    second = _item("/photos/b.jpg", label="Approved", selected=True)
    third = _item("/photos/c.jpg", label="Approved")
    model = _make_model(first, second, third)
    model.set_filter(FilterCriteria(labels={"Approved"}))

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/b.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSyncWindow(
        model,
        overlay,
        started_with_multi_selection=False,
    )

    second.db_metadata[DBFields.LABEL] = "Rejected"
    window.sync_model_after_metadata_update(
        {DBFields.LABEL},
        source="test",
        allow_fullscreen_filter=True,
    )

    assert overlay.rebind_calls == [
        (
            ["/photos/a.jpg", "/photos/c.jpg"],
            "/photos/c.jpg",
        )
    ]
    assert overlay.get_visible_paths() == ["/photos/a.jpg", "/photos/c.jpg"]
    assert overlay.get_current_path() == "/photos/c.jpg"
    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]


def test_multi_selection_keep_selection_tracks_surviving_loop_members_live(
    monkeypatch,
):
    _patch_settings(
        monkeypatch,
        filter_in_fullscreen=False,
        exit_mode=OnFullscreenExitMultipleSelected.KEEP_SELECTION,
    )

    first = _item("/photos/a.jpg", label="Approved")
    second = _item("/photos/b.jpg", label="Approved", selected=True)
    third = _item("/photos/c.jpg", label="Approved", selected=True)
    model = _make_model(first, second, third)
    model.set_filter(FilterCriteria(labels={"Approved"}))

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/c.jpg",
        loop_paths=["/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSyncWindow(
        model,
        overlay,
        started_with_multi_selection=True,
    )

    window._apply_live_grid_selection_from_fullscreen()
    assert _selected_paths(window.images_data) == [
        "/photos/b.jpg",
        "/photos/c.jpg",
    ]

    third.db_metadata[DBFields.LABEL] = "Rejected"
    window.sync_model_after_metadata_update(
        {DBFields.LABEL},
        source="test",
        allow_fullscreen_filter=True,
    )

    assert _selected_paths(window.images_data) == ["/photos/b.jpg"]


def test_multi_selection_keep_selection_uses_previous_survivor_without_wrap(
    monkeypatch,
):
    _patch_settings(
        monkeypatch,
        filter_in_fullscreen=False,
        exit_mode=OnFullscreenExitMultipleSelected.KEEP_SELECTION,
    )

    first = _item("/photos/a.jpg", label="Approved", selected=True)
    second = _item("/photos/b.jpg", label="Approved")
    third = _item("/photos/c.jpg", label="Approved", selected=True)
    fourth = _item("/photos/d.jpg", label="Approved", selected=True)
    model = _make_model(first, second, third, fourth)
    model.set_filter(FilterCriteria(labels={"Approved"}))

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/d.jpg",
        loop_paths=["/photos/a.jpg", "/photos/c.jpg", "/photos/d.jpg"],
        all_paths=[
            "/photos/a.jpg",
            "/photos/b.jpg",
            "/photos/c.jpg",
            "/photos/d.jpg",
        ],
    )
    window = _FullscreenSyncWindow(
        model,
        overlay,
        started_with_multi_selection=True,
    )

    window._apply_live_grid_selection_from_fullscreen()
    assert _selected_paths(window.images_data) == [
        "/photos/a.jpg",
        "/photos/c.jpg",
        "/photos/d.jpg",
    ]
    assert window.grid._last_selected_path == "/photos/d.jpg"

    fourth.db_metadata[DBFields.LABEL] = "Rejected"
    window.sync_model_after_metadata_update(
        {DBFields.LABEL},
        source="test",
        allow_fullscreen_filter=True,
    )

    assert [item.path for item in window.images_data] == [
        "/photos/a.jpg",
        "/photos/b.jpg",
        "/photos/c.jpg",
    ]
    assert overlay.get_current_path() == "/photos/d.jpg"
    assert _selected_paths(window.images_data) == [
        "/photos/a.jpg",
        "/photos/c.jpg",
    ]
    assert window.grid._last_selected_path == "/photos/c.jpg"
    assert window.grid.ensure_visible_paths[-1] == "/photos/c.jpg"


def test_multi_selection_select_last_viewed_tracks_only_current_item_live(
    monkeypatch,
):
    _patch_settings(
        monkeypatch,
        exit_mode=OnFullscreenExitMultipleSelected.SELECT_LAST_VIEWED,
    )

    first = _item("/photos/a.jpg")
    second = _item("/photos/b.jpg", selected=True)
    third = _item("/photos/c.jpg", selected=True)
    model = _make_model(first, second, third)

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/c.jpg",
        loop_paths=["/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSyncWindow(
        model,
        overlay,
        started_with_multi_selection=True,
    )

    window._apply_live_grid_selection_from_fullscreen()

    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]
    assert window.grid._last_selected_path == "/photos/c.jpg"
    assert window.grid.ensure_visible_paths[-1] == "/photos/c.jpg"


def test_multi_selection_select_last_viewed_uses_previous_survivor_without_wrap(
    monkeypatch,
):
    _patch_settings(
        monkeypatch,
        filter_in_fullscreen=False,
        exit_mode=OnFullscreenExitMultipleSelected.SELECT_LAST_VIEWED,
    )

    first = _item("/photos/a.jpg", label="Approved", selected=True)
    second = _item("/photos/b.jpg", label="Approved")
    third = _item("/photos/c.jpg", label="Approved", selected=True)
    fourth = _item("/photos/d.jpg", label="Approved", selected=True)
    model = _make_model(first, second, third, fourth)
    model.set_filter(FilterCriteria(labels={"Approved"}))

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/d.jpg",
        loop_paths=["/photos/a.jpg", "/photos/c.jpg", "/photos/d.jpg"],
        all_paths=[
            "/photos/a.jpg",
            "/photos/b.jpg",
            "/photos/c.jpg",
            "/photos/d.jpg",
        ],
    )
    window = _FullscreenSyncWindow(
        model,
        overlay,
        started_with_multi_selection=True,
    )

    window._apply_live_grid_selection_from_fullscreen()
    assert _selected_paths(window.images_data) == ["/photos/d.jpg"]
    assert window.grid._last_selected_path == "/photos/d.jpg"

    fourth.db_metadata[DBFields.LABEL] = "Rejected"
    window.sync_model_after_metadata_update(
        {DBFields.LABEL},
        source="test",
        allow_fullscreen_filter=True,
    )

    assert [item.path for item in window.images_data] == [
        "/photos/a.jpg",
        "/photos/b.jpg",
        "/photos/c.jpg",
    ]
    assert overlay.get_current_path() == "/photos/d.jpg"
    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]
    assert window.grid._last_selected_path == "/photos/c.jpg"
    assert window.grid.ensure_visible_paths[-1] == "/photos/c.jpg"


def test_eject_updates_grid_immediately_without_waiting_for_close(monkeypatch):
    _patch_settings(monkeypatch)

    model = _make_model(
        _item("/photos/a.jpg"),
        _item("/photos/b.jpg", selected=True),
        _item("/photos/c.jpg"),
    )
    overlay = _FakeFullscreenOverlay(
        current_path="/photos/b.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSyncWindow(
        model,
        overlay,
        started_with_multi_selection=False,
    )

    window._apply_live_grid_selection_from_fullscreen()
    window._on_fullscreen_eject_from_loop_requested()

    assert overlay.close_calls == 0
    assert overlay.get_visible_paths() == ["/photos/a.jpg", "/photos/c.jpg"]
    assert overlay.get_current_path() == "/photos/c.jpg"
    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]


def test_last_eject_applies_fallback_before_close_and_close_does_not_reselect(
    monkeypatch,
):
    _patch_settings(monkeypatch)

    model = _make_model(
        _item("/photos/a.jpg"),
        _item("/photos/b.jpg", selected=True),
        _item("/photos/c.jpg"),
    )
    overlay = _FakeFullscreenOverlay(
        current_path="/photos/b.jpg",
        loop_paths=["/photos/b.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _FullscreenSyncWindow(
        model,
        overlay,
        started_with_multi_selection=False,
    )

    window._apply_live_grid_selection_from_fullscreen()
    window._on_fullscreen_eject_from_loop_requested()
    select_call_count = len(window.grid.select_calls)

    assert overlay.close_calls == 1
    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]

    window._on_fullscreen_overlay_about_to_close(overlay)

    assert len(window.grid.select_calls) == select_call_count
    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]


@pytest.mark.parametrize("filter_in_fullscreen", [False, True])
@pytest.mark.parametrize("started_with_multi_selection", [False, True])
@pytest.mark.parametrize("exit_mode", list(OnFullscreenExitMultipleSelected))
@pytest.mark.parametrize(
    ("rejected_indices", "destination_index"),
    [
        ([], 2),
        ([0, 1], 2),
        ([2], 3),
        ([2, 3], 4),
        ([2, 3, 4], 1),
        ([1, 2, 3, 4], 0),
        ([0, 1, 2, 3, 4], None),
    ],
)
def test_flush_prunes_loop_and_resolves_selection(
    monkeypatch,
    make_flush_window,
    filter_in_fullscreen,
    started_with_multi_selection,
    exit_mode,
    rejected_indices,
    destination_index,
):
    _patch_settings(
        monkeypatch,
        filter_in_fullscreen=filter_in_fullscreen,
        exit_mode=exit_mode,
    )
    items = [
        _item(f"/photos/{name}.jpg", label="Review" if index % 2 else "Approved")
        for index, name in enumerate("abcde")
    ]
    loop_paths = [item.path for item in items]
    if started_with_multi_selection:
        items.append(_item("/photos/f.jpg", label="Approved"))
    model = _make_model(*items)
    model.set_filter(FilterCriteria(labels={"Review", "Approved"}))
    window, overlay = make_flush_window(
        model,
        loop_paths,
        loop_paths[2],
        started_with_multi_selection=started_with_multi_selection,
    )

    for index in rejected_indices:
        items[index].db_metadata[DBFields.LABEL] = "Rejected"
    # Ordinary metadata refreshes update the grid without automatic loop pruning.
    window.sync_model_after_metadata_update({DBFields.LABEL}, source="test")
    assert overlay.get_visible_paths() == loop_paths

    window._on_fullscreen_flush_loop_requested()

    survivors = [
        path for index, path in enumerate(loop_paths) if index not in rejected_indices
    ]
    assert overlay.get_visible_paths() == survivors
    assert set(overlay.get_ejected_paths()) == {
        loop_paths[index] for index in rejected_indices
    }
    if destination_index is not None:
        destination_path = loop_paths[destination_index]
        assert window._fullscreen_overlay is overlay
        assert overlay.get_current_path() == destination_path
        expected_selection = (
            survivors
            if started_with_multi_selection
            and exit_mode == OnFullscreenExitMultipleSelected.KEEP_SELECTION
            else [destination_path]
        )
        assert _selected_paths(window.images_data) == expected_selection
        assert window.grid._last_selected_path == destination_path
    else:
        assert window._fullscreen_overlay is None
        assert _selected_paths(window.images_data) == (
            ["/photos/f.jpg"] if started_with_multi_selection else []
        )
        if started_with_multi_selection:
            assert window.grid.ensure_visible_paths[-1] == "/photos/f.jpg"

    select_call_count = len(window.grid.select_calls)
    window._on_fullscreen_flush_loop_requested()
    assert len(window.grid.select_calls) == select_call_count


@pytest.mark.parametrize(
    ("criteria", "survivor_names"),
    [
        (FilterCriteria(folder="/photos"), "abde"),
        (FilterCriteria(labels={"Approved", "Review"}), "abc"),
        (
            FilterCriteria(
                include_no_label=True, explicit_labels={"Approved", "Review"}
            ),
            "de",
        ),
        (FilterCriteria(search_text="sea"), "bce"),
        (
            FilterCriteria(
                folder="/photos",
                labels={"Approved", "Review"},
                search_text="sea",
            ),
            "b",
        ),
    ],
)
def test_flush_uses_complete_current_grid_filter(
    monkeypatch, make_flush_window, criteria, survivor_names
):
    _patch_settings(monkeypatch)
    items = [
        _item(f"/photos/{name}.jpg", label=label)
        for name, label in zip(
            "abcde", ["Approved", "Review", "Approved", None, "Old"], strict=True
        )
    ]
    items[0].db_metadata[DBFields.TITLE] = "Mountain"
    items[1].db_metadata[DBFields.KEYWORDS] = "sea"
    items[2].db_metadata[DBFields.TITLE] = "Sea View"
    items[2].source_folder = "/other"
    items[4].db_metadata[DBFields.KEYWORDS] = "SEA"
    model = _make_model(*items)
    loop_paths = [item.path for item in items]
    window, overlay = make_flush_window(
        model, loop_paths, loop_paths[0], started_with_multi_selection=False
    )
    model.set_filter(criteria)
    metadata_before = [dict(item.db_metadata) for item in items]

    window._on_fullscreen_flush_loop_requested()

    expected_paths = [f"/photos/{name}.jpg" for name in survivor_names]
    assert overlay.get_visible_paths() == expected_paths
    assert overlay.get_current_path() == expected_paths[0]
    assert [item.path for item in window.images_data] == expected_paths
    assert [item.db_metadata for item in items] == metadata_before
    assert model._filter == model.normalize_filter_criteria(criteria)


def test_flush_does_not_restore_removed_photos_or_add_photos_outside_loop(
    monkeypatch, make_flush_window
):
    _patch_settings(monkeypatch)
    items = [_item(f"/photos/{name}.jpg", label="Approved") for name in "abcd"]
    model = _make_model(*items)
    model.set_filter(FilterCriteria(labels={"Approved"}))
    loop_paths = [item.path for item in items[:3]]
    window, overlay = make_flush_window(
        model, loop_paths, loop_paths[0], started_with_multi_selection=True
    )
    window._on_fullscreen_eject_from_loop_requested()
    items[2].db_metadata[DBFields.LABEL] = "Rejected"
    window.sync_model_after_metadata_update(
        {DBFields.LABEL}, source="test", allow_fullscreen_filter=True
    )

    window._on_fullscreen_flush_loop_requested()
    items[2].db_metadata[DBFields.LABEL] = "Approved"
    window.sync_model_after_metadata_update(
        {DBFields.LABEL}, source="test", allow_fullscreen_filter=True
    )
    window._on_fullscreen_flush_loop_requested()

    assert overlay.get_visible_paths() == [items[1].path]
    assert overlay.get_ejected_paths() == [items[0].path, items[2].path]
    assert _selected_paths(window.images_data) == [items[1].path]


@pytest.mark.parametrize("fallback_direction", ["next", "previous"])
def test_empty_flush_skips_previously_ejected_grid_photos(
    monkeypatch, make_flush_window, fallback_direction
):
    _patch_settings(monkeypatch)
    items = [_item(f"/photos/{name}.jpg", label="Approved") for name in "abcd"]
    model = _make_model(*items)
    model.set_filter(FilterCriteria(labels={"Approved"}))
    loop_paths = [items[1].path, items[2].path]
    window, overlay = make_flush_window(
        model, loop_paths, items[2].path, started_with_multi_selection=True
    )
    window._on_fullscreen_eject_from_loop_requested()
    assert overlay.get_current_path() == items[1].path
    items[1].db_metadata[DBFields.LABEL] = "Rejected"
    if fallback_direction == "previous":
        items[3].db_metadata[DBFields.LABEL] = "Rejected"
    window.sync_model_after_metadata_update({DBFields.LABEL}, source="test")

    window._on_fullscreen_flush_loop_requested()

    target = items[3].path if fallback_direction == "next" else items[0].path
    assert window._fullscreen_overlay is None
    assert overlay.get_visible_paths() == []
    assert _selected_paths(window.images_data) == [target]
    assert window.grid.ensure_visible_paths[-1] == target


def test_flush_with_no_grid_filter_leaves_loop_unchanged(
    monkeypatch, make_flush_window
):
    _patch_settings(monkeypatch)
    items = [_item(f"/photos/{name}.jpg", label="Rejected") for name in "abc"]
    model = _make_model(*items)
    loop_paths = [item.path for item in items]
    window, overlay = make_flush_window(
        model, loop_paths, loop_paths[1], started_with_multi_selection=False
    )
    select_call_count = len(window.grid.select_calls)

    window._on_fullscreen_flush_loop_requested()

    assert window._fullscreen_overlay is overlay
    assert overlay.get_visible_paths() == loop_paths
    assert overlay.get_current_path() == loop_paths[1]
    assert overlay.get_ejected_paths() == []
    assert len(window.grid.select_calls) == select_call_count


@pytest.mark.parametrize(
    ("shortcut", "key", "modifiers", "should_flush"),
    [
        ("Shift+\\", Qt.Key_Backslash, Qt.ShiftModifier, True),
        ("Shift+\\", Qt.Key_Bar, Qt.ShiftModifier, True),
        ("Ctrl+Shift+F", Qt.Key_F, Qt.ControlModifier | Qt.ShiftModifier, True),
        ("", Qt.Key_Backslash, Qt.ShiftModifier, False),
        ("Ctrl+Shift+F", Qt.Key_Backslash, Qt.ShiftModifier, False),
    ],
)
def test_fullscreen_flush_shortcut_dispatch(
    monkeypatch, make_flush_window, shortcut, key, modifiers, should_flush
):
    _patch_settings(monkeypatch)
    set_user_setting(
        UserSettingKey.SHORTCUTS,
        {Shortcut.EJECT_FROM_LOOP: "\\", Shortcut.FLUSH_LOOP: shortcut},
    )
    items = [_item(f"/photos/{name}.jpg", label="Approved") for name in "abc"]
    model = _make_model(*items)
    model.set_filter(FilterCriteria(labels={"Approved"}))
    loop_paths = [item.path for item in items]
    window, overlay = make_flush_window(
        model, loop_paths, loop_paths[1], started_with_multi_selection=False
    )
    ejected = []
    overlay.eject_from_loop_requested.connect(lambda: ejected.append(True))
    items[0].db_metadata[DBFields.LABEL] = "Rejected"
    items[2].db_metadata[DBFields.LABEL] = "Rejected"
    window.sync_model_after_metadata_update({DBFields.LABEL}, source="test")

    overlay.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, modifiers))

    assert overlay.get_visible_paths() == (
        [items[1].path] if should_flush else loop_paths
    )
    assert ejected == []
