"""Regression tests for absolute fullscreen zoom across image navigation."""

from __future__ import annotations

import math
from types import SimpleNamespace
import uuid

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.fullscreen.overlay import FullscreenOverlay
from piqopiqo.fullscreen.zoom import ZoomDirection, ZoomState
from piqopiqo.metadata.db_fields import DBFields
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
    core.setApplicationName(f"piqopiqo-test-fullscreen-navigation-{uuid.uuid4().hex}")
    return app


@pytest.fixture
def make_overlay(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    monkeypatch.setattr(
        "piqopiqo.fullscreen.overlay.atexit.register",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(FullscreenOverlay, "_update_info_panel", lambda self: None)
    overlays = []

    def make(images: list[tuple[int, int, int]], dpr: float) -> FullscreenOverlay:
        items = []
        pixmaps = {}
        for index, (width, height, orientation) in enumerate(images):
            path = f"/virtual/photo-{index}.jpg"
            pixmap = QPixmap(width, height)
            pixmap.fill(QColor("white"))
            pixmaps[path] = pixmap
            items.append(
                SimpleNamespace(
                    path=path,
                    db_metadata={DBFields.ORIENTATION: orientation},
                )
            )

        monkeypatch.setattr(
            FullscreenOverlay,
            "_load_fullscreen_pixmap_with_color_management",
            lambda self: pixmaps[self.image_path],
        )
        overlay = FullscreenOverlay(items, list(range(len(items))), 0)
        overlay.resize(1200, 800)
        overlay._device_pixel_ratio = dpr
        overlays.append(overlay)
        return overlay

    yield make

    for overlay in overlays:
        overlay.close()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _assert_physical_pixel_scale(overlay: FullscreenOverlay, expected: float) -> None:
    # Measure the transformed unit vectors against the viewport's fit scale,
    # independently of the stored zoom multiplier and zoom-state helper.
    base_scale = min(
        overlay.width() / overlay._pixmap.width(),
        overlay.height() / overlay._pixmap.height(),
        1.0 / overlay._device_pixel_ratio,
    )
    origin = overlay._transform.map(QPointF())
    for unit in (QPointF(1.0, 0.0), QPointF(0.0, 1.0)):
        delta = overlay._transform.map(unit) - origin
        physical_scale = (
            math.hypot(delta.x(), delta.y()) * base_scale * overlay._device_pixel_ratio
        )
        assert physical_scale == pytest.approx(expected, abs=1e-6)


def _click_at_center(overlay: FullscreenOverlay) -> None:
    overlay._update_small_image_flag()
    pointer = QPointF(overlay.width() / 2.0, overlay.height() / 2.0)
    overlay.mousePressEvent(
        QMouseEvent(
            QEvent.MouseButtonPress,
            pointer,
            pointer,
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    overlay.mouseReleaseEvent(
        QMouseEvent(
            QEvent.MouseButtonRelease,
            pointer,
            pointer,
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        )
    )


@pytest.mark.parametrize("dpr", [1.0, 2.0])
@pytest.mark.parametrize(
    ("state", "physical_scale"),
    [
        (ZoomState.ZOOM_100, 1.0),
        (ZoomState.ZOOM_200, 2.0),
        (ZoomState.ZOOM_400, 4.0),
        (ZoomState.ZOOM_800, 8.0),
    ],
)
@pytest.mark.parametrize(
    "images",
    [
        [(600, 1800, 1), (1800, 600, 1)],
        [(3600, 2400, 1), (1800, 1200, 1)],
        [(1800, 600, 6), (1800, 600, 1)],
        [(3600, 2400, 1), (160, 120, 1)],
    ],
    ids=["portrait-landscape", "mixed-resolution", "exif-rotation", "small-image"],
)
def test_navigation_preserves_absolute_zoom(
    make_overlay, images, dpr, state, physical_scale
):
    overlay = make_overlay(images, dpr)
    center = overlay._get_zoom_anchor_for_screen_pos(QPointF(600.0, 400.0))
    overlay._zoom_to_state(state, center)
    direction = ZoomDirection.OUT if state == ZoomState.ZOOM_100 else ZoomDirection.IN
    overlay._zoom_direction = direction
    _assert_physical_pixel_scale(overlay, physical_scale)

    # Cover both directions, wraparound, and repeated visits without scale drift.
    for key in [Qt.Key_Right, Qt.Key_Left, Qt.Key_Left, Qt.Key_Right] * 2:
        previous_index = overlay.current_visible_idx
        overlay.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))

        assert overlay.current_visible_idx == 1 - previous_index
        assert overlay._zoom_state == state
        assert overlay._zoom_direction == direction
        _assert_physical_pixel_scale(overlay, physical_scale)


@pytest.mark.parametrize("dpr", [1.0, 2.0])
@pytest.mark.parametrize(
    "destination",
    [(600, 1800, 1), (1800, 600, 1), (1800, 1200, 1), (1800, 600, 8), (160, 120, 1)],
    ids=["portrait", "landscape", "mixed-resolution", "exif-rotation", "small-image"],
)
def test_navigated_100_percent_matches_fresh_click(make_overlay, destination, dpr):
    overlay = make_overlay([(3600, 2400, 1), destination], dpr)
    _click_at_center(overlay)
    assert overlay._zoom_state == ZoomState.ZOOM_100

    overlay._navigate_to_preserve_zoom(1)
    assert overlay._zoom_state == ZoomState.ZOOM_100
    _assert_physical_pixel_scale(overlay, 1.0)
    navigated_transform_scale = overlay._transform.m11()

    overlay._zoom_to_base_view()
    _click_at_center(overlay)

    _assert_physical_pixel_scale(overlay, 1.0)
    assert overlay._transform.m11() == pytest.approx(navigated_transform_scale)


@pytest.mark.parametrize("dpr", [1.0, 2.0])
def test_navigation_preserves_panned_image_center(make_overlay, dpr):
    overlay = make_overlay([(600, 1800, 1), (1800, 600, 1)], dpr)
    overlay._zoom_in(overlay._get_zoom_anchor_for_screen_pos(QPointF(600.0, 400.0)))
    overlay._zoom_in(overlay._get_zoom_anchor_for_screen_pos(QPointF(600.0, 400.0)))
    assert overlay._zoom_state == ZoomState.ZOOM_200

    scale = overlay._zoom_level * overlay._get_base_scale_factor()
    overlay._transform.translate(70.0 / scale, -60.0 / scale)
    overlay._set_allowed_extra_space_from_current()
    overlay._clamp_pan()
    center = overlay._get_image_center_screen_coords()
    assert center.x() == pytest.approx(670.0)
    assert center.y() == pytest.approx(340.0)

    for index in [1, 0, 1, 0]:
        overlay._navigate_to_preserve_zoom(index)
        overlay._clamp_pan()
        current_center = overlay._get_image_center_screen_coords()

        assert current_center.x() == pytest.approx(center.x())
        assert current_center.y() == pytest.approx(center.y())
        _assert_physical_pixel_scale(overlay, 2.0)


@pytest.mark.parametrize("dpr", [1.0, 2.0])
def test_completely_offscreen_destination_returns_to_base_view(make_overlay, dpr):
    overlay = make_overlay([(3600, 2400, 1), (160, 120, 1)], dpr)
    overlay._zoom_in(overlay._get_zoom_anchor_for_screen_pos(QPointF(600.0, 400.0)))
    overlay._position_image_center_at_screen_no_clamp(QPointF(-600.0, 400.0))
    assert overlay._is_image_completely_offscreen() is False
    changed_indices = []
    overlay.index_changed.connect(changed_indices.append)

    overlay._navigate_to_preserve_zoom(1)

    assert overlay._zoom_state == ZoomState.BASE_VIEW
    assert overlay._zoom_level == 1.0
    assert overlay._transform.isIdentity()
    assert overlay._get_image_center_screen_coords() == QPointF(600.0, 400.0)
    assert overlay._is_image_completely_offscreen() is False
    assert all(space == 0 for space in overlay._allowed_extra_space.values())
    assert changed_indices == [1]
    _assert_physical_pixel_scale(overlay, 1.0)


@pytest.mark.parametrize("dpr", [1.0, 2.0])
def test_base_view_navigation_keeps_fit_and_center(make_overlay, dpr):
    overlay = make_overlay([(600, 1800, 1), (1800, 600, 1), (160, 120, 1)], dpr)

    for index in [1, 2, 0, 2, 1, 0]:
        overlay._navigate_to_preserve_zoom(index)

        assert overlay._zoom_state == ZoomState.BASE_VIEW
        assert overlay._zoom_level == 1.0
        assert overlay._transform.isIdentity()
        assert overlay._get_image_center_screen_coords() == QPointF(600.0, 400.0)
        image_rect = overlay._get_image_rect_in_screen_coords()
        assert image_rect.width() <= overlay.width()
        assert image_rect.height() <= overlay.height()


@pytest.mark.parametrize("dpr", [1.0, 2.0])
def test_ejecting_current_image_preserves_destination_zoom(make_overlay, dpr):
    overlay = make_overlay([(3600, 2400, 1), (1800, 1200, 1)], dpr)
    _click_at_center(overlay)

    result = overlay.eject_current_from_loop()

    assert result["auto_close"] is False
    assert result["current_path"] == "/virtual/photo-1.jpg"
    assert overlay._zoom_state == ZoomState.ZOOM_100
    _assert_physical_pixel_scale(overlay, 1.0)
