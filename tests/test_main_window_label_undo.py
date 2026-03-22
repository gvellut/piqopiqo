from __future__ import annotations

from piqopiqo.main_window import MainWindow
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDBManager
from piqopiqo.model import (
    FilterCriteria,
    ImageItem,
    LabelUndoEntry,
    OnFullscreenExitMultipleSelected,
)
from piqopiqo.photo_model import PhotoListModel
from piqopiqo.ssf.settings_state import UserSettingKey


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


class _FakeAction:
    def __init__(self) -> None:
        self.text = "Undo label"
        self.enabled = False

    def setText(self, text: str) -> None:
        self.text = text

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


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
        self.color_swatch_updates = 0
        self.update_calls = 0

    def get_current_path(self) -> str | None:
        return self.current_path

    def get_visible_paths(self) -> list[str]:
        return list(self.loop_paths)

    def get_all_paths(self) -> list[str]:
        return list(self.all_paths)

    def get_ejected_paths(self) -> list[str]:
        return list(self.ejected_paths)

    def close(self) -> None:
        self.close_calls += 1

    def _update_color_swatch(self) -> None:
        self.color_swatch_updates += 1

    def update(self) -> None:
        self.update_calls += 1


class _FakeGrid:
    def __init__(self, owner) -> None:
        self._owner = owner
        self.items_data: list[ImageItem] = []
        self._last_selected_index = -1
        self._last_selected_path: str | None = None
        self.ensure_visible_paths: list[str] = []
        self.focus_calls = 0

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

    def refresh_item(self, _index: int) -> None:
        return

    def select_paths(
        self,
        paths: list[str],
        *,
        anchor_path: str | None = None,
    ) -> set[int]:
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

    def _set_selection_anchor(self, index: int) -> None:
        if 0 <= index < len(self.items_data):
            self._last_selected_index = index
            self._last_selected_path = self.items_data[index].path
        else:
            self._last_selected_index = -1
            self._last_selected_path = None

    def _choose_anchor_from_current_selection(self) -> int:
        if not self.items_data:
            return -1

        if self._last_selected_path is not None:
            idx = self.get_index_for_path(self._last_selected_path)
            if idx is not None and self.items_data[idx].is_selected:
                return idx

        if 0 <= self._last_selected_index < len(self.items_data):
            if self.items_data[self._last_selected_index].is_selected:
                return self._last_selected_index

        selected = [i for i, item in enumerate(self.items_data) if item.is_selected]
        return selected[-1] if selected else -1

    def _ensure_visible(self, index: int, *, navigation_activity: bool = True) -> None:
        del navigation_activity
        if 0 <= index < len(self.items_data):
            self.ensure_visible_paths.append(self.items_data[index].path)

    def setFocus(self) -> None:
        self.focus_calls += 1


class _FakeBackgroundSavePool:
    def __init__(self) -> None:
        self.workers: list[object] = []

    def start(self, worker: object) -> None:
        self.workers.append(worker)


class _FakeWindowDbManager:
    def get_db_for_image(self, _path: str) -> object:
        return object()


class _FakeStatusBar:
    def showMessage(self, _message: str, _timeout_ms: int) -> None:
        return


class _LabelUndoWindow:
    def __init__(
        self,
        photo_model: PhotoListModel,
        *,
        overlay: _FakeFullscreenOverlay | None = None,
        started_with_multi_selection: bool = False,
    ) -> None:
        self.photo_model = photo_model
        self.grid = _FakeGrid(self)
        self.grid.set_data(photo_model.photos)
        self._fullscreen_overlay = overlay
        self._fullscreen_started_with_multi_selection = (
            started_with_multi_selection
        )
        self._pending_metadata_reselection_context = None
        self._next_model_change_fast_first_paint = False
        self._last_model_change_grid_ms = None
        self._undo_label_action = _FakeAction()
        self._label_undo_entry: LabelUndoEntry | None = None
        self._label_undo_is_redo = False
        self._selection_changed_since_edit = True
        self._items_by_path = {item.path: item for item in photo_model.all_photos}
        self._background_db_save_pool = _FakeBackgroundSavePool()
        self.db_manager = _FakeWindowDbManager()
        self.status_bar = _FakeStatusBar()
        self.edit_panel = None
        self.shortcut_refreshes = 0
        self.menu_policy_enabled_states: list[bool] = []

        selected_items = photo_model.get_selected_photos()
        self._selected_paths_cache = {item.path for item in selected_items}
        self._selected_count_cache = len(selected_items)

        self.photo_model.photos_changed.connect(
            lambda: MainWindow._on_model_changed(self)
        )

    @property
    def images_data(self) -> list[ImageItem]:
        return self.photo_model.photos

    def _ensure_db_metadata_ready(self, _items: list[ImageItem]) -> bool:
        return True

    def _get_selected_items(self) -> list[ImageItem]:
        return MainWindow._get_selected_items(self)

    def _get_grid_label_undo_anchor_path(self) -> str | None:
        return MainWindow._get_grid_label_undo_anchor_path(self)

    def _should_create_new_label_undo_entry(
        self,
        items: list[ImageItem],
        *,
        origin: str,
    ) -> bool:
        return MainWindow._should_create_new_label_undo_entry(
            self,
            items,
            origin=origin,
        )

    def _record_label_undo_entry(
        self,
        items: list[ImageItem],
        previous_labels: dict[str, str | None],
        label_name: str | None,
        *,
        origin: str,
        anchor_path: str | None,
    ) -> None:
        MainWindow._record_label_undo_entry(
            self,
            items,
            previous_labels,
            label_name,
            origin=origin,
            anchor_path=anchor_path,
        )

    def _capture_metadata_reselection_context(self) -> dict | None:
        return MainWindow._capture_metadata_reselection_context(self)

    def _pick_metadata_reselection_path(
        self,
        old_photo_list_paths: list[str],
        new_photo_list_paths: list[str],
        base_path: str | None,
    ) -> str | None:
        return MainWindow._pick_metadata_reselection_path(
            old_photo_list_paths,
            new_photo_list_paths,
            base_path,
        )

    def _apply_pending_metadata_reselection(self, context: dict) -> None:
        MainWindow._apply_pending_metadata_reselection(self, context)

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

    def _apply_label_to_grid_selection(self, label_name: str | None) -> None:
        MainWindow._apply_label_to_grid_selection(self, label_name)

    def _apply_label_to_fullscreen_current(self, label_name: str | None) -> None:
        MainWindow._apply_label_to_fullscreen_current(self, label_name)

    def _apply_label_to_items(
        self,
        selected_items: list[ImageItem],
        label_name: str | None,
        *,
        record_undo: bool,
        sync_source: str,
        label_undo_origin: str | None = None,
        label_undo_anchor_path: str | None = None,
    ) -> None:
        MainWindow._apply_label_to_items(
            self,
            selected_items,
            label_name,
            record_undo=record_undo,
            sync_source=sync_source,
            label_undo_origin=label_undo_origin,
            label_undo_anchor_path=label_undo_anchor_path,
        )

    def _on_undo_redo_label(self) -> None:
        MainWindow._on_undo_redo_label(self)

    def _restore_visible_items_after_label_undo(
        self,
        entry: LabelUndoEntry,
    ) -> None:
        MainWindow._restore_visible_items_after_label_undo(self, entry)

    def _refresh_undo_label_action_enabled_for_context(self) -> None:
        MainWindow._refresh_undo_label_action_enabled_for_context(self)

    def _on_fullscreen_overlay_about_to_close(
        self,
        overlay: _FakeFullscreenOverlay,
    ) -> None:
        MainWindow._on_fullscreen_overlay_about_to_close(self, overlay)

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

    def _set_selected_cache_from_items(self, items: list[ImageItem]) -> None:
        MainWindow._set_selected_cache_from_items(self, items)

    def _reconcile_selection_and_panels(self) -> None:
        MainWindow._set_selected_cache_from_items(
            self,
            self.photo_model.get_selected_photos(),
        )

    def _update_status_bar_count(self) -> None:
        return

    def _setup_shortcuts(self) -> None:
        self.shortcut_refreshes += 1

    def _set_fullscreen_menu_action_policy(self, enabled: bool) -> None:
        self.menu_policy_enabled_states.append(enabled)


def _patch_label_undo_environment(monkeypatch) -> None:
    monkeypatch.setattr(
        "piqopiqo.main_window.get_user_setting",
        lambda key: (
            False
            if key == UserSettingKey.FILTER_IN_FULLSCREEN
            else OnFullscreenExitMultipleSelected.KEEP_SELECTION
            if key == UserSettingKey.ON_FULLSCREEN_EXIT_SELECTION_MODE
            else None
        ),
    )
    monkeypatch.setattr(
        "piqopiqo.main_window.MetadataSaveWorker",
        lambda db, path, metadata: {
            "db": db,
            "path": path,
            "metadata": metadata,
        },
    )


def test_grid_undo_restores_filtered_item_selection_and_reveal(monkeypatch):
    _patch_label_undo_environment(monkeypatch)

    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/a.jpg", label="Approved", selected=True)
    second = _item("/photos/b.jpg", label="Approved")
    model.set_photos([first, second], ["/photos"])
    model.set_filter(FilterCriteria(labels={"Approved"}))

    window = _LabelUndoWindow(model)

    window._apply_label_to_grid_selection("Rejected")

    assert [item.path for item in window.images_data] == ["/photos/b.jpg"]
    assert window._label_undo_entry is not None
    assert window._label_undo_entry.anchor_path == "/photos/a.jpg"
    assert window._label_undo_entry.origin == "grid"

    window._on_undo_redo_label()

    assert [item.path for item in window.images_data] == [
        "/photos/a.jpg",
        "/photos/b.jpg",
    ]
    assert _selected_paths(window.images_data) == ["/photos/a.jpg"]
    assert window.grid.ensure_visible_paths[-1] == "/photos/a.jpg"
    assert window._undo_label_action.text == "Redo label"


def test_fullscreen_label_edit_replaces_stale_grid_redo_state(monkeypatch):
    _patch_label_undo_environment(monkeypatch)

    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/a.jpg", label="Approved", selected=True)
    second = _item("/photos/b.jpg", label="Approved")
    model.set_photos([first, second], ["/photos"])
    model.set_filter(FilterCriteria(labels={"Approved"}))

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/b.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg"],
    )
    window = _LabelUndoWindow(model, overlay=overlay)
    window._label_undo_entry = LabelUndoEntry(
        items=[first],
        previous_labels={"/photos/a.jpg": "Approved"},
        new_labels={"/photos/a.jpg": "Rejected"},
        anchor_path="/photos/a.jpg",
        origin="grid",
    )
    window._label_undo_is_redo = True
    window._undo_label_action.setText("Redo label")
    window._selection_changed_since_edit = False

    window._apply_label_to_fullscreen_current("Rejected")

    assert window._label_undo_entry is not None
    assert [item.path for item in window._label_undo_entry.items] == ["/photos/b.jpg"]
    assert window._label_undo_entry.previous_labels == {
        "/photos/b.jpg": "Approved"
    }
    assert window._label_undo_entry.new_labels == {"/photos/b.jpg": "Rejected"}
    assert window._label_undo_entry.anchor_path == "/photos/b.jpg"
    assert window._label_undo_entry.origin == "fullscreen"
    assert window._label_undo_is_redo is False
    assert window._undo_label_action.text == "Undo label"
    assert window._undo_label_action.enabled is False


def test_fullscreen_exit_enables_undo_for_fullscreen_label_edit(monkeypatch):
    _patch_label_undo_environment(monkeypatch)

    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/a.jpg", label="Approved")
    second = _item("/photos/b.jpg", label="Approved")
    model.set_photos([first, second], ["/photos"])
    model.set_filter(FilterCriteria(labels={"Approved"}))

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/b.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg"],
    )
    window = _LabelUndoWindow(model, overlay=overlay)

    window._apply_label_to_fullscreen_current("Rejected")
    window._on_fullscreen_overlay_about_to_close(overlay)

    assert window._fullscreen_overlay is None
    assert window._undo_label_action.enabled is True
    assert window._undo_label_action.text == "Undo label"


def test_fullscreen_undo_redo_restores_filtered_photo_after_exit(monkeypatch):
    _patch_label_undo_environment(monkeypatch)

    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/a.jpg", label="Approved")
    second = _item("/photos/b.jpg", label="Approved")
    third = _item("/photos/c.jpg", label="Approved")
    model.set_photos([first, second, third], ["/photos"])
    model.set_filter(FilterCriteria(labels={"Approved"}))

    overlay = _FakeFullscreenOverlay(
        current_path="/photos/b.jpg",
        loop_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
        all_paths=["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"],
    )
    window = _LabelUndoWindow(model, overlay=overlay)

    window._apply_label_to_fullscreen_current("Rejected")

    assert [item.path for item in window.images_data] == [
        "/photos/a.jpg",
        "/photos/c.jpg",
    ]
    assert _selected_paths(window.images_data) == ["/photos/c.jpg"]

    window._on_fullscreen_overlay_about_to_close(overlay)
    assert window._undo_label_action.enabled is True

    window._on_undo_redo_label()

    assert [item.path for item in window.images_data] == [
        "/photos/a.jpg",
        "/photos/b.jpg",
        "/photos/c.jpg",
    ]
    assert _selected_paths(window.images_data) == ["/photos/b.jpg"]
    assert window.grid.ensure_visible_paths[-1] == "/photos/b.jpg"
    assert second.db_metadata[DBFields.LABEL] == "Approved"
    assert window._undo_label_action.text == "Redo label"

    window._on_undo_redo_label()

    assert [item.path for item in window.images_data] == [
        "/photos/a.jpg",
        "/photos/c.jpg",
    ]
    assert second.db_metadata[DBFields.LABEL] == "Rejected"
    assert window._undo_label_action.text == "Undo label"
