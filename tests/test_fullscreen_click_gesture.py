"""Tests for fullscreen click vs pan gesture classification."""

from PySide6.QtCore import QPointF

from piqopiqo.fullscreen.overlay import (
    _PAN_GESTURE_DISTANCE_THRESHOLD_PX,
    _classify_release_click_zoom_out,
    _did_cross_pan_threshold,
    _should_activate_pan_cursor,
)


def test_release_zoom_out_allowed_when_no_pan_and_not_just_zoomed():
    should_zoom_out, outcome = _classify_release_click_zoom_out(
        did_pan=False,
        just_zoomed_in=False,
        pan_mode_active=False,
    )

    assert should_zoom_out is True
    assert outcome == "zoom_out"


def test_release_zoom_out_blocked_when_pan_happened():
    should_zoom_out, outcome = _classify_release_click_zoom_out(
        did_pan=True,
        just_zoomed_in=False,
        pan_mode_active=False,
    )

    assert should_zoom_out is False
    assert outcome == "suppressed:did_pan"


def test_release_zoom_out_blocked_when_press_just_zoomed_in():
    should_zoom_out, outcome = _classify_release_click_zoom_out(
        did_pan=False,
        just_zoomed_in=True,
        pan_mode_active=False,
    )

    assert should_zoom_out is False
    assert outcome == "suppressed:just_zoomed_in"


def test_release_zoom_out_not_blocked_by_pan_mode_alone():
    should_zoom_out, outcome = _classify_release_click_zoom_out(
        did_pan=False,
        just_zoomed_in=False,
        pan_mode_active=True,
    )

    assert should_zoom_out is True
    assert outcome == "zoom_out"


def test_pan_threshold_below_limit_does_not_count_as_pan():
    delta = QPointF(_PAN_GESTURE_DISTANCE_THRESHOLD_PX - 0.1, 0.0)
    assert _did_cross_pan_threshold(delta) is False


def test_pan_threshold_at_limit_counts_as_pan():
    delta = QPointF(_PAN_GESTURE_DISTANCE_THRESHOLD_PX, 0.0)
    assert _did_cross_pan_threshold(delta) is True


def test_pan_cursor_activation_requires_actual_pan():
    assert (
        _should_activate_pan_cursor(
            panning=True,
            did_pan=False,
            pan_mode_active=False,
        )
        is False
    )
    assert (
        _should_activate_pan_cursor(
            panning=True,
            did_pan=True,
            pan_mode_active=False,
        )
        is True
    )
