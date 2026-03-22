"""Regression tests for pointer-anchored fullscreen zoom behavior."""

from __future__ import annotations

from types import SimpleNamespace
import uuid

from PySide6.QtCore import QCoreApplication, QPointF
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.fullscreen.overlay import FullscreenOverlay
from piqopiqo.fullscreen.zoom import ZoomState
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
    core.setApplicationName(f"piqopiqo-test-fullscreen-pointer-{uuid.uuid4().hex}")
    return app


def _build_overlay(monkeypatch) -> FullscreenOverlay:
    pixmap = QPixmap(600, 1800)
    pixmap.fill(QColor("white"))

    monkeypatch.setattr(
        "piqopiqo.fullscreen.overlay.atexit.register",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        FullscreenOverlay,
        "_load_fullscreen_pixmap_with_color_management",
        lambda self: pixmap,
    )
    monkeypatch.setattr(FullscreenOverlay, "_update_info_panel", lambda self: None)

    overlay = FullscreenOverlay(
        all_items=[SimpleNamespace(path="/virtual/portrait.jpg", db_metadata={})],
        visible_indices=[0],
        start_index=0,
    )
    overlay.resize(1200, 800)
    overlay._device_pixel_ratio = 1.0
    return overlay


def _actual_image_coords(overlay: FullscreenOverlay, screen_pos: QPointF) -> QPointF:
    base_scale = overlay._get_base_scale_factor()
    pixmap_size = overlay._pixmap.size()
    scaled_width = pixmap_size.width() * base_scale
    scaled_height = pixmap_size.height() * base_scale

    target_rect = overlay.rect()
    base_x = (target_rect.width() - scaled_width) / 2
    base_y = (target_rect.height() - scaled_height) / 2

    image_space = QPointF(
        (screen_pos.x() - base_x) / base_scale,
        (screen_pos.y() - base_y) / base_scale,
    )
    inverse_transform, invertible = overlay._transform.inverted()
    assert invertible is True
    return inverse_transform.map(image_space)


def _assert_anchor_preserved(
    overlay: FullscreenOverlay,
    screen_pos: QPointF,
    action,
) -> None:
    before = _actual_image_coords(overlay, screen_pos)
    action()
    after = _actual_image_coords(overlay, screen_pos)

    assert after.x() == pytest.approx(before.x(), abs=1e-6)
    assert after.y() == pytest.approx(before.y(), abs=1e-6)


def _pan_overlay_in_screen_space(
    overlay: FullscreenOverlay,
    dx_screen: float,
    dy_screen: float,
) -> None:
    scale = overlay._zoom_level * overlay._get_base_scale_factor()
    overlay._transform.translate(dx_screen / scale, dy_screen / scale)
    overlay._set_allowed_extra_space_from_current()
    overlay._clamp_pan()


def _assert_regular_base_view(overlay: FullscreenOverlay) -> None:
    current_space = overlay._get_current_space_per_side()

    assert overlay._zoom_state == ZoomState.BASE_VIEW
    assert overlay._transform.isIdentity()
    assert current_space["top"] == pytest.approx(0.0, abs=1.5)
    assert current_space["bottom"] == pytest.approx(0.0, abs=1.5)
    assert current_space["left"] == pytest.approx(current_space["right"], abs=3.5)


def test_pointer_zoom_keeps_hovered_pixel_for_portrait_images(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    overlay = _build_overlay(monkeypatch)
    overlay.show()
    qapp.processEvents()

    pointer = QPointF(520.0, 260.0)

    assert overlay._zoom_state == ZoomState.BASE_VIEW

    _assert_anchor_preserved(
        overlay,
        pointer,
        lambda: overlay._zoom_in(overlay._get_zoom_anchor_for_screen_pos(pointer)),
    )
    assert overlay._zoom_state == ZoomState.ZOOM_100

    _pan_overlay_in_screen_space(overlay, 90.0, -120.0)

    _assert_anchor_preserved(
        overlay,
        pointer,
        lambda: overlay._zoom_in(overlay._get_zoom_anchor_for_screen_pos(pointer)),
    )
    assert overlay._zoom_state == ZoomState.ZOOM_200

    overlay._handle_click_zoom_out(pointer)
    _assert_regular_base_view(overlay)

    overlay.close()
