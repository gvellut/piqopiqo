"""Regression tests for right-sidebar shortcut focus handling."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.background.media_man import FolderPrimingResult
from piqopiqo.main_window import MainWindow
from piqopiqo.ssf.settings_state import init_qsettings_store


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
def window(qapp, monkeypatch):  # noqa: ARG001
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


def test_toggle_sidebar_keeps_selected_path_visible(window, qapp):
    initial_rows = window.grid.n_rows
    target_index = 150
    target_path = window.images_data[target_index].path

    window.grid.on_cell_clicked(target_index, False, False)
    qapp.processEvents()

    assert target_path not in window.grid.get_viewport_visible_paths()

    window._toggle_right_sidebar_collapsed()
    qapp.processEvents()

    assert window.grid.n_rows == initial_rows
    assert target_path in window.grid.get_viewport_visible_paths()


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
