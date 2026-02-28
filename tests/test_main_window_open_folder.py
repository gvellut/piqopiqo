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
