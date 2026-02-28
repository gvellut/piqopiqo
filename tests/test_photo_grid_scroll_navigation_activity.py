"""Tests for scroll navigation-activity handling in PhotoGrid."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.grid.photo_grid import PhotoGrid
from piqopiqo.model import ImageItem
from piqopiqo.ssf.settings_state import init_qsettings_store


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-grid-scroll-{uuid.uuid4().hex}")
    return app


def _item(path: str) -> ImageItem:
    return ImageItem(
        path=path,
        name=path.split("/")[-1],
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        state=0,
    )


def test_ensure_visible_without_navigation_activity_skips_mark(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    grid._rebuild_grid(1, 1)
    grid.set_data([_item(f"/tmp/{i}.jpg") for i in range(6)])
    qapp.processEvents()

    grid.scrollbar.setValue(5)
    qapp.processEvents()

    marks = {"count": 0}

    def _mark():
        marks["count"] += 1

    monkeypatch.setattr(grid, "_mark_navigation_activity", _mark)
    grid._ensure_visible(0, navigation_activity=False)
    qapp.processEvents()

    assert grid.scrollbar.value() == 0
    assert marks["count"] == 0


def test_ensure_visible_with_navigation_activity_marks(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    grid._rebuild_grid(1, 1)
    grid.set_data([_item(f"/tmp/{i}.jpg") for i in range(6)])
    qapp.processEvents()

    grid.scrollbar.setValue(0)
    qapp.processEvents()

    marks = {"count": 0}

    def _mark():
        marks["count"] += 1

    monkeypatch.setattr(grid, "_mark_navigation_activity", _mark)
    grid._ensure_visible(5, navigation_activity=True)
    qapp.processEvents()

    assert grid.scrollbar.value() == 5
    assert marks["count"] >= 1
