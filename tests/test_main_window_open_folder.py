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
