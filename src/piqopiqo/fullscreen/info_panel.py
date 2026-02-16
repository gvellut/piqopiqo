"""Info panel and zoom overlay visibility logic for fullscreen overlay.

This module handles:
- Determining when to show the zoom level overlay based on state
- Managing the visibility state and timers for overlays
- The logic is extracted from overlay.py to separate concerns
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer

from .zoom import ZOOM_STATE_PERCENTAGES, ZoomDirection, ZoomState

if TYPE_CHECKING:
    from PySide6.QtWidgets import QLabel


@dataclass
class ZoomDisplayState:
    """Tracks the current state relevant for zoom overlay display decisions."""

    zoom_state: ZoomState = ZoomState.BASE_VIEW
    zoom_direction: ZoomDirection = ZoomDirection.NONE
    is_small_image: bool = False


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


class ZoomOverlayController:
    """Controls the visibility and content of the zoom level overlay.

    This class manages:
    - When to show/hide the zoom overlay based on zoom state changes
    - Auto-hide timer for the zoom percent overlay
    - Immediate hiding when returning to base view (no lingering)
    """

    def __init__(
        self,
        overlay_widget: QLabel,
        timer_ms: int,
        get_base_scale: Callable[[], float],
        get_device_pixel_ratio: Callable[[], float],
        update_overlay_position: Callable[[], None],
    ):
        """Initialize the controller.

        Args:
            overlay_widget: The QLabel widget displaying zoom percentage
            timer_ms: Duration in ms before auto-hiding the zoom percent overlay
            get_base_scale: Callback to get current base scale factor
            get_device_pixel_ratio: Callback to get device pixel ratio
            update_overlay_position: Callback to update overlay position/text
        """
        self._overlay = overlay_widget
        self._timer_ms = timer_ms
        self._get_base_scale = get_base_scale
        self._get_device_pixel_ratio = get_device_pixel_ratio
        self._update_overlay_position = update_overlay_position

        self._visible = False

        # Auto-hide timer
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timer_expired)

    def on_zoom_state_changed(
        self,
        zoom_state: ZoomState,
        zoom_direction: ZoomDirection,
    ) -> None:
        """Called when the zoom state changes.

        Determines whether to show, hide, or update the overlay.

        Args:
            zoom_state: The new zoom state
            zoom_direction: The direction of the zoom change
        """
        # When returning to base view, IMMEDIATELY hide the overlay
        # This prevents the "100% lingering" issue when unzooming quickly
        if zoom_state == ZoomState.BASE_VIEW:
            # Check if this is a small image (base view = 100%)
            base_scale = self._get_base_scale()
            dpr = self._get_device_pixel_ratio()
            is_small_image = base_scale * dpr >= 1.0

            if is_small_image and zoom_direction == ZoomDirection.OUT:
                # Small image zooming out to base view (which IS 100%)
                # Show the overlay briefly
                self._show_overlay(zoom_state)
            else:
                # Large image returning to base view - hide immediately
                self._hide_immediately()
            return

        # Check if we should show the overlay for this state
        if should_show_zoom_overlay(
            zoom_state,
            zoom_direction,
            self._get_base_scale(),
            self._get_device_pixel_ratio(),
        ):
            self._show_overlay(zoom_state)
        else:
            # Don't show for this state, but don't hide existing either
            # (let timer run if it was already shown)
            pass

    def _show_overlay(self, zoom_state: ZoomState) -> None:
        """Show the overlay with the given zoom percentage."""
        percentage = ZOOM_STATE_PERCENTAGES.get(zoom_state)
        if percentage is None:
            return

        self._overlay.setText(f"{percentage}%")
        self._overlay.adjustSize()
        self._update_overlay_position()
        self._overlay.show()
        self._visible = True

        # Start/restart the auto-hide timer
        self._timer.start(self._timer_ms)

    def _hide_immediately(self) -> None:
        """Hide the overlay immediately and cancel any pending timer."""
        self._timer.stop()
        self._overlay.hide()
        self._visible = False

    def _on_timer_expired(self) -> None:
        """Called when the auto-hide timer expires."""
        self._overlay.hide()
        self._visible = False

    def hide(self) -> None:
        """Public method to hide the overlay immediately."""
        self._hide_immediately()

    @property
    def is_visible(self) -> bool:
        """Whether the overlay is currently visible."""
        return self._visible
