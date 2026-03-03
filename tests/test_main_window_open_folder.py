"""Tests for Open Folder filter-reset behavior."""

from __future__ import annotations

from piqopiqo.main_window import MainWindow


class _FakeMainWindow:
    def __init__(self):
        self.root_folder = "/previous"
        self.events: list[str] = []

    def _clear_filters_before_folder_load(self) -> None:
        self.events.append("clear")

    def _load_folder(self, folder: str) -> None:
        self.events.append(f"load:{folder}")


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


def test_on_open_clears_filters_before_loading_folder(monkeypatch):
    fake_window = _FakeMainWindow()
    monkeypatch.setattr(
        "piqopiqo.main_window.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: "/new-folder",
    )

    MainWindow.on_open(fake_window)

    assert fake_window.events == ["clear", "load:/new-folder"]


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
