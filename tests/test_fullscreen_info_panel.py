"""Tests for fullscreen information and zoom overlays."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import uuid

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor, QKeyEvent, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QWidget
import pytest

from piqopiqo.fullscreen.info_panel import ZoomOverlayController
from piqopiqo.fullscreen.overlay import FullscreenOverlay
from piqopiqo.fullscreen.zoom import ZoomDirection, ZoomState
from piqopiqo.main_window import MainWindow
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
    core.setApplicationName(f"piqopiqo-test-fullscreen-info-{uuid.uuid4().hex}")
    return app


@pytest.fixture
def make_overlay(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_INFO_PANEL_RANK_FONT_SIZE", raising=False)
    monkeypatch.setenv("PIQO_INFO_PANEL_POSITION", "bottom")
    monkeypatch.setenv("PIQO_INFO_PANEL_MARGIN_BOTTOM", "10")
    monkeypatch.setenv("PIQO_INFO_PANEL_MARGIN_SIDE", "10")
    monkeypatch.setenv("PIQO_INFO_PANEL_TEXT_COLOR", "#73bfee")
    pixmap = QPixmap(160, 120)
    pixmap.fill(QColor("white"))
    monkeypatch.setattr(
        "piqopiqo.fullscreen.overlay.atexit.register", lambda *_args: None
    )
    monkeypatch.setattr(
        FullscreenOverlay,
        "_load_fullscreen_pixmap_with_color_management",
        lambda self: pixmap,
    )
    overlays = []

    def make(visible_indices, start_index):
        init_qsettings_store(dyn=True)
        items = [
            SimpleNamespace(
                path=f"/virtual/photo-{index}.jpg",
                db_metadata={DBFields.TIME_TAKEN: datetime(2026, 1, 1)},
            )
            for index in range(5)
        ]
        overlay = FullscreenOverlay(items, visible_indices, start_index)
        overlays.append(overlay)
        overlay.resize(1200, 800)
        overlay._position_info_panel()
        overlay.show()
        qapp.processEvents()
        return overlay

    yield make

    for overlay in overlays:
        overlay.close()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.mark.parametrize(
    ("loop", "start", "rank"),
    [([0, 1, 2, 3, 4], 2, "#3"), ([1, 3, 4], 1, "#1")],
)
def test_initial_rank_uses_active_loop(make_overlay, loop, start, rank):
    overlay = make_overlay(loop, start)

    assert overlay.rank_label.text() == rank
    assert overlay.filename_label.text() == f"photo-{start}.jpg"


def test_rank_follows_navigation_and_wraparound(make_overlay):
    overlay = make_overlay([1, 3, 4], 1)

    for key, filename, rank in [
        (Qt.Key_Right, "photo-3.jpg", "#2"),
        (Qt.Key_Right, "photo-4.jpg", "#3"),
        (Qt.Key_Right, "photo-1.jpg", "#1"),
        (Qt.Key_Left, "photo-4.jpg", "#3"),
        (Qt.Key_Left, "photo-3.jpg", "#2"),
    ]:
        overlay.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))

        assert overlay.rank_label.text() == rank
        assert overlay.filename_label.text() == filename


@pytest.mark.parametrize(
    ("start", "filename", "rank"),
    [(2, "photo-3.jpg", "#3"), (4, "photo-3.jpg", "#4")],
)
def test_rank_stays_contiguous_after_ejection(make_overlay, start, filename, rank):
    overlay = make_overlay([0, 1, 2, 3, 4], start)

    result = overlay.eject_current_from_loop()

    assert result["auto_close"] is False
    assert overlay.rank_label.text() == rank
    assert overlay.filename_label.text() == filename
    assert f"/virtual/photo-{start}.jpg" not in overlay.get_visible_paths()

    # Moving backward and forward still uses the compacted loop.
    overlay._navigate_to_preserve_zoom(overlay.current_visible_idx - 1)
    assert overlay.rank_label.text() == f"#{int(rank[1:]) - 1}"
    overlay._navigate_to_preserve_zoom(overlay.current_visible_idx + 1)
    assert overlay.rank_label.text() == rank
    assert overlay.filename_label.text() == filename


def test_ejecting_only_photo_closes_real_overlay(make_overlay):
    overlay = make_overlay([3], 3)
    assert overlay.rank_label.text() == "#1"
    closed = []
    overlay.about_to_close.connect(lambda: closed.append(True))
    window = SimpleNamespace(
        _fullscreen_overlay=overlay,
        _capture_fullscreen_selection_state=lambda *_args, **_kwargs: {},
        _apply_live_grid_selection_from_fullscreen=lambda _state: None,
    )

    MainWindow._on_fullscreen_eject_from_loop_requested(window)

    assert closed == [True]
    assert overlay.isVisible() is False
    assert overlay.get_visible_paths() == []


@pytest.mark.parametrize("replace_items", [False, True])
def test_rebinding_updates_rank_when_current_photo_survives(
    make_overlay, replace_items
):
    overlay = make_overlay([1, 3, 4], 3)
    assert overlay.rank_label.text() == "#2"
    current_path = overlay.get_current_path()
    paths = ["/virtual/photo-3.jpg", "/virtual/photo-4.jpg"]

    if replace_items:
        items = [item for item in overlay.all_items if item.path in paths]
        rebound = overlay.rebind_to_items_and_paths(items, paths, current_path)
    else:
        rebound = overlay.rebind_to_paths(paths, current_path)

    assert rebound is True
    assert overlay.get_current_path() == current_path
    assert overlay.rank_label.text() == "#1"
    overlay._navigate_to_preserve_zoom(1)
    assert overlay.rank_label.text() == "#2"
    assert overlay.get_current_path() == "/virtual/photo-4.jpg"


@pytest.mark.parametrize("fail_on_entry", [False, True])
def test_rank_updates_even_if_image_cannot_be_decoded(
    make_overlay, monkeypatch, fail_on_entry
):
    if fail_on_entry:
        monkeypatch.setattr(
            FullscreenOverlay,
            "_load_fullscreen_pixmap_with_color_management",
            lambda self: QPixmap(),
        )
    overlay = make_overlay([1, 3, 4], 3 if fail_on_entry else 1)
    if not fail_on_entry:
        monkeypatch.setattr(
            FullscreenOverlay,
            "_load_fullscreen_pixmap_with_color_management",
            lambda self: QPixmap(),
        )
        overlay._navigate_to_preserve_zoom(1)

    assert overlay.rank_label.text() == "#2"
    assert overlay.filename_label.text() == "photo-3.jpg"
    assert overlay._pixmap.isNull()


def test_rank_styling_and_panel_growth(make_overlay, monkeypatch):
    overlay = make_overlay([0, 1, 2, 3, 4], 0)
    panel = overlay.info_panel
    rank = overlay.rank_label

    assert panel.layout().itemAt(0).widget() is rank
    assert panel.layout().itemAt(1).widget() is overlay.color_swatch
    assert rank.alignment() & Qt.AlignLeft
    assert rank.font().pointSize() == 18
    assert rank.palette().color(QPalette.WindowText) == QColor("#73bfee")
    assert rank.geometry().bottom() < overlay.color_swatch.y()
    assert rank.height() >= rank.sizeHint().height()
    assert panel.x() == 10
    assert panel.y() + panel.height() == overlay.height() - 10

    monkeypatch.setenv("PIQO_INFO_PANEL_RANK_FONT_SIZE", "36")
    larger = make_overlay([0, 1, 2, 3, 4], 0)

    assert larger.rank_label.font().pointSize() == 36
    assert larger.info_panel.height() > panel.height()
    assert larger.info_panel.y() < panel.y()
    assert (
        larger.info_panel.y() + larger.info_panel.height() == panel.y() + panel.height()
    )


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
