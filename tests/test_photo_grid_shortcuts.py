"""Tests for PhotoGrid view-scoped shortcut ownership."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QVBoxLayout, QWidget
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
    core.setApplicationName(f"piqopiqo-test-grid-shortcuts-{uuid.uuid4().hex}")
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


def test_select_all_visible_selects_all_items_and_emits_selection(qapp):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    items = [_item("/tmp/a.jpg"), _item("/tmp/b.jpg"), _item("/tmp/c.jpg")]
    grid.set_data(items)

    emitted: list[set[int]] = []
    grid.selection_changed.connect(lambda indices: emitted.append(set(indices)))

    grid.select_all_visible()

    assert [item.is_selected for item in items] == [True, True, True]
    assert grid._last_selected_index == 2
    assert emitted == [{0, 1, 2}]


def test_shared_grid_scope_shortcuts_follow_focus_text_vs_panel(qapp):
    init_qsettings_store(dyn=True)

    root = QWidget()
    layout = QVBoxLayout(root)
    grid = PhotoGrid()
    panel_button = QPushButton("Panel Action")
    search_field = QLineEdit()
    layout.addWidget(grid)
    layout.addWidget(panel_button)
    layout.addWidget(search_field)
    grid.set_grid_view_shortcut_scope(root)

    root.show()
    root.activateWindow()
    qapp.processEvents()

    assert grid._shared_grid_view_shortcut_objects

    panel_button.setFocus()
    qapp.processEvents()
    grid._update_shared_grid_view_shortcut_enabled_state()
    assert all(sc.isEnabled() for sc in grid._shared_grid_view_shortcut_objects)

    search_field.setFocus()
    qapp.processEvents()
    grid._update_shared_grid_view_shortcut_enabled_state()
    assert all(not sc.isEnabled() for sc in grid._shared_grid_view_shortcut_objects)
