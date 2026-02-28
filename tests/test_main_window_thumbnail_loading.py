"""Tests for MainWindow thumbnail-ready cache invalidation behavior."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.main_window import MainWindow
from piqopiqo.model import ImageItem
from piqopiqo.ssf.settings_state import RuntimeSettingKey, init_qsettings_store


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-thumb-ready-{uuid.uuid4().hex}")
    return app


def _pixmap() -> QPixmap:
    return QPixmap(4, 4)


def _item(
    path: str,
    *,
    state: int,
    has_embedded: bool,
    has_hq: bool,
    display_source: str | None,
) -> ImageItem:
    item = ImageItem(
        path=path,
        name=path.split("/")[-1],
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        state=state,
    )
    item._global_index = 3
    item.embedded_pixmap = _pixmap() if has_embedded else None
    item.hq_pixmap = _pixmap() if has_hq else None

    if display_source == "hq":
        item.pixmap = item.hq_pixmap
        item._pixmap_source = item.hq_pixmap
    elif display_source == "embedded":
        item.pixmap = item.embedded_pixmap
        item._pixmap_source = item.embedded_pixmap
    else:
        item.pixmap = None
        item._pixmap_source = None
    item._pixmap_orientation = None
    return item


class _FakeGrid:
    def __init__(self):
        self.refreshed: list[int] = []

    def refresh_item(self, index: int) -> None:
        self.refreshed.append(index)


class _FakeWindow:
    def __init__(self, item: ImageItem):
        self._items_by_path = {item.path: item}
        self.grid = _FakeGrid()


def _set_lowres_only(monkeypatch, enabled: bool) -> None:
    def _fake_get_runtime_setting(key):
        if key == RuntimeSettingKey.GRID_LOWRES_ONLY:
            return enabled
        return False

    monkeypatch.setattr(
        "piqopiqo.main_window.get_runtime_setting",
        _fake_get_runtime_setting,
    )


def test_hq_ready_with_loaded_hq_keeps_display_and_skips_refresh(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    _set_lowres_only(monkeypatch, False)

    item = _item(
        "/tmp/a.jpg",
        state=2,
        has_embedded=True,
        has_hq=True,
        display_source="hq",
    )
    window = _FakeWindow(item)

    original_hq = item.hq_pixmap
    original_display = item.pixmap

    MainWindow.on_thumb_ready(window, item.path, "hq", "/tmp/hq.jpg")

    assert item.state == 2
    assert item.hq_pixmap is original_hq
    assert item.pixmap is original_display
    assert window.grid.refreshed == []


def test_hq_ready_without_loaded_hq_invalidates_and_refreshes(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    _set_lowres_only(monkeypatch, False)

    item = _item(
        "/tmp/b.jpg",
        state=1,
        has_embedded=True,
        has_hq=False,
        display_source="embedded",
    )
    window = _FakeWindow(item)

    MainWindow.on_thumb_ready(window, item.path, "hq", "/tmp/hq.jpg")

    assert item.state == 2
    assert item.hq_pixmap is None
    assert item.pixmap is None
    assert window.grid.refreshed == [item._global_index]


def test_embedded_ready_with_loaded_hq_keeps_display_and_skips_refresh(
    qapp, monkeypatch
):
    init_qsettings_store(dyn=True)
    _set_lowres_only(monkeypatch, False)

    item = _item(
        "/tmp/c.jpg",
        state=2,
        has_embedded=True,
        has_hq=True,
        display_source="hq",
    )
    window = _FakeWindow(item)

    original_hq = item.hq_pixmap
    original_display = item.pixmap

    MainWindow.on_thumb_ready(window, item.path, "embedded", "/tmp/embedded.jpg")

    assert item.state == 2
    assert item.embedded_pixmap is None
    assert item.hq_pixmap is original_hq
    assert item.pixmap is original_display
    assert window.grid.refreshed == []


def test_embedded_ready_without_hq_invalidates_and_refreshes(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    _set_lowres_only(monkeypatch, False)

    item = _item(
        "/tmp/d.jpg",
        state=1,
        has_embedded=True,
        has_hq=False,
        display_source="embedded",
    )
    window = _FakeWindow(item)

    MainWindow.on_thumb_ready(window, item.path, "embedded", "/tmp/embedded.jpg")

    assert item.state == 1
    assert item.embedded_pixmap is None
    assert item.pixmap is None
    assert window.grid.refreshed == [item._global_index]


def test_lowres_only_ignores_non_embedded_thumb_ready(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    _set_lowres_only(monkeypatch, True)

    item = _item(
        "/tmp/e.jpg",
        state=1,
        has_embedded=True,
        has_hq=False,
        display_source="embedded",
    )
    window = _FakeWindow(item)

    original_state = item.state
    original_embedded = item.embedded_pixmap
    original_hq = item.hq_pixmap
    original_display = item.pixmap

    MainWindow.on_thumb_ready(window, item.path, "hq", "/tmp/hq.jpg")

    assert item.state == original_state
    assert item.embedded_pixmap is original_embedded
    assert item.hq_pixmap is original_hq
    assert item.pixmap is original_display
    assert window.grid.refreshed == []
