"""Regression tests for right-sidebar shortcut focus handling."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.background.media_man import FolderPrimingResult
from piqopiqo.main_window import MainWindow
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.shortcuts import Shortcut
from piqopiqo.ssf.settings_state import (
    UserSettingKey,
    get_user_setting,
    init_qsettings_store,
    set_user_setting,
)


class _SignalStub:
    def connect(self, *_args, **_kwargs) -> None:
        return None


class _MediaManagerStub:
    next_priming_result = FolderPrimingResult({}, set())

    def __init__(self, *_args, **_kwargs):
        self.thumb_ready = _SignalStub()
        self.thumb_progress_updated = _SignalStub()
        self.editable_ready = _SignalStub()
        self.editable_terminal = _SignalStub()
        self.exif_progress_updated = _SignalStub()
        self.panel_fields_ready = _SignalStub()
        self.all_completed = _SignalStub()

    def reset_for_folder(
        self, _file_paths: list[str], _source_folders: list[str]
    ) -> FolderPrimingResult:
        return self.next_priming_result

    def pause_processing(self) -> None:
        return None

    def resume_processing(self) -> None:
        return None

    def update_visible(self, _visible_paths_in_order: list[str]) -> None:
        return None

    def has_errors(self) -> bool:
        return False

    def add_files(self, _file_paths: list[str]) -> None:
        return None

    def remove_files(self, _file_paths: list[str]) -> None:
        return None

    def request_thumbnail(self, _file_path: str) -> None:
        return None

    def regenerate_thumbnails(self, _file_paths: list[str]) -> None:
        return None

    def refresh_files(self, _file_paths: list[str]) -> None:
        return None

    def reload_exif(self, _file_paths: list[str]) -> None:
        return None

    def ensure_panel_fields_loaded_from_db(self, _file_paths: list[str]) -> None:
        return None

    def refresh_exif_field_keys(self, _field_keys: list[str]) -> None:
        return None

    def stop(self, timeout_s: float | None = None) -> None:  # noqa: ARG002
        return None


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-sidebar-shortcuts-{uuid.uuid4().hex}")
    return app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):  # noqa: ARG001
    monkeypatch.setattr("piqopiqo.cache_paths._CACHE_BASE_DIR", tmp_path / "cache")
    init_qsettings_store(dyn=True)
    _MediaManagerStub.next_priming_result = FolderPrimingResult({}, set())
    monkeypatch.setattr("piqopiqo.main_window.MediaManager", _MediaManagerStub)
    monkeypatch.setattr(
        "piqopiqo.main_window.refresh_main_screen_color_space_cache_macos",
        lambda: None,
    )

    images = [
        {
            "path": f"/photos/{index}.jpg",
            "name": f"{index}.jpg",
            "created": "2020-01-01 00:00:00",
            "source_folder": "/photos",
            "state": 0,
        }
        for index in range(200)
    ]

    main_window = MainWindow(images, ["/photos"], None)
    main_window.resize(900, 700)
    main_window.show()
    qapp.processEvents()
    yield main_window
    main_window.close()


@pytest.fixture
def metadata_window(window, qapp):
    item = window.images_data[0]
    data = {DBFields.TITLE: "A photo title", DBFields.KEYWORDS: "alpha, beta"}
    window.db_manager.get_db_for_image(item.path).save_metadata(item.path, data)
    item.db_metadata = data
    window.grid.on_cell_clicked(0, False, False)
    window.activateWindow()
    window.grid.setFocus()
    qapp.processEvents()
    return window


@pytest.mark.parametrize("key", [Qt.Key_L, Qt.Key_K])
def test_metadata_shortcuts_focus_editor_and_receive_typing(metadata_window, qapp, key):
    panel = metadata_window.edit_panel
    QTest.keyClick(metadata_window.grid, key, Qt.ControlModifier)
    qapp.processEvents()

    editor = panel.title_edit if key == Qt.Key_L else panel.keywords_edit
    assert qapp.focusWidget() is editor
    if key == Qt.Key_L:
        assert editor.selectedText() == "A photo title"
    else:
        cursor = editor.textCursor()
        assert not cursor.hasSelection()
        assert cursor.position() == len("alpha, beta")

    QTest.keyClicks(editor, "new")
    assert editor.text() == ("new" if key == Qt.Key_L else "alpha, betanew")
    QTest.keyClick(editor, Qt.Key_Escape)
    qapp.processEvents()


@pytest.mark.parametrize("key", [Qt.Key_L, Qt.Key_K])
def test_repeated_metadata_shortcut_preserves_pending_edit_and_selection(
    metadata_window, qapp, key
):
    QTest.keyClick(metadata_window.grid, key, Qt.ControlModifier)
    editor = qapp.focusWidget()
    QTest.keyClicks(editor, "pending, ")
    if key == Qt.Key_L:
        editor.setSelection(1, 3)
        before = (
            editor.cursorPosition(),
            editor.selectionStart(),
            editor.selectedText(),
        )
    else:
        cursor = editor.textCursor()
        cursor.setPosition(1)
        cursor.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        before = (cursor.position(), cursor.anchor(), cursor.selectedText())
    text_before = editor.text()

    QTest.keyClick(editor, key, Qt.ControlModifier)
    qapp.processEvents()

    assert qapp.focusWidget() is editor
    assert editor.text() == text_before
    if key == Qt.Key_L:
        assert (
            editor.cursorPosition(),
            editor.selectionStart(),
            editor.selectedText(),
        ) == before
    else:
        cursor = editor.textCursor()
        assert (cursor.position(), cursor.anchor(), cursor.selectedText()) == before
    QTest.keyClick(editor, Qt.Key_Escape)
    qapp.processEvents()


def test_metadata_shortcuts_switch_between_active_editors(metadata_window, qapp):
    panel = metadata_window.edit_panel
    QTest.keyClick(metadata_window.grid, Qt.Key_L, Qt.ControlModifier)
    QTest.keyClick(panel.title_edit, Qt.Key_K, Qt.ControlModifier)
    qapp.processEvents()
    assert qapp.focusWidget() is panel.keywords_edit
    assert panel.keywords_edit.textCursor().position() == len("alpha, beta")

    QTest.keyClick(panel.keywords_edit, Qt.Key_L, Qt.ControlModifier)
    qapp.processEvents()
    assert qapp.focusWidget() is panel.title_edit
    assert panel.title_edit.selectedText() == "A photo title"


def test_metadata_shortcut_flushes_pending_selection_refresh(metadata_window, qapp):
    metadata_window._show_selection_panels_pending(1)
    metadata_window._schedule_deferred_selection_panel_refresh()
    assert not metadata_window.edit_panel.title_edit.isEnabled()

    QTest.keyClick(metadata_window.grid, Qt.Key_L, Qt.ControlModifier)
    qapp.processEvents()

    assert metadata_window._selection_panel_refresh_scheduled_serial is None
    assert qapp.focusWidget() is metadata_window.edit_panel.title_edit
    assert metadata_window.edit_panel.title_edit.selectedText() == "A photo title"


def test_metadata_shortcut_reveals_collapsed_panels(metadata_window, qapp):
    metadata_window._toggle_right_sidebar_collapsed()
    metadata_window._right_splitter.setSizes([0, 500])
    qapp.processEvents()
    assert metadata_window._main_splitter.sizes()[1] == 0

    QTest.keyClick(metadata_window.grid, Qt.Key_K, Qt.ControlModifier)
    qapp.processEvents()

    assert metadata_window._main_splitter.sizes()[1] > 0
    assert metadata_window._right_splitter.sizes()[0] > 0
    assert qapp.focusWidget() is metadata_window.edit_panel.keywords_edit


def test_metadata_shortcuts_use_updated_settings(metadata_window, qapp):
    set_user_setting(
        UserSettingKey.SHORTCUTS,
        {
            Shortcut.EDIT_TITLE: "Ctrl+Shift+T",
            Shortcut.EDIT_KEYWORDS: "",
        },
    )
    metadata_window._setup_shortcuts()
    qapp.processEvents()

    for key in (Qt.Key_L, Qt.Key_K):
        QTest.keyClick(metadata_window.grid, key, Qt.ControlModifier)
        assert qapp.focusWidget() is metadata_window.grid

    QTest.keyClick(
        metadata_window.grid, Qt.Key_T, Qt.ControlModifier | Qt.ShiftModifier
    )
    qapp.processEvents()
    assert qapp.focusWidget() is metadata_window.edit_panel.title_edit


@pytest.mark.parametrize(
    "value,matching_indices,include_no_label",
    [
        ("13", [0, 1], False),
        ("013", [0, 1, 2, 3], True),
        ("0", [2, 3], True),
    ],
)
def test_base_labels_shortcut_updates_filter_and_preserves_search(
    window, qapp, value, matching_indices, include_no_label
):
    set_user_setting(UserSettingKey.BASE_LABELS, value)
    labels = get_user_setting(UserSettingKey.STATUS_LABELS)
    photos = window.photo_model.all_photos[:4]
    for photo, label in zip(
        photos, [labels[0].name, labels[2].name, None, "Old label"], strict=True
    ):
        photo.db_metadata = {DBFields.TITLE: "sunset", DBFields.LABEL: label}
    window.filter_panel.search_field.setText("sunset")
    window.filter_panel.toggle_label_filter(None)
    window.activateWindow()
    window.grid.setFocus()
    qapp.processEvents()

    QTest.keyClick(window.grid, Qt.Key_Backslash, Qt.MetaModifier)
    qapp.processEvents()

    criteria = window.filter_panel.get_current_filter()
    assert criteria.labels == (
        {labels[0].name, labels[2].name} if value != "0" else set()
    )
    assert criteria.search_text == "sunset"
    assert criteria.include_no_label is include_no_label
    assert window.photo_model._filter == criteria
    assert window.photo_model.photos == [photos[index] for index in matching_indices]

    QTest.keyClick(window.grid, Qt.Key_Backslash, Qt.MetaModifier)
    qapp.processEvents()
    assert window.filter_panel.get_current_filter() == criteria


@pytest.mark.parametrize("key", [Qt.Key_L, Qt.Key_K])
def test_metadata_shortcuts_leave_disabled_editors_unfocused(window, qapp, key):
    window.edit_panel.update_for_selection([])
    window.activateWindow()
    window.grid.setFocus()
    qapp.processEvents()

    QTest.keyClick(window.grid, key, Qt.ControlModifier)
    qapp.processEvents()

    assert qapp.focusWidget() is window.grid


def _press_toggle_shortcut(window: MainWindow, qapp: QApplication) -> None:
    QTest.keyClick(window, Qt.Key_BracketRight, Qt.ControlModifier)
    qapp.processEvents()


def _first_populated_cell(window: MainWindow):
    return next(cell for cell in window.grid.cells if cell.current_data is not None)


def _viewport_row_for_path(window: MainWindow, path: str) -> int:
    index = window.grid.get_index_for_path(path)
    assert index is not None
    return (index // window.grid.n_cols) - window.grid.scrollbar.value()


def _place_selected_path_on_viewport_row(
    window: MainWindow,
    qapp: QApplication,
    target_index: int,
    viewport_row: int,
) -> str:
    assert window.grid.n_rows > viewport_row

    target_path = window.images_data[target_index].path
    window.grid.on_cell_clicked(target_index, False, False)
    qapp.processEvents()

    target_data_row = target_index // window.grid.n_cols
    top_row = max(
        0,
        min(target_data_row - viewport_row, window.grid.scrollbar.maximum()),
    )
    window.grid.scrollbar.setValue(top_row)
    qapp.processEvents()

    assert target_path in window.grid.get_viewport_visible_paths()
    assert _viewport_row_for_path(window, target_path) == viewport_row
    return target_path


def test_toggle_sidebar_shortcut_repeats_from_grid_after_toggle(window, qapp):
    initial_rows = window.grid.n_rows
    cell = _first_populated_cell(window)

    QTest.mouseClick(cell, Qt.LeftButton)
    qapp.processEvents()

    assert qapp.focusWidget() is cell

    _press_toggle_shortcut(window, qapp)

    collapsed_sizes = window._main_splitter.sizes()
    assert collapsed_sizes[1] == 0
    assert window.grid.n_rows == initial_rows
    assert qapp.focusWidget() is window.grid

    _press_toggle_shortcut(window, qapp)

    restored_sizes = window._main_splitter.sizes()
    assert restored_sizes[1] > 0
    assert restored_sizes != collapsed_sizes
    assert qapp.focusWidget() is window.grid


def test_toggle_sidebar_shortcut_preserves_panel_focus(window, qapp):
    assert window.exif_panel is not None

    window.exif_panel.setFocus(Qt.FocusReason.OtherFocusReason)
    qapp.processEvents()

    assert qapp.focusWidget() is window.exif_panel

    _press_toggle_shortcut(window, qapp)
    assert window._main_splitter.sizes()[1] == 0
    assert qapp.focusWidget() is window.exif_panel

    _press_toggle_shortcut(window, qapp)
    assert window._main_splitter.sizes()[1] > 0
    assert qapp.focusWidget() is window.exif_panel


def test_toggle_sidebar_keeps_visible_items_when_selected_anchor_is_offscreen(
    window,
    qapp,
):
    initial_rows = window.grid.n_rows
    target_index = 150
    target_path = window.images_data[target_index].path
    initial_visible_paths = window.grid.get_viewport_visible_paths()

    window.grid.on_cell_clicked(target_index, False, False)
    qapp.processEvents()

    assert target_path not in window.grid.get_viewport_visible_paths()
    assert window.grid.get_viewport_visible_paths() == initial_visible_paths

    window._toggle_right_sidebar_collapsed()
    qapp.processEvents()

    assert window.grid.n_rows == initial_rows
    assert target_path not in window.grid.get_viewport_visible_paths()
    assert window.grid.get_viewport_visible_paths() == initial_visible_paths

    window._toggle_right_sidebar_collapsed()
    qapp.processEvents()

    assert window.grid.get_viewport_visible_paths() == initial_visible_paths


def test_toggle_sidebar_keeps_row_count_and_cell_height_but_expands_width(window, qapp):
    initial_rows = window.grid.n_rows
    initial_cell = _first_populated_cell(window)
    initial_width = initial_cell.width()
    initial_height = initial_cell.height()

    window._toggle_right_sidebar_collapsed()
    qapp.processEvents()

    collapsed_cell = _first_populated_cell(window)

    assert window.grid.n_rows == initial_rows
    assert collapsed_cell.width() > initial_width
    assert collapsed_cell.height() == initial_height


def test_collapsed_sidebar_resize_keeps_fixed_row_count(window, qapp):
    initial_rows = window.grid.n_rows

    window._toggle_right_sidebar_collapsed()
    qapp.processEvents()

    collapsed_rows = window.grid.n_rows
    collapsed_cell_height = _first_populated_cell(window).height()

    assert collapsed_rows == initial_rows

    window.resize(900, 900)
    qapp.processEvents()

    resized_cell_height = _first_populated_cell(window).height()

    assert window.grid.n_rows == collapsed_rows
    assert resized_cell_height > collapsed_cell_height


@pytest.mark.parametrize(
    ("button_attr", "expected_delta"),
    [("increment_button", 1), ("decrement_button", -1)],
)
def test_column_selector_keeps_visible_selected_anchor_on_same_row(
    window,
    qapp,
    button_attr,
    expected_delta,
):
    viewport_row = 1
    target_path = _place_selected_path_on_viewport_row(
        window,
        qapp,
        target_index=72,
        viewport_row=viewport_row,
    )
    initial_cols = window.grid.n_cols

    getattr(window.column_selector, button_attr).click()
    qapp.processEvents()

    assert window.grid.n_cols == initial_cols + expected_delta
    assert target_path in window.grid.get_viewport_visible_paths()
    assert _viewport_row_for_path(window, target_path) == viewport_row
