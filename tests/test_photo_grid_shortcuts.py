"""Tests for PhotoGrid view-scoped shortcut ownership."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QVBoxLayout, QWidget
import pytest

from piqopiqo.grid.photo_grid import PhotoGrid
from piqopiqo.model import ImageItem
from piqopiqo.shortcuts import Shortcut
from piqopiqo.ssf.settings_state import (
    UserSettingKey,
    init_qsettings_store,
    set_user_setting,
)


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
    assert grid._last_selected_index == 0
    assert grid._last_selected_path == "/tmp/a.jpg"
    assert emitted == [{0, 1, 2}]


def test_deselecting_select_all_anchor_advances_indicator_and_keyboard_origin(qapp):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    grid._rebuild_grid(1, 3)
    items = [_item(f"/tmp/{index}.jpg") for index in range(3)]
    grid.set_data(items)
    grid.select_all_visible()

    grid.on_cell_clicked(0, False, True)

    assert [item.is_selected for item in items] == [False, True, True]
    assert grid._last_selected_index == 1
    assert grid._last_selected_path == "/tmp/1.jpg"
    assert grid.cells[1].is_last_selected is True
    assert grid.cells[2].is_last_selected is False

    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Left, Qt.NoModifier)
    grid.keyPressEvent(event)

    assert [item.is_selected for item in items] == [True, False, False]
    assert grid._last_selected_path == "/tmp/0.jpg"


def test_deselecting_middle_anchor_advances_to_next_selected_image(qapp):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    items = [_item(f"/tmp/{index}.jpg") for index in range(6)]
    grid.set_data(items)
    grid.on_cell_clicked(0, False, False)
    grid.on_cell_clicked(3, False, True)
    grid.on_cell_clicked(5, False, True)
    grid.on_cell_clicked(2, False, True)

    grid.on_cell_clicked(2, False, True)

    assert grid._last_selected_index == 3
    assert grid._last_selected_path == "/tmp/3.jpg"


def test_deselecting_final_anchor_wraps_to_first_selected_image(qapp):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    items = [_item(f"/tmp/{index}.jpg") for index in range(6)]
    grid.set_data(items)
    grid.on_cell_clicked(0, False, False)
    grid.on_cell_clicked(2, False, True)
    grid.on_cell_clicked(5, False, True)

    grid.on_cell_clicked(5, False, True)

    assert grid._last_selected_index == 0
    assert grid._last_selected_path == "/tmp/0.jpg"


def test_deselecting_non_anchor_preserves_current_anchor(qapp):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    items = [_item(f"/tmp/{index}.jpg") for index in range(4)]
    grid.set_data(items)
    grid.on_cell_clicked(0, False, False)
    grid.on_cell_clicked(2, False, True)

    grid.on_cell_clicked(0, False, True)

    assert grid._last_selected_index == 2
    assert grid._last_selected_path == "/tmp/2.jpg"


def test_deselecting_only_selected_image_clears_anchor(qapp):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    items = [_item("/tmp/0.jpg")]
    grid.set_data(items)
    grid.on_cell_clicked(0, False, False)

    grid.on_cell_clicked(0, False, True)

    assert grid._last_selected_index == -1
    assert grid._last_selected_path is None


def test_set_data_advances_filtered_anchor_using_previous_grid_order(qapp):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    items = [_item(f"/tmp/{index}.jpg") for index in range(6)]
    grid.set_data(items)
    grid.on_cell_clicked(0, False, False)
    grid.on_cell_clicked(4, False, True)
    grid.on_cell_clicked(5, False, True)
    grid.on_cell_clicked(3, False, True)

    items[3].is_selected = False
    filtered_items = [items[index] for index in (0, 2, 4, 5)]
    grid.set_data(filtered_items)

    assert grid._last_selected_index == 2
    assert grid._last_selected_path == "/tmp/4.jpg"


def test_set_data_advances_removed_anchor_from_its_former_grid_position(qapp):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    items = [_item(f"/tmp/{index}.jpg") for index in range(6)]
    grid.set_data(items)
    grid.on_cell_clicked(0, False, False)
    grid.on_cell_clicked(3, False, True)
    grid.on_cell_clicked(5, False, True)
    grid.on_cell_clicked(2, False, True)

    items.pop(2)
    grid.set_data(items)

    assert grid._last_selected_index == 2
    assert grid._last_selected_path == "/tmp/3.jpg"


def test_select_paths_advances_invalidated_anchor_without_explicit_replacement(qapp):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    items = [_item(f"/tmp/{index}.jpg") for index in range(6)]
    grid.set_data(items)
    grid.on_cell_clicked(0, False, False)
    grid.on_cell_clicked(3, False, True)
    grid.on_cell_clicked(5, False, True)
    grid.on_cell_clicked(2, False, True)

    grid.select_paths(["/tmp/0.jpg", "/tmp/3.jpg", "/tmp/5.jpg"])

    assert grid._last_selected_index == 3
    assert grid._last_selected_path == "/tmp/3.jpg"


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


def test_escape_shortcut_collapses_multiselection_to_anchor(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.SHORTCUTS,
        {Shortcut.COLLAPSE_TO_LAST_SELECTED: "Esc"},
    )

    grid = PhotoGrid()
    items = [_item("/tmp/a.jpg"), _item("/tmp/b.jpg"), _item("/tmp/c.jpg")]
    grid.set_data(items)
    grid.on_cell_clicked(1, False, False)
    grid.on_cell_clicked(2, False, True)
    grid.on_cell_clicked(0, False, True)

    emitted: list[set[int]] = []
    grid.selection_changed.connect(lambda indices: emitted.append(set(indices)))

    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    grid.keyPressEvent(event)

    assert [item.is_selected for item in items] == [True, False, False]
    assert grid._last_selected_index == 0
    assert grid._last_selected_path == "/tmp/a.jpg"
    assert emitted == [{0}]


def test_escape_shortcut_reveals_anchor_when_it_is_offscreen(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.SHORTCUTS,
        {Shortcut.COLLAPSE_TO_LAST_SELECTED: "Esc"},
    )

    grid = PhotoGrid()
    grid._rebuild_grid(1, 1)
    items = [_item(f"/tmp/{index}.jpg") for index in range(6)]
    grid.set_data(items)
    grid.on_cell_clicked(0, False, False)
    grid.on_cell_clicked(5, False, True)
    grid.scrollbar.setValue(0)
    qapp.processEvents()

    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    grid.keyPressEvent(event)
    qapp.processEvents()

    assert [item.is_selected for item in items] == [
        False,
        False,
        False,
        False,
        False,
        True,
    ]
    assert grid._last_selected_index == 5
    assert grid.scrollbar.value() == 5


def test_escape_shortcut_keeps_scroll_position_when_anchor_is_already_visible(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.SHORTCUTS,
        {Shortcut.COLLAPSE_TO_LAST_SELECTED: "Esc"},
    )

    grid = PhotoGrid()
    grid._rebuild_grid(1, 1)
    items = [_item(f"/tmp/{index}.jpg") for index in range(6)]
    grid.set_data(items)
    grid.on_cell_clicked(0, False, False)
    grid.on_cell_clicked(5, False, True)
    grid.scrollbar.setValue(5)
    qapp.processEvents()

    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    grid.keyPressEvent(event)
    qapp.processEvents()

    assert [item.is_selected for item in items] == [
        False,
        False,
        False,
        False,
        False,
        True,
    ]
    assert grid._last_selected_index == 5
    assert grid.scrollbar.value() == 5


def test_escape_shortcut_reveals_single_selected_item_when_it_is_offscreen(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.SHORTCUTS,
        {Shortcut.COLLAPSE_TO_LAST_SELECTED: "Esc"},
    )

    grid = PhotoGrid()
    grid._rebuild_grid(1, 1)
    items = [_item(f"/tmp/{index}.jpg") for index in range(6)]
    grid.set_data(items)
    grid.on_cell_clicked(5, False, False)
    grid.scrollbar.setValue(0)
    qapp.processEvents()

    emitted: list[set[int]] = []
    grid.selection_changed.connect(lambda indices: emitted.append(set(indices)))

    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    grid.keyPressEvent(event)
    qapp.processEvents()

    assert [item.is_selected for item in items] == [
        False,
        False,
        False,
        False,
        False,
        True,
    ]
    assert grid._last_selected_index == 5
    assert grid._last_selected_path == "/tmp/5.jpg"
    assert grid.scrollbar.value() == 5
    assert emitted == []


def test_filter_shortcut_activation_respects_shared_scope_focus_guard(qapp):
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

    captured_labels: list[str | None] = []
    captured_cycles: list[int] = []
    captured_all: list[bool] = []
    captured_clear: list[bool] = []
    captured_search: list[bool] = []
    captured_toggle: list[bool] = []
    grid.filter_label_shortcut_requested.connect(captured_labels.append)
    grid.folder_filter_cycle_requested.connect(captured_cycles.append)
    grid.folder_filter_all_requested.connect(lambda: captured_all.append(True))
    grid.clear_filter_shortcut_requested.connect(lambda: captured_clear.append(True))
    grid.focus_filter_search_shortcut_requested.connect(
        lambda: captured_search.append(True)
    )
    grid.toggle_sidebar_shortcut_requested.connect(lambda: captured_toggle.append(True))

    panel_button.setFocus()
    qapp.processEvents()

    grid._activate_filter_label_shortcut("Approved")
    grid._activate_filter_label_shortcut(None)
    grid._activate_folder_filter_cycle_shortcut(1)
    grid._activate_folder_filter_cycle_shortcut(-1)
    grid._activate_folder_filter_all_shortcut()
    grid._activate_clear_filter_shortcut()
    grid._activate_focus_filter_search_shortcut()
    grid._activate_toggle_sidebar_shortcut()

    assert captured_labels == ["Approved", None]
    assert captured_cycles == [1, -1]
    assert captured_all == [True]
    assert captured_clear == [True]
    assert captured_search == [True]
    assert captured_toggle == [True]

    search_field.setFocus()
    qapp.processEvents()

    grid._activate_filter_label_shortcut("Review")
    grid._activate_folder_filter_cycle_shortcut(1)
    grid._activate_folder_filter_all_shortcut()
    grid._activate_clear_filter_shortcut()
    grid._activate_focus_filter_search_shortcut()
    grid._activate_toggle_sidebar_shortcut()

    assert captured_labels == ["Approved", None]
    assert captured_cycles == [1, -1]
    assert captured_all == [True]
    assert captured_clear == [True]
    assert captured_search == [True]
    assert captured_toggle == [True]
