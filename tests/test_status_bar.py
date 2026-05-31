"""Tests for status bar count and layout behavior."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QMainWindow
import pytest

from piqopiqo.components.status_bar import NO_FOLDER_LOADED_TEXT, LoadingStatusBar
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
    core.setApplicationName(f"piqopiqo-test-status-bar-{uuid.uuid4().hex}")
    return app


def _label_center_x(status_bar: LoadingStatusBar) -> float:
    rect = status_bar.folder_label.geometry()
    return rect.x() + rect.width() / 2


def _show_status_bar(
    qapp: QApplication,
    status_bar: LoadingStatusBar,
    *,
    width: int = 1600,
) -> QMainWindow:
    window = QMainWindow()
    window.resize(width, 120)
    window.setStatusBar(status_bar)
    window.show()
    qapp.processEvents()
    qapp.processEvents()
    return window


def test_photo_count_format_includes_selected_for_filtered_and_unfiltered(qapp):
    init_qsettings_store(dyn=True)
    status_bar = LoadingStatusBar()

    status_bar.set_photo_count(10, selected=3)
    assert status_bar.count_label.text() == "10 photos / 3 selected"

    status_bar.set_photo_count(10, 4, selected=2)
    assert status_bar.count_label.text() == "4 of 10 photos / 2 selected"


def test_status_bar_folder_label_defaults_to_no_folder_loaded(qapp):
    init_qsettings_store(dyn=True)
    status_bar = LoadingStatusBar()

    assert status_bar.folder_label.full_text == NO_FOLDER_LOADED_TEXT
    assert status_bar.folder_label.toolTip() == NO_FOLDER_LOADED_TEXT


def test_status_bar_folder_label_updates_and_resets_empty_values(qapp):
    init_qsettings_store(dyn=True)
    status_bar = LoadingStatusBar()

    status_bar.set_folder_label("trip/shoot")
    assert status_bar.folder_label.full_text == "trip/shoot"
    assert status_bar.folder_label.toolTip() == "trip/shoot"

    status_bar.set_folder_label("")
    assert status_bar.folder_label.full_text == NO_FOLDER_LOADED_TEXT


def test_status_bar_folder_label_wide_default_text_is_not_elided(qapp):
    init_qsettings_store(dyn=True)
    status_bar = LoadingStatusBar()
    window = _show_status_bar(qapp, status_bar)

    assert window.isVisible()
    assert status_bar.folder_label.text() == NO_FOLDER_LOADED_TEXT


def test_status_bar_folder_label_wide_folder_name_is_not_elided(qapp):
    init_qsettings_store(dyn=True)
    status_bar = LoadingStatusBar()
    status_bar.set_folder_label("20260509_miribel")
    window = _show_status_bar(qapp, status_bar)

    assert window.isVisible()
    assert status_bar.folder_label.text() == "20260509_miribel"


def test_status_bar_folder_label_still_elides_when_constrained(qapp, monkeypatch):
    monkeypatch.setenv("PIQO_STATUS_BAR_FOLDER_LABEL_MAX_WIDTH_RATIO", "0.1")
    init_qsettings_store(dyn=True)
    status_bar = LoadingStatusBar()
    long_folder = "/" + "/".join(["very-long-folder-name"] * 20)
    status_bar.set_folder_label(long_folder)
    window = _show_status_bar(qapp, status_bar, width=800)

    assert window.isVisible()
    assert status_bar.folder_label.full_text == long_folder
    assert status_bar.folder_label.text().endswith("\u2026")
    assert status_bar.folder_label.text() != long_folder


def test_status_bar_side_padding_runtime_setting_is_applied(qapp, monkeypatch):
    monkeypatch.setenv("PIQO_STATUS_BAR_SIDE_PADDING", "16")
    init_qsettings_store(dyn=True)
    status_bar = LoadingStatusBar()

    left_layout = status_bar._left_cluster.layout()
    right_layout = status_bar._right_cluster.layout()
    assert left_layout.contentsMargins().left() == 16
    assert right_layout.contentsMargins().right() == 16


def test_status_bar_folder_label_max_width_ratio_is_applied(qapp, monkeypatch):
    monkeypatch.setenv("PIQO_STATUS_BAR_FOLDER_LABEL_MAX_WIDTH_RATIO", "0.25")
    init_qsettings_store(dyn=True)
    window = QMainWindow()
    window.resize(800, 120)
    status_bar = LoadingStatusBar()
    window.setStatusBar(status_bar)
    status_bar.set_folder_label("/" + "/".join(["very-long-folder-name"] * 20))
    window.show()
    qapp.processEvents()

    assert status_bar.folder_label.width() <= int(
        status_bar.contentsRect().width() * 0.25
    )


def test_status_bar_height_stays_stable_when_progress_or_errors_appear(qapp):
    init_qsettings_store(dyn=True)
    window = QMainWindow()
    status_bar = LoadingStatusBar()
    window.setStatusBar(status_bar)
    window.show()
    qapp.processEvents()

    initial_height = status_bar.height()

    status_bar.set_thumb_progress(1, 10)
    qapp.processEvents()
    assert status_bar.height() == initial_height

    status_bar.reset()
    status_bar.set_has_errors(True)
    qapp.processEvents()
    assert status_bar.height() == initial_height


def test_status_bar_selection_progress_is_full_without_text(qapp):
    init_qsettings_store(dyn=True)
    status_bar = LoadingStatusBar()

    status_bar.set_selection_progress_active(True)

    assert status_bar.progress_bar.isHidden() is False
    assert status_bar.progress_bar.minimum() == 0
    assert status_bar.progress_bar.maximum() == 1
    assert status_bar.progress_bar.value() == 1
    assert status_bar.progress_bar.format() == ""
    assert status_bar.progress_bar.isTextVisible() is False

    status_bar.set_selection_progress_active(False)

    assert status_bar.progress_bar.isHidden() is True
    assert status_bar.progress_bar.isTextVisible() is True


def test_status_bar_loading_progress_takes_precedence_over_selection(qapp):
    init_qsettings_store(dyn=True)
    status_bar = LoadingStatusBar()

    status_bar.set_selection_progress_active(True)
    status_bar.set_thumb_progress(1, 10)

    assert status_bar.progress_bar.isHidden() is False
    assert status_bar.progress_bar.maximum() == 10
    assert status_bar.progress_bar.value() == 1
    assert status_bar.progress_bar.format() == "1/10"
    assert status_bar.progress_bar.isTextVisible() is True

    status_bar.set_thumb_progress(10, 10)

    assert status_bar.progress_bar.isHidden() is False
    assert status_bar.progress_bar.maximum() == 1
    assert status_bar.progress_bar.value() == 1
    assert status_bar.progress_bar.format() == ""
    assert status_bar.progress_bar.isTextVisible() is False


def test_status_bar_folder_label_center_stays_stable_when_controls_change(qapp):
    init_qsettings_store(dyn=True)
    window = QMainWindow()
    window.resize(900, 120)
    status_bar = LoadingStatusBar()
    window.setStatusBar(status_bar)
    status_bar.set_folder_label("trip/shoot")
    status_bar.set_photo_count(10, selected=0)
    window.show()
    qapp.processEvents()

    initial_center = _label_center_x(status_bar)

    status_bar.set_photo_count(10000, 999, selected=777)
    qapp.processEvents()
    assert _label_center_x(status_bar) == pytest.approx(initial_center, abs=0.5)

    status_bar.set_thumb_progress(1, 10)
    qapp.processEvents()
    assert _label_center_x(status_bar) == pytest.approx(initial_center, abs=0.5)

    status_bar.set_has_errors(True)
    qapp.processEvents()
    assert _label_center_x(status_bar) == pytest.approx(initial_center, abs=0.5)
