"""Tests for status bar count and layout behavior."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
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


def test_status_bar_side_padding_runtime_setting_is_applied(qapp, monkeypatch):
    monkeypatch.setenv("PIQO_STATUS_BAR_SIDE_PADDING", "16")
    init_qsettings_store(dyn=True)
    status_bar = LoadingStatusBar()

    left_layout = status_bar._left_cluster.layout()
    right_layout = status_bar._right_cluster.layout()
    assert left_layout.contentsMargins().left() == 16
    assert right_layout.contentsMargins().right() == 16
