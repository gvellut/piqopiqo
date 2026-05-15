"""Tests for Open Folder filter-reset behavior."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMessageBox
import pytest

from piqopiqo.main_window import MainWindow


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakeMainWindow:
    def __init__(self, *, root_folder: str | None = "/previous", hint: str = ""):
        self.root_folder = root_folder
        self._folder_dialog_directory_hint = hint
        self.events: list[object] = []

    @staticmethod
    def _parent_directory_for_folder_dialog(folder_path: str | None) -> str:
        return MainWindow._parent_directory_for_folder_dialog(folder_path)

    def _set_folder_dialog_directory_hint_from_folder(
        self,
        folder_path: str | None,
    ) -> None:
        MainWindow._set_folder_dialog_directory_hint_from_folder(self, folder_path)

    def _get_folder_dialog_start_directory(self) -> str:
        return MainWindow._get_folder_dialog_start_directory(self)

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


class _FakeGridSelection:
    def __init__(self, items: list[_Item]):
        self.items_data = list(items)
        self.select_calls: list[tuple[list[str], str | None]] = []
        self.ensure_calls: list[tuple[int, bool]] = []

    def select_paths(self, paths, *, anchor_path=None):
        selected = set(paths)
        for item in self.items_data:
            item.is_selected = item.path in selected
        self.select_calls.append((list(paths), anchor_path))

    def get_index_for_path(self, path: str):
        for index, item in enumerate(self.items_data):
            if item.path == path:
                return index
        return None

    def _ensure_visible(self, index: int, *, navigation_activity: bool = True) -> None:
        self.ensure_calls.append((index, navigation_activity))


class _FakePhotoModelAll:
    def __init__(self, all_photos: list[_Item]):
        self.all_photos = list(all_photos)


class _FakeFilterPanelClear:
    def __init__(self, window):
        self.window = window
        self.clear_calls = 0

    def clear_filter(self) -> None:
        self.clear_calls += 1
        all_photos = list(self.window.photo_model.all_photos)
        self.window.images_data = all_photos
        self.window.grid.items_data = all_photos


class _FakeSelectionWindow:
    def __init__(self, *, visible_items: list[_Item], all_items: list[_Item]):
        self.images_data = list(visible_items)
        self.photo_model = _FakePhotoModelAll(all_items)
        self.grid = _FakeGridSelection(visible_items)
        self.filter_panel = _FakeFilterPanelClear(self)

    def _selection_paths_include_hidden_loaded_items(self, paths: list[str]) -> bool:
        return MainWindow._selection_paths_include_hidden_loaded_items(self, paths)

    def _ensure_grid_path_visible(self, path: str | None) -> bool:
        return MainWindow._ensure_grid_path_visible(self, path)

    def select_paths_in_grid(
        self,
        paths: list[str],
        *,
        anchor_path: str | None = None,
        reveal_path: str | None = None,
        clear_filter_for_hidden: bool = False,
    ) -> None:
        MainWindow.select_paths_in_grid(
            self,
            paths,
            anchor_path=anchor_path,
            reveal_path=reveal_path,
            clear_filter_for_hidden=clear_filter_for_hidden,
        )


class _FakePhotoModelForModelChange:
    def __init__(self, photos=None):
        self.photos = photos if photos is not None else ["a", "b"]


class _FakeModelChangedWindow:
    def __init__(self):
        self.grid = _FakeGridSetData()
        self.photo_model = _FakePhotoModelForModelChange()
        self._next_model_change_fast_first_paint = True
        self._pending_metadata_reselection_context = None
        self._pending_fullscreen_grid_sync_snapshot = None
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
        self._pending_fullscreen_grid_sync_snapshot = None
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


class _FakeScrollBar:
    def __init__(self, value: int):
        self._value = value

    def value(self) -> int:
        return self._value


class _FakeSidebarToggleGrid:
    def __init__(
        self,
        paths: list[str],
        *,
        n_rows: int,
        n_cols: int,
        top_row: int,
        anchor_index: int = -1,
        ensure_row_result: bool = True,
    ):
        self.items_data = [_Item(path) for path in paths]
        self.n_rows = n_rows
        self.n_cols = n_cols
        self.scrollbar = _FakeScrollBar(top_row)
        self._anchor_index = anchor_index
        self.ensure_row_result = ensure_row_result
        self.ensure_row_calls: list[tuple[str, int, bool]] = []

    def get_viewport_visible_paths(self) -> list[str]:
        start = self.scrollbar.value() * self.n_cols
        end = min(len(self.items_data), start + (self.n_rows * self.n_cols))
        return [self.items_data[index].path for index in range(start, end)]

    def _choose_anchor_from_current_selection(self) -> int:
        return self._anchor_index

    def _ensure_path_at_viewport_row(
        self,
        path: str,
        viewport_row: int,
        *,
        navigation_activity: bool = True,
    ) -> bool:
        self.ensure_row_calls.append((path, viewport_row, navigation_activity))
        return self.ensure_row_result


class _FakeSidebarToggleViewportWindow:
    def __init__(self, grid: _FakeSidebarToggleGrid):
        self.grid = grid
        self.visible_calls: list[str | None] = []

    def _ensure_grid_path_visible(self, path: str | None) -> bool:
        self.visible_calls.append(path)
        return path is not None


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

    def _pick_grid_viewport_fallback_target(
        self,
        previous_visible_paths: list[str],
        old_photo_list_paths: list[str],
        new_photo_list_paths: list[str],
        visible_rows_by_path: dict[str, int],
    ) -> tuple[str | None, int | None]:
        return MainWindow._pick_grid_viewport_fallback_target(
            self,
            previous_visible_paths,
            old_photo_list_paths,
            new_photo_list_paths,
            visible_rows_by_path,
        )

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

    def _pick_grid_viewport_restore_target(
        self,
        snapshot: dict,
        new_photo_list_paths: list[str],
    ) -> tuple[str | None, int | None]:
        return MainWindow._pick_grid_viewport_restore_target(
            self,
            snapshot,
            new_photo_list_paths,
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

    def _restore_grid_viewport_from_snapshot(self, snapshot: dict) -> None:
        MainWindow._restore_grid_viewport_from_snapshot(self, snapshot)

    def _ensure_grid_path_visible(self, path: str | None) -> bool:
        self.visible_calls.append(path)
        return path is not None


class _FakeSortRestoreScrollBar:
    def __init__(self, maximum: int):
        self._maximum = maximum

    def maximum(self) -> int:
        return self._maximum


class _FakeSortRestoreGrid:
    def __init__(self, paths: list[str], *, maximum: int = 20):
        self.items_data = [_Item(path) for path in paths]
        self.scrollbar = _FakeSortRestoreScrollBar(maximum)
        self.scroll_calls: list[tuple[int, bool]] = []
        self.ensure_visible_calls: list[tuple[int, bool]] = []

    def _set_scrollbar_value(
        self,
        value: int,
        *,
        navigation_activity: bool = True,
    ) -> None:
        self.scroll_calls.append((value, navigation_activity))

    def get_index_for_path(self, path: str) -> int | None:
        for index, item in enumerate(self.items_data):
            if item.path == path:
                return index
        return None

    def _ensure_visible(
        self,
        index: int,
        *,
        navigation_activity: bool = True,
    ) -> None:
        self.ensure_visible_calls.append((index, navigation_activity))


class _FakeSortRestoreWindow:
    def __init__(self, paths: list[str], *, maximum: int = 20):
        self.images_data = [_Item(path) for path in paths]
        self.grid = _FakeSortRestoreGrid(paths, maximum=maximum)


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


def test_on_open_starts_at_parent_of_current_folder(monkeypatch, tmp_path):
    root = tmp_path / "current" / "folder"
    root.mkdir(parents=True)
    captured: list[str] = []
    fake_window = _FakeMainWindow(root_folder=str(root))

    def _get_existing_directory(_parent, _title, start_dir, _options):
        captured.append(start_dir)
        return ""

    monkeypatch.setattr(
        "piqopiqo.main_window.QFileDialog.getExistingDirectory",
        _get_existing_directory,
    )

    MainWindow.on_open(fake_window)

    assert captured == [str(root.parent)]


def test_on_open_uses_archive_hint_when_no_folder_loaded(monkeypatch, tmp_path):
    archive_parent = tmp_path / "archive"
    archived_folder = archive_parent / "20250502_annecy"
    archived_folder.mkdir(parents=True)
    captured: list[str] = []
    fake_window = _FakeMainWindow(root_folder=None)
    fake_window._set_folder_dialog_directory_hint_from_folder(str(archived_folder))

    def _get_existing_directory(_parent, _title, start_dir, _options):
        captured.append(start_dir)
        return ""

    monkeypatch.setattr(
        "piqopiqo.main_window.QFileDialog.getExistingDirectory",
        _get_existing_directory,
    )

    MainWindow.on_open(fake_window)

    assert captured == [str(archive_parent)]


def test_open_from_favorite_starts_in_configured_favorite_folder(monkeypatch, tmp_path):
    favorite_folder = tmp_path / "favorite"
    favorite_folder.mkdir()
    captured: list[str] = []
    fake_window = _FakeMainWindow(root_folder=None)

    monkeypatch.setattr(
        "piqopiqo.main_window.get_user_setting",
        lambda _key: str(favorite_folder),
    )

    def _get_existing_directory(_parent, _title, start_dir, _options):
        captured.append(start_dir)
        return ""

    monkeypatch.setattr(
        "piqopiqo.main_window.QFileDialog.getExistingDirectory",
        _get_existing_directory,
    )

    MainWindow._on_open_from_favorite_folder(fake_window)

    assert captured == [str(favorite_folder)]


def test_open_from_favorite_falls_back_to_default_start_dir_when_missing(
    monkeypatch, tmp_path
):
    archive_parent = tmp_path / "archive"
    archived_folder = archive_parent / "20250502_annecy"
    archived_folder.mkdir(parents=True)
    missing_favorite = tmp_path / "missing-favorite"
    captured: list[str] = []
    fake_window = _FakeMainWindow(root_folder=None)
    fake_window._set_folder_dialog_directory_hint_from_folder(str(archived_folder))

    monkeypatch.setattr(
        "piqopiqo.main_window.get_user_setting",
        lambda _key: str(missing_favorite),
    )

    def _get_existing_directory(_parent, _title, start_dir, _options):
        captured.append(start_dir)
        return ""

    monkeypatch.setattr(
        "piqopiqo.main_window.QFileDialog.getExistingDirectory",
        _get_existing_directory,
    )

    MainWindow._on_open_from_favorite_folder(fake_window)

    assert captured == [str(archive_parent)]


def test_open_from_favorite_clears_filters_before_loading_folder(monkeypatch, tmp_path):
    favorite_folder = tmp_path / "favorite"
    favorite_folder.mkdir()
    fake_window = _FakeMainWindow(root_folder=None)

    monkeypatch.setattr(
        "piqopiqo.main_window.get_user_setting",
        lambda _key: str(favorite_folder),
    )
    monkeypatch.setattr(
        "piqopiqo.main_window.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: "/new-folder",
    )

    MainWindow._on_open_from_favorite_folder(fake_window)

    assert fake_window.events == ["clear", ("load", "/new-folder", True)]


def test_open_from_favorite_does_nothing_when_dialog_cancelled(monkeypatch, tmp_path):
    favorite_folder = tmp_path / "favorite"
    favorite_folder.mkdir()
    fake_window = _FakeMainWindow(root_folder=None)

    monkeypatch.setattr(
        "piqopiqo.main_window.get_user_setting",
        lambda _key: str(favorite_folder),
    )
    monkeypatch.setattr(
        "piqopiqo.main_window.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: "",
    )

    MainWindow._on_open_from_favorite_folder(fake_window)

    assert fake_window.events == []


def test_ensure_grid_path_visible_uses_non_navigation_scroll():
    fake_window = _FakeEnsureVisibleWindow()

    assert MainWindow._ensure_grid_path_visible(fake_window, "/ok.jpg") is True
    assert fake_window.grid.calls == [(7, False)]


def test_ensure_grid_path_visible_returns_false_for_missing_path():
    fake_window = _FakeEnsureVisibleWindow()

    assert MainWindow._ensure_grid_path_visible(fake_window, "/missing.jpg") is False
    assert fake_window.grid.calls == []


def test_select_paths_in_grid_does_not_clear_filter_when_targets_visible(qapp):
    visible = _Item("/visible.jpg")
    other_visible = _Item("/other.jpg")
    fake_window = _FakeSelectionWindow(
        visible_items=[visible, other_visible],
        all_items=[visible, other_visible],
    )

    MainWindow.select_paths_in_grid(
        fake_window,
        ["/visible.jpg", "/other.jpg"],
        anchor_path="/visible.jpg",
        reveal_path="/visible.jpg",
        clear_filter_for_hidden=True,
    )
    qapp.processEvents()

    assert fake_window.filter_panel.clear_calls == 0
    assert fake_window.grid.select_calls == [
        (["/visible.jpg", "/other.jpg"], "/visible.jpg")
    ]
    assert fake_window.grid.ensure_calls == [(0, False)]


def test_select_paths_in_grid_clears_filter_before_hidden_selection(qapp):
    visible = _Item("/visible.jpg")
    hidden = _Item("/hidden.jpg")
    fake_window = _FakeSelectionWindow(
        visible_items=[visible],
        all_items=[visible, hidden],
    )

    MainWindow.select_paths_in_grid(
        fake_window,
        ["/hidden.jpg", "/visible.jpg"],
        anchor_path="/hidden.jpg",
        reveal_path="/hidden.jpg",
        clear_filter_for_hidden=True,
    )

    assert fake_window.filter_panel.clear_calls == 1
    assert fake_window.grid.select_calls == []

    qapp.processEvents()

    assert fake_window.grid.select_calls == [
        (["/hidden.jpg", "/visible.jpg"], "/hidden.jpg")
    ]
    assert fake_window.grid.ensure_calls == [(1, False)]


def test_grid_viewport_restore_prefers_visible_anchor_and_keeps_row():
    fake_window = _FakeFilterRestoreWindow(["/a.jpg", "/b.jpg", "/c.jpg"])
    snapshot = {
        "photo_list_paths": ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"],
        "visible_paths": ["/b.jpg", "/c.jpg"],
        "selected_visible_paths": ["/b.jpg", "/c.jpg"],
        "visible_rows_by_path": {"/b.jpg": 0, "/c.jpg": 1},
        "visible_anchor_path": "/c.jpg",
    }

    MainWindow._restore_grid_viewport_from_snapshot(fake_window, snapshot)

    assert fake_window.grid.calls == [("/c.jpg", 1, False)]
    assert fake_window.visible_calls == []


def test_grid_viewport_restore_uses_first_visible_selected_when_no_anchor():
    fake_window = _FakeFilterRestoreWindow(["/a.jpg", "/b.jpg", "/c.jpg"])
    snapshot = {
        "photo_list_paths": ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"],
        "visible_paths": ["/b.jpg", "/c.jpg"],
        "selected_visible_paths": ["/b.jpg", "/c.jpg"],
        "visible_rows_by_path": {"/b.jpg": 0, "/c.jpg": 1},
        "visible_anchor_path": None,
    }

    MainWindow._restore_grid_viewport_from_snapshot(fake_window, snapshot)

    assert fake_window.grid.calls == [("/b.jpg", 0, False)]
    assert fake_window.visible_calls == []


def test_grid_viewport_restore_uses_first_visible_path_when_selection_gone():
    fake_window = _FakeFilterRestoreWindow(["/a.jpg", "/c.jpg"])
    snapshot = {
        "photo_list_paths": ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"],
        "visible_paths": ["/b.jpg", "/c.jpg"],
        "selected_visible_paths": ["/b.jpg"],
        "visible_rows_by_path": {"/b.jpg": 0, "/c.jpg": 1},
        "visible_anchor_path": None,
    }

    MainWindow._restore_grid_viewport_from_snapshot(fake_window, snapshot)

    assert fake_window.grid.calls == [("/c.jpg", 1, False)]
    assert fake_window.visible_calls == []


def test_grid_viewport_restore_uses_row_aware_fallback_when_no_visible_path_survives():
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

    MainWindow._restore_grid_viewport_from_snapshot(fake_window, snapshot)

    assert fake_window.grid.calls == [("/g.jpg", 2, False)]
    assert fake_window.visible_calls == []


def test_grid_viewport_restore_falls_back_to_visibility_when_row_restore_fails():
    fake_window = _FakeFilterRestoreWindow(["/a.jpg", "/b.jpg"], ensure_result=False)
    snapshot = {
        "photo_list_paths": ["/a.jpg", "/b.jpg"],
        "visible_paths": ["/b.jpg"],
        "selected_visible_paths": ["/b.jpg"],
        "visible_rows_by_path": {"/b.jpg": 0},
        "visible_anchor_path": "/b.jpg",
    }

    MainWindow._restore_grid_viewport_from_snapshot(fake_window, snapshot)

    assert fake_window.grid.calls == [("/b.jpg", 0, False)]
    assert fake_window.visible_calls == ["/b.jpg"]


def test_sort_viewport_restore_without_selection_keeps_scroll_row():
    fake_window = _FakeSortRestoreWindow(["/a.jpg", "/b.jpg", "/c.jpg"], maximum=10)
    snapshot = {
        "photo_list_paths": ["/a.jpg", "/b.jpg", "/c.jpg"],
        "visible_paths": ["/a.jpg"],
        "selected_visible_paths": [],
        "visible_rows_by_path": {"/a.jpg": 0},
        "visible_anchor_path": None,
        "selected_anchor_path": None,
        "selected_anchor_viewport_row": None,
        "top_scroll_row": 7,
    }

    MainWindow._restore_grid_viewport_after_sort_change(fake_window, snapshot)

    assert fake_window.grid.scroll_calls == [(7, False)]
    assert fake_window.grid.ensure_visible_calls == []


def test_sort_viewport_restore_without_selection_clamps_scroll_row():
    fake_window = _FakeSortRestoreWindow(["/a.jpg", "/b.jpg", "/c.jpg"], maximum=4)
    snapshot = {
        "photo_list_paths": ["/a.jpg", "/b.jpg", "/c.jpg"],
        "visible_paths": ["/a.jpg"],
        "selected_visible_paths": [],
        "visible_rows_by_path": {"/a.jpg": 0},
        "visible_anchor_path": None,
        "selected_anchor_path": None,
        "selected_anchor_viewport_row": None,
        "top_scroll_row": 9,
    }

    MainWindow._restore_grid_viewport_after_sort_change(fake_window, snapshot)

    assert fake_window.grid.scroll_calls == [(4, False)]


def test_sort_viewport_restore_keeps_visible_selected_anchor_row():
    fake_window = _FakeFilterRestoreWindow(["/a.jpg", "/b.jpg", "/c.jpg"])
    snapshot = {
        "photo_list_paths": ["/a.jpg", "/b.jpg", "/c.jpg"],
        "visible_paths": ["/a.jpg", "/b.jpg"],
        "selected_visible_paths": ["/b.jpg"],
        "visible_rows_by_path": {"/a.jpg": 0, "/b.jpg": 1},
        "visible_anchor_path": "/b.jpg",
        "selected_anchor_path": "/b.jpg",
        "selected_anchor_viewport_row": 1,
        "top_scroll_row": 3,
    }

    MainWindow._restore_grid_viewport_after_sort_change(fake_window, snapshot)

    assert fake_window.grid.calls == [("/b.jpg", 1, False)]
    assert fake_window.visible_calls == []


def test_sort_viewport_restore_reveals_offscreen_selected_anchor():
    fake_window = _FakeFilterRestoreWindow(["/a.jpg", "/b.jpg", "/c.jpg"])
    snapshot = {
        "photo_list_paths": ["/a.jpg", "/b.jpg", "/c.jpg"],
        "visible_paths": ["/a.jpg"],
        "selected_visible_paths": [],
        "visible_rows_by_path": {"/a.jpg": 0},
        "visible_anchor_path": None,
        "selected_anchor_path": "/c.jpg",
        "selected_anchor_viewport_row": None,
        "top_scroll_row": 0,
    }

    MainWindow._restore_grid_viewport_after_sort_change(fake_window, snapshot)

    assert fake_window.grid.calls == []
    assert fake_window.visible_calls == ["/c.jpg"]


def test_sort_viewport_restore_falls_back_when_selected_anchor_disappears():
    fake_window = _FakeFilterRestoreWindow(["/a.jpg", "/b.jpg"])
    snapshot = {
        "photo_list_paths": ["/a.jpg", "/gone.jpg", "/b.jpg"],
        "visible_paths": ["/gone.jpg", "/b.jpg"],
        "selected_visible_paths": ["/gone.jpg"],
        "visible_rows_by_path": {"/gone.jpg": 0, "/b.jpg": 1},
        "visible_anchor_path": "/gone.jpg",
        "selected_anchor_path": "/gone.jpg",
        "selected_anchor_viewport_row": 0,
        "top_scroll_row": 5,
    }

    MainWindow._restore_grid_viewport_after_sort_change(fake_window, snapshot)

    assert fake_window.grid.calls == [("/b.jpg", 1, False)]
    assert fake_window.visible_calls == []


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


def test_capture_sidebar_toggle_viewport_context_keeps_first_visible():
    fake_window = _FakeSidebarToggleViewportWindow(
        _FakeSidebarToggleGrid(
            ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"],
            n_rows=2,
            n_cols=1,
            top_row=0,
            anchor_index=1,
        )
    )

    context = MainWindow._capture_sidebar_toggle_viewport_restore_context(fake_window)

    assert context == (2, "/a.jpg", 0)


def test_capture_sidebar_toggle_viewport_context_falls_back_to_first_visible():
    fake_window = _FakeSidebarToggleViewportWindow(
        _FakeSidebarToggleGrid(
            ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"],
            n_rows=2,
            n_cols=1,
            top_row=2,
        )
    )

    context = MainWindow._capture_sidebar_toggle_viewport_restore_context(fake_window)

    assert context == (2, "/c.jpg", 0)


def test_restore_grid_viewport_after_sidebar_toggle_uses_preferred_row_first():
    grid = _FakeSidebarToggleGrid(
        ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"],
        n_rows=3,
        n_cols=1,
        top_row=0,
        ensure_row_result=True,
    )
    fake_window = _FakeSidebarToggleViewportWindow(grid)

    MainWindow._restore_grid_viewport_after_sidebar_toggle(
        fake_window,
        2,
        "/c.jpg",
        0,
    )

    assert grid.ensure_row_calls == [("/c.jpg", 0, False)]
    assert fake_window.visible_calls == []


def test_restore_grid_viewport_after_sidebar_toggle_falls_back_to_visibility():
    grid = _FakeSidebarToggleGrid(
        ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"],
        n_rows=3,
        n_cols=1,
        top_row=0,
        ensure_row_result=False,
    )
    fake_window = _FakeSidebarToggleViewportWindow(grid)

    MainWindow._restore_grid_viewport_after_sidebar_toggle(
        fake_window,
        2,
        "/d.jpg",
        0,
    )

    assert grid.ensure_row_calls == [("/d.jpg", 0, False)]
    assert fake_window.visible_calls == ["/d.jpg"]
