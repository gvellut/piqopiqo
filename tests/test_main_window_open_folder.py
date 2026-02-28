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

    def set_data(self, items, *, fast_first_paint: bool = False):
        self.calls.append((list(items), fast_first_paint))


class _FakePhotoModelForModelChange:
    def __init__(self):
        self.photos = ["a", "b"]


class _FakeModelChangedWindow:
    def __init__(self):
        self.grid = _FakeGridSetData()
        self.photo_model = _FakePhotoModelForModelChange()
        self._next_model_change_fast_first_paint = True
        self._last_model_change_grid_ms = None
        self.events: list[str] = []

    def _update_status_bar_count(self):
        self.events.append("status")

    def _reconcile_selection_and_panels(self):
        self.events.append("panels")


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
