"""Fullscreen overlay module for displaying images at full resolution."""

from .overlay import FullscreenOverlay
from .pan import (
    SideSpaces,
    calculate_allowed_extra_from_current,
    calculate_current_space,
    calculate_effective_space_per_side,
    is_image_visible,
    update_allowed_extra_after_pan,
)
from .zoom import ZoomDirection, ZoomState

__all__ = [
    "FullscreenOverlay",
    "SideSpaces",
    "ZoomDirection",
    "ZoomState",
    "calculate_allowed_extra_from_current",
    "calculate_current_space",
    "calculate_effective_space_per_side",
    "is_image_visible",
    "update_allowed_extra_after_pan",
]
