"""Tests for fullscreen zoom overlay controller lifecycle behavior."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QLabel, QWidget
import pytest

from piqopiqo.fullscreen.info_panel import ZoomOverlayController
from piqopiqo.fullscreen.zoom import ZoomDirection, ZoomState


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-fullscreen-info-{uuid.uuid4().hex}")
    return app


def _build_controller(overlay: QLabel) -> ZoomOverlayController:
    return ZoomOverlayController(
        overlay_widget=overlay,
        timer_ms=250,
        get_base_scale=lambda: 1.0,
        get_device_pixel_ratio=lambda: 1.0,
        update_overlay_position=lambda: None,
    )


def test_zoom_overlay_timer_parented_and_shutdown_stops_timer(qapp):
    host = QWidget()
    overlay = QLabel(host)
    controller = _build_controller(overlay)

    controller.on_zoom_state_changed(ZoomState.ZOOM_200, ZoomDirection.IN)

    assert controller._timer.parent() is overlay
    assert controller._timer.isActive() is True

    controller.shutdown()

    assert controller._timer.isActive() is False
    assert controller.is_visible is False


def test_zoom_overlay_controller_is_safe_after_overlay_deletion(qapp):
    host = QWidget()
    overlay = QLabel(host)
    controller = _build_controller(overlay)

    controller.on_zoom_state_changed(ZoomState.ZOOM_200, ZoomDirection.IN)
    overlay.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()

    # Should remain no-op and not raise if overlay was deleted.
    controller.hide()
    controller.on_zoom_state_changed(ZoomState.ZOOM_200, ZoomDirection.IN)

    assert controller._is_shutdown is True
    assert controller.is_visible is False
