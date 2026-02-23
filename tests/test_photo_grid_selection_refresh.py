"""Tests for lightweight grid selection highlight refresh."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.grid.photo_grid import PhotoGrid
from piqopiqo.model import ImageItem
from piqopiqo.settings_state import init_qsettings_store


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-grid-{uuid.uuid4().hex}")
    return app


def _item(path: str, *, selected: bool = False) -> ImageItem:
    return ImageItem(
        path=path,
        name=path.split("/")[-1],
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        is_selected=selected,
        state=0,
    )


def test_refresh_visible_selection_only_updates_cells_without_full_render(
    qapp, monkeypatch
):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    grid._rebuild_grid(1, 2)

    items = [_item("/tmp/a.jpg"), _item("/tmp/b.jpg")]
    grid.set_data(items)
    qapp.processEvents()

    items[0].is_selected = True
    items[1].is_selected = False

    render_calls = {"count": 0}

    def _record_render(*_args, **_kwargs):
        render_calls["count"] += 1

    monkeypatch.setattr(grid, "_render", _record_render)
    grid.refresh_visible_selection_only()

    assert render_calls["count"] == 0
    assert grid.cells[0].is_selected is True
    assert grid.cells[1].is_selected is False
