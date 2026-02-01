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
    is_small_image: bool,
) -> ZoomState | None:
    """Get the next zoom state in the given direction.

    For small images, BASE_VIEW is the same as ZOOM_100, so we skip ZOOM_100
    when zooming in from base view.

    Args:
        current_state: The current zoom state
        direction: The zoom direction (IN or OUT)
        is_small_image: True if image fits on screen without scaling

    Returns:
        The next zoom state, or None if we can't zoom further in that direction.
    """
    current_idx = ZOOM_STATE_ORDER.index(current_state)

    if direction == ZoomDirection.IN:
        # For small images at base view, skip ZOOM_100 (go directly to ZOOM_200)
        if is_small_image and current_state == ZoomState.BASE_VIEW:
            return ZoomState.ZOOM_200

        if current_idx < len(ZOOM_STATE_ORDER) - 1:
            return ZOOM_STATE_ORDER[current_idx + 1]

    elif direction == ZoomDirection.OUT:
        if current_idx > 0:
            next_state = ZOOM_STATE_ORDER[current_idx - 1]
            # For small images, ZOOM_100 is the same as BASE_VIEW
            if is_small_image and next_state == ZoomState.ZOOM_100:
                return ZoomState.BASE_VIEW
            return next_state

    return None


def should_show_zoom_overlay(
    zoom_state: ZoomState,
    zoom_direction: ZoomDirection,
    is_small_image: bool,
) -> bool:
    """Determine if the zoom overlay should be shown based on current state.

    Rules:
    - Never show in base view (initial or zooming back to it) for large images
    - For 100%: only show when zooming OUT (coming back from higher zoom)
    - For small images at base view (which is 100%): show when going back from
      further zoom
    - Always show for 200%, 400%, 800%

    Args:
        zoom_state: Current zoom state
        zoom_direction: Current zoom direction
        is_small_image: True if image fits on screen without scaling

    Returns:
        True if overlay should be shown
    """
    if zoom_state == ZoomState.BASE_VIEW:
        # For small images, base view IS 100%, so show when zooming out to it
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
