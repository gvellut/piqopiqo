"""Tests for status bar count text and centered column controls."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QMainWindow
import pytest

from piqopiqo.components.status_bar import LoadingStatusBar
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


def test_photo_count_format_includes_selected_for_filtered_and_unfiltered(qapp):
    init_qsettings_store(dyn=True)
    status_bar = LoadingStatusBar()

    status_bar.set_photo_count(10, selected=3)
    assert status_bar.count_label.text() == "10 photos / 3 selected"

    status_bar.set_photo_count(10, 4, selected=2)
    assert status_bar.count_label.text() == "4 of 10 photos / 2 selected"


def test_column_buttons_disable_at_bounds_and_emit_when_enabled(qapp):
    init_qsettings_store(dyn=True)
    status_bar = LoadingStatusBar()

    events: list[str] = []
    status_bar.decrement_columns_requested.connect(lambda: events.append("dec"))
    status_bar.increment_columns_requested.connect(lambda: events.append("inc"))

    status_bar.set_column_count(3, 3, 10)
    assert status_bar.columns_decrement_btn.isEnabled() is False
    assert status_bar.columns_increment_btn.isEnabled() is True

    status_bar.set_column_count(10, 3, 10)
    assert status_bar.columns_decrement_btn.isEnabled() is True
    assert status_bar.columns_increment_btn.isEnabled() is False

    status_bar.set_column_count(6, 3, 10)
    status_bar.columns_decrement_btn.click()
    status_bar.columns_increment_btn.click()
    assert events == ["dec", "inc"]


def test_column_control_stays_strictly_centered(qapp):
    init_qsettings_store(dyn=True)
    window = QMainWindow()
    status_bar = LoadingStatusBar()
    window.setStatusBar(status_bar)
    window.resize(1100, 700)
    window.show()
    qapp.processEvents()

    status_bar.set_column_count(6, 3, 10)
    status_bar.set_photo_count(5000, 47, selected=31)
    status_bar.set_thumb_progress(5, 200)
    status_bar.set_has_errors(True)
    qapp.processEvents()

    control_geom = status_bar._column_control.geometry()
    control_center_x = control_geom.x() + (control_geom.width() / 2.0)
    status_center_x = status_bar.width() / 2.0
    assert abs(control_center_x - status_center_x) <= 1.0

    window.resize(900, 700)
    qapp.processEvents()
    control_geom = status_bar._column_control.geometry()
    control_center_x = control_geom.x() + (control_geom.width() / 2.0)
    status_center_x = status_bar.width() / 2.0
    assert abs(control_center_x - status_center_x) <= 1.0
