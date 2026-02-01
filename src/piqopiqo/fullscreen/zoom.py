"""Zoom state and helper functions for fullscreen overlay."""

from __future__ import annotations

from enum import Enum, auto


class ZoomState(Enum):
    """Enum for discrete zoom states."""

    BASE_VIEW = auto()  # Fit to screen (can be <100% for large, or 100% for small)
    ZOOM_100 = auto()  # 1:1 pixel mapping (1 image pixel = 1 render buffer pixel)
    ZOOM_200 = auto()  # 2x zoom (1 image pixel = 2 render buffer pixels)
    ZOOM_400 = auto()  # 4x zoom (1 image pixel = 4 render buffer pixels)
    ZOOM_800 = auto()  # 8x zoom (1 image pixel = 8 render buffer pixels)


class ZoomDirection(Enum):
    """Enum for zoom direction tracking."""

    NONE = auto()  # Initial state or reset
    IN = auto()  # Zooming in
    OUT = auto()  # Zooming out


# Zoom state progression for wheel/keyboard
ZOOM_STATE_ORDER = [
    ZoomState.BASE_VIEW,
    ZoomState.ZOOM_100,
    ZoomState.ZOOM_200,
    ZoomState.ZOOM_400,
    ZoomState.ZOOM_800,
]

# Mapping from zoom state to display percentage
ZOOM_STATE_PERCENTAGES = {
    ZoomState.ZOOM_100: 100,
    ZoomState.ZOOM_200: 200,
    ZoomState.ZOOM_400: 400,
    ZoomState.ZOOM_800: 800,
}


def get_zoom_level_for_state(
    state: ZoomState,
    base_scale: float,
    device_pixel_ratio: float,
) -> float:
    """Calculate the zoom level for a given zoom state.

    The zoom level is the multiplier applied to the transform on top of base_scale.
    For ZOOM_100, we want 1 image pixel = 1 render buffer pixel.

    Args:
        state: The target zoom state
        base_scale: The scale factor to fit image to screen
        device_pixel_ratio: The screen's device pixel ratio

    Returns:
        The zoom_level value that achieves the desired pixel mapping.
    """
    if state == ZoomState.BASE_VIEW:
        return 1.0

    # For ZoomState.ZOOM_100: 1 image pixel = 1 render buffer pixel
    # render_buffer_pixel = image_pixel * base_scale * zoom_level * dpr
    # For 100%: 1 = 1 * base_scale * zoom_level * dpr
    # zoom_level = 1 / (base_scale * dpr)
    one_to_one_zoom = 1.0 / (base_scale * device_pixel_ratio)

    if state == ZoomState.ZOOM_100:
        return one_to_one_zoom
    elif state == ZoomState.ZOOM_200:
        return one_to_one_zoom * 2
    elif state == ZoomState.ZOOM_400:
        return one_to_one_zoom * 4
    elif state == ZoomState.ZOOM_800:
        return one_to_one_zoom * 8

    return 1.0


def get_next_zoom_state(
    current_state: ZoomState,
    direction: ZoomDirection,
    base_scale: float,
    device_pixel_ratio: float,
) -> ZoomState | None:
    """Get the next zoom state in the given direction.

    When zooming in from BASE_VIEW, skips any states that would not provide
    actual magnification (zoom_level <= 1.0). This happens for small images
    where BASE_VIEW already shows the image at or above 1:1 render buffer size.

    Args:
        current_state: The current zoom state
        direction: The zoom direction (IN or OUT)
        base_scale: The scale factor to fit image to screen
        device_pixel_ratio: The screen's device pixel ratio

    Returns:
        The next zoom state, or None if we can't zoom further in that direction.
    """
    current_idx = ZOOM_STATE_ORDER.index(current_state)

    if direction == ZoomDirection.IN:
        # Find the next state that provides actual magnification
        for next_idx in range(current_idx + 1, len(ZOOM_STATE_ORDER)):
            next_state = ZOOM_STATE_ORDER[next_idx]
            next_zoom_level = get_zoom_level_for_state(
                next_state, base_scale, device_pixel_ratio
            )
            # Skip states that don't provide magnification over BASE_VIEW
            if next_zoom_level > 1.0:
                return next_state
        return None

    elif direction == ZoomDirection.OUT:
        # Find the previous state
        for next_idx in range(current_idx - 1, -1, -1):
            next_state = ZOOM_STATE_ORDER[next_idx]
            if next_state == ZoomState.BASE_VIEW:
                return ZoomState.BASE_VIEW
            next_zoom_level = get_zoom_level_for_state(
                next_state, base_scale, device_pixel_ratio
            )
            # Skip states that are >= BASE_VIEW (zoom_level <= 1.0)
            if next_zoom_level > 1.0:
                return next_state
        # If all intermediate states are skipped, go to BASE_VIEW
        return ZoomState.BASE_VIEW

    return None


def should_show_zoom_overlay(
    zoom_state: ZoomState,
    zoom_direction: ZoomDirection,
    base_scale: float,
    device_pixel_ratio: float,
) -> bool:
    """Determine if the zoom overlay should be shown based on current state.

    Rules:
    - Never show in base view for large images
    - For small images at base view: show when zooming out (it's effectively 100%+)
    - For ZOOM_100: only show when zooming OUT (coming back from higher zoom)
    - Always show for states that provide actual magnification (zoom_level > 1.0)

    Args:
        zoom_state: Current zoom state
        zoom_direction: Current zoom direction
        base_scale: The scale factor to fit image to screen
        device_pixel_ratio: The screen's device pixel ratio

    Returns:
        True if overlay should be shown
    """
    is_small_image = base_scale * device_pixel_ratio >= 1.0

    if zoom_state == ZoomState.BASE_VIEW:
        # For small images, base view is >= 100%, so show when zooming out to it
        if is_small_image and zoom_direction == ZoomDirection.OUT:
            return True
        # Never show overlay in base view for large images
        return False

    if zoom_state == ZoomState.ZOOM_100:
        # Only show 100% when zooming out to it (not zooming in from base)
        return zoom_direction == ZoomDirection.OUT

    # Always show for 200%, 400%, 800%
    return zoom_state in (
        ZoomState.ZOOM_200,
        ZoomState.ZOOM_400,
        ZoomState.ZOOM_800,
    )
