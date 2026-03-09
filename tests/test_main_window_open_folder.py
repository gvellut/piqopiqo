"""Tests for Open Folder filter-reset behavior."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from piqopiqo.main_window import MainWindow


class _FakeMainWindow:
    def __init__(self):
        self.root_folder = "/previous"
        self.events: list[object] = []

    def _clear_filters_before_folder_load(self) -> None:
        self.events.append("clear")

    def _load_folder(self, folder: str, *, reset_grid_to_top: bool = False) -> None:
        self.events.append(("load", folder, reset_grid_to_top))


class _FakeGridEnsureVisible:
    def __init__(self):
        self.calls: list[tuple[int, bool]] = []

    def get_index_for_path(self, path: str):
        if path == "/ok.jpg":
            return 7
        return None

    def _ensure_visible(self, index: int, *, navigation_activity: bool = True) -> None:
        self.calls.append((index, navigation_activity))


class _FakeEnsureVisibleWindow:
    def __init__(self):
        self.grid = _FakeGridEnsureVisible()


class _FakeGridSetData:
    def __init__(self):
        self.calls: list[tuple[list[object], bool]] = []
        self.items_data: list[object] = []

    def set_data(self, items, *, fast_first_paint: bool = False):
        self.items_data = list(items)
        self.calls.append((list(items), fast_first_paint))


class _FakeGridReselection(_FakeGridSetData):
    def __init__(self):
        super().__init__()
        self.select_calls: list[tuple[list[str], str | None]] = []

    def select_paths(self, paths, *, anchor_path=None):
        selected = set(paths)
        for item in self.items_data:
            item.is_selected = item.path in selected
        self.select_calls.append((list(paths), anchor_path))


class _Item:
    def __init__(self, path: str, *, selected: bool = False):
        self.path = path
        self.is_selected = selected


class _FakePhotoModelForModelChange:
    def __init__(self, photos=None):
        self.photos = photos if photos is not None else ["a", "b"]


class _FakeModelChangedWindow:
    def __init__(self):
        self.grid = _FakeGridSetData()
        self.photo_model = _FakePhotoModelForModelChange()
        self._next_model_change_fast_first_paint = True
        self._pending_metadata_reselection_context = None
        self._last_model_change_grid_ms = None
        self.events: list[str] = []

    def _update_status_bar_count(self):
        self.events.append("status")

    def _reconcile_selection_and_panels(self):
        self.events.append("panels")


class _FakeModelChangedWindowReselection:
    def __init__(self, photos: list[_Item], pending_context: dict | None):
        self.grid = _FakeGridReselection()
        self.photo_model = _FakePhotoModelForModelChange(photos)
        self._next_model_change_fast_first_paint = False
        self._pending_metadata_reselection_context = pending_context
        self._last_model_change_grid_ms = None
        self.events: list[str] = []
        self.visible_paths: list[str] = []

    @property
    def images_data(self):
        return self.photo_model.photos

    def _update_status_bar_count(self):
        self.events.append("status")

    def _reconcile_selection_and_panels(self):
        self.events.append("panels")

    def _ensure_grid_path_visible(self, path: str | None) -> bool:
        if path is None:
            return False
        self.visible_paths.append(path)
        return True

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


class _FakeSplitterCollapse:
    def __init__(self, sizes: list[int]):
        self._sizes = list(sizes)
        self.set_sizes_calls: list[list[int]] = []

    def count(self) -> int:
        return 2

    def sizes(self) -> list[int]:
        return list(self._sizes)

    def setSizes(self, sizes: list[int]) -> None:
        self._sizes = list(sizes)
        self.set_sizes_calls.append(list(sizes))


class _FakeSidebarCollapseWindow:
    def __init__(self, sizes: list[int], restore_size: int | None = None):
        self._main_splitter = _FakeSplitterCollapse(sizes)
        self._right_sidebar_collapsed = False
        self._right_sidebar_restore_size = restore_size


class _FakeGridFilterRestore:
    def __init__(self, *, ensure_result: bool = True):
        self.ensure_result = ensure_result
        self.calls: list[tuple[str, int, bool]] = []

    def _ensure_path_at_viewport_row(
        self,
        path: str,
        viewport_row: int,
        *,
        navigation_activity: bool = True,
    ) -> bool:
        self.calls.append((path, viewport_row, navigation_activity))
        return self.ensure_result


class _FakeFilterRestoreWindow:
    def __init__(self, new_photo_list_paths: list[str], *, ensure_result: bool = True):
        self.images_data = [_Item(path) for path in new_photo_list_paths]
        self.grid = _FakeGridFilterRestore(ensure_result=ensure_result)
        self.visible_calls: list[str | None] = []

    def _pick_filter_fallback_target(
        self,
        previous_visible_paths: list[str],
        old_photo_list_paths: list[str],
        new_photo_list_paths: list[str],
        visible_rows_by_path: dict[str, int],
    ) -> tuple[str | None, int | None]:
        return MainWindow._pick_filter_fallback_target(
            self,
            previous_visible_paths,
            old_photo_list_paths,
            new_photo_list_paths,
            visible_rows_by_path,
        )

    def _pick_filter_restore_target(
        self,
        snapshot: dict,
        new_photo_list_paths: list[str],
    ) -> tuple[str | None, int | None]:
        return MainWindow._pick_filter_restore_target(
            self,
            snapshot,
            new_photo_list_paths,
        )

    def _ensure_grid_path_visible(self, path: str | None) -> bool:
        self.visible_calls.append(path)
        return path is not None


class _FakeDBManagerForClearAllData:
    def __init__(self):
        self.deleted = False
        self.closed = False

    def delete_all_metadata(self) -> None:
        self.deleted = True

    def close_all(self) -> None:
        self.closed = True


class _FakePhotoModelForClearAllData:
    def __init__(self):
        self.source_folders = ["/photos/source"]


class _FakeClearAllDataWindow:
    def __init__(self):
        self.root_folder = "/photos/root"
        self.db_manager = _FakeDBManagerForClearAllData()
        self.photo_model = _FakePhotoModelForClearAllData()
        self.load_calls: list[tuple[str, bool]] = []

    def _load_folder(self, folder: str, *, reset_grid_to_top: bool = False) -> None:
        self.load_calls.append((folder, reset_grid_to_top))


def test_on_open_clears_filters_before_loading_folder(monkeypatch):
    fake_window = _FakeMainWindow()
    monkeypatch.setattr(
        "piqopiqo.main_window.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: "/new-folder",
    )

    MainWindow.on_open(fake_window)

    assert fake_window.events == ["clear", ("load", "/new-folder", True)]


def test_on_open_does_nothing_when_dialog_cancelled(monkeypatch):
    fake_window = _FakeMainWindow()
    monkeypatch.setattr(
        "piqopiqo.main_window.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: "",
    )

    MainWindow.on_open(fake_window)

    assert fake_window.events == []


def test_ensure_grid_path_visible_uses_non_navigation_scroll():
    fake_window = _FakeEnsureVisibleWindow()

    assert MainWindow._ensure_grid_path_visible(fake_window, "/ok.jpg") is True
    assert fake_window.grid.calls == [(7, False)]


def test_ensure_grid_path_visible_returns_false_for_missing_path():
    fake_window = _FakeEnsureVisibleWindow()

    assert MainWindow._ensure_grid_path_visible(fake_window, "/missing.jpg") is False
    assert fake_window.grid.calls == []


def test_filter_restore_prefers_visible_anchor_and_keeps_row():
    fake_window = _FakeFilterRestoreWindow(["/a.jpg", "/b.jpg", "/c.jpg"])
    snapshot = {
        "photo_list_paths": ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"],
        "visible_paths": ["/b.jpg", "/c.jpg"],
        "selected_visible_paths": ["/b.jpg", "/c.jpg"],
        "visible_rows_by_path": {"/b.jpg": 0, "/c.jpg": 1},
        "visible_anchor_path": "/c.jpg",
    }

    MainWindow._restore_grid_viewport_after_filter_change(fake_window, snapshot)

    assert fake_window.grid.calls == [("/c.jpg", 1, False)]
    assert fake_window.visible_calls == []


def test_filter_restore_falls_back_to_first_visible_selected_when_anchor_not_visible():
    fake_window = _FakeFilterRestoreWindow(["/a.jpg", "/b.jpg", "/c.jpg"])
    snapshot = {
        "photo_list_paths": ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"],
        "visible_paths": ["/b.jpg", "/c.jpg"],
        "selected_visible_paths": ["/b.jpg", "/c.jpg"],
        "visible_rows_by_path": {"/b.jpg": 0, "/c.jpg": 1},
        "visible_anchor_path": None,
    }

    MainWindow._restore_grid_viewport_after_filter_change(fake_window, snapshot)

    assert fake_window.grid.calls == [("/b.jpg", 0, False)]
    assert fake_window.visible_calls == []


def test_filter_restore_falls_back_to_first_visible_path_when_no_visible_selection_survives():
    fake_window = _FakeFilterRestoreWindow(["/a.jpg", "/c.jpg"])
    snapshot = {
        "photo_list_paths": ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"],
        "visible_paths": ["/b.jpg", "/c.jpg"],
        "selected_visible_paths": ["/b.jpg"],
        "visible_rows_by_path": {"/b.jpg": 0, "/c.jpg": 1},
        "visible_anchor_path": None,
    }

    MainWindow._restore_grid_viewport_after_filter_change(fake_window, snapshot)

    assert fake_window.grid.calls == [("/c.jpg", 1, False)]
    assert fake_window.visible_calls == []


def test_filter_restore_uses_row_aware_fallback_when_no_visible_path_survives():
    fake_window = _FakeFilterRestoreWindow(["/a.jpg", "/g.jpg"])
    snapshot = {
        "photo_list_paths": [
            "/a.jpg",
            "/b.jpg",
            "/c.jpg",
            "/d.jpg",
            "/e.jpg",
            "/f.jpg",
            "/g.jpg",
        ],
        "visible_paths": ["/d.jpg", "/e.jpg", "/f.jpg"],
        "selected_visible_paths": [],
        "visible_rows_by_path": {"/d.jpg": 0, "/e.jpg": 1, "/f.jpg": 2},
        "visible_anchor_path": None,
    }

    MainWindow._restore_grid_viewport_after_filter_change(fake_window, snapshot)

    assert fake_window.grid.calls == [("/g.jpg", 2, False)]
    assert fake_window.visible_calls == []


def test_filter_restore_falls_back_to_visibility_when_row_restore_fails():
    fake_window = _FakeFilterRestoreWindow(["/a.jpg", "/b.jpg"], ensure_result=False)
    snapshot = {
        "photo_list_paths": ["/a.jpg", "/b.jpg"],
        "visible_paths": ["/b.jpg"],
        "selected_visible_paths": ["/b.jpg"],
        "visible_rows_by_path": {"/b.jpg": 0},
        "visible_anchor_path": "/b.jpg",
    }

    MainWindow._restore_grid_viewport_after_filter_change(fake_window, snapshot)

    assert fake_window.grid.calls == [("/b.jpg", 0, False)]
    assert fake_window.visible_calls == ["/b.jpg"]


def test_on_model_changed_forwards_fast_first_paint_and_resets_flag():
    fake_window = _FakeModelChangedWindow()

    MainWindow._on_model_changed(fake_window)

    assert fake_window.grid.calls == [(["a", "b"], True)]
    assert fake_window._next_model_change_fast_first_paint is False
    assert isinstance(fake_window._last_model_change_grid_ms, float)
    assert fake_window.events == ["status", "panels"]


def test_pick_reselection_path_prefers_next_after_base():
    old_paths = ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"]
    new_paths = ["/a.jpg", "/d.jpg"]

    assert (
        MainWindow._pick_metadata_reselection_path(old_paths, new_paths, "/b.jpg")
        == "/d.jpg"
    )


def test_pick_reselection_path_falls_back_to_previous_when_no_next():
    old_paths = ["/a.jpg", "/b.jpg", "/c.jpg"]
    new_paths = ["/a.jpg"]

    assert (
        MainWindow._pick_metadata_reselection_path(old_paths, new_paths, "/b.jpg")
        == "/a.jpg"
    )


def test_pick_reselection_path_returns_none_when_no_visible_items():
    old_paths = ["/a.jpg", "/b.jpg"]
    new_paths: list[str] = []

    assert (
        MainWindow._pick_metadata_reselection_path(old_paths, new_paths, "/a.jpg")
        is None
    )


def test_clear_all_data_reloads_without_open_folder_top_reset(monkeypatch):
    fake_window = _FakeClearAllDataWindow()
    monkeypatch.setattr(
        "piqopiqo.main_window.QMessageBox.warning",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    cleared_folders: list[list[str]] = []
    monkeypatch.setattr(
        "piqopiqo.cache_paths.clear_thumb_cache_for_folders",
        lambda folders: cleared_folders.append(list(folders)),
    )

    MainWindow._on_clear_all_data(fake_window)

    assert fake_window.db_manager.deleted is True
    assert fake_window.db_manager.closed is True
    assert cleared_folders == [["/photos/source"]]
    assert fake_window.load_calls == [("/photos/root", False)]


def test_on_model_changed_auto_reselects_after_metadata_sync():
    photos = [_Item("/a.jpg"), _Item("/d.jpg")]
    pending_context = {
        "old_photo_list_paths": ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"],
        "selected_paths": ["/b.jpg"],
        "base_path": "/b.jpg",
    }
    fake_window = _FakeModelChangedWindowReselection(photos, pending_context)

    MainWindow._on_model_changed(fake_window)

    assert fake_window.grid.select_calls == [(["/d.jpg"], "/d.jpg")]
    assert fake_window.visible_paths == ["/d.jpg"]
    assert fake_window._pending_metadata_reselection_context is None


def test_on_model_changed_keeps_selection_when_any_selected_item_survives():
    photos = [_Item("/a.jpg", selected=True), _Item("/d.jpg", selected=False)]
    pending_context = {
        "old_photo_list_paths": ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"],
        "selected_paths": ["/a.jpg", "/b.jpg"],
        "base_path": "/b.jpg",
    }
    fake_window = _FakeModelChangedWindowReselection(photos, pending_context)

    MainWindow._on_model_changed(fake_window)

    assert fake_window.grid.select_calls == []
    assert fake_window.visible_paths == []
    assert fake_window._pending_metadata_reselection_context is None


def test_toggle_right_sidebar_collapses_and_stores_restore_size():
    fake_window = _FakeSidebarCollapseWindow([800, 200], restore_size=None)

    MainWindow._toggle_right_sidebar_collapsed(fake_window)

    assert fake_window._right_sidebar_collapsed is True
    assert fake_window._right_sidebar_restore_size == 200
    assert fake_window._main_splitter.set_sizes_calls == [[1000, 0]]


def test_toggle_right_sidebar_restores_previous_size_on_second_press():
    fake_window = _FakeSidebarCollapseWindow([1000, 0], restore_size=240)
    fake_window._right_sidebar_collapsed = True

    MainWindow._toggle_right_sidebar_collapsed(fake_window)

    assert fake_window._right_sidebar_collapsed is False
    assert fake_window._main_splitter.set_sizes_calls == [[760, 240]]


def test_toggle_right_sidebar_restores_from_manual_collapsed_state():
    fake_window = _FakeSidebarCollapseWindow([1000, 0], restore_size=180)

    MainWindow._toggle_right_sidebar_collapsed(fake_window)

    assert fake_window._right_sidebar_collapsed is False
    assert fake_window._main_splitter.set_sizes_calls == [[820, 180]]
