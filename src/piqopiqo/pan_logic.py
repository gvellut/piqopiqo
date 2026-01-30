"""Pure functions for pan boundary calculations.

This module contains the logic for calculating allowed empty space around
images during panning in fullscreen overlay. The functions are extracted
to allow easy unit testing without requiring Qt widgets.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SideSpaces:
    """Empty space on each side of an image."""

    left: float
    right: float
    top: float
    bottom: float

    def as_dict(self) -> dict[str, float]:
        return {
            "left": self.left,
            "right": self.right,
            "top": self.top,
            "bottom": self.bottom,
        }

    @classmethod
    def from_dict(cls, d: dict[str, float]) -> SideSpaces:
        return cls(
            left=d.get("left", 0),
            right=d.get("right", 0),
            top=d.get("top", 0),
            bottom=d.get("bottom", 0),
        )


def calculate_effective_space_per_side(
    allowed_extra: dict[str, float],
    base_space: float,
) -> dict[str, float]:
    """Calculate the effective allowed empty space for each side.

    Takes the maximum of base_space (PAN_EMPTY_SPACE) and the per-side
    allowed extra space. This allows larger space on sides where it was
    larger at image load time.

    Args:
        allowed_extra: Per-side extra space allowance (beyond base_space)
        base_space: The base PAN_EMPTY_SPACE value

    Returns:
        Dict with effective allowed space for each side
    """
    return {
        side: max(base_space, allowed_extra.get(side, 0) + base_space)
        for side in ["left", "right", "top", "bottom"]
    }


def calculate_allowed_extra_from_current(
    current_space: dict[str, float],
    base_space: float,
) -> dict[str, float]:
    """Calculate allowed extra space based on current image position.

    For each side, if the current space exceeds base_space,
    the difference becomes the allowed extra space for that side.

    Args:
        current_space: Current empty space on each side
        base_space: The base PAN_EMPTY_SPACE value

    Returns:
        Dict with allowed extra space for each side
    """
    return {
        side: max(0, space - base_space) if space > base_space else 0
        for side, space in current_space.items()
    }


def update_allowed_extra_after_pan(
    current_space: dict[str, float],
    allowed_extra: dict[str, float],
    base_space: float,
) -> dict[str, float]:
    """Update allowed extra space after panning.

    If panning has reduced the space on any side below base_space,
    that side's extra allowance is reset to 0.

    Args:
        current_space: Current empty space on each side
        allowed_extra: Current per-side extra space allowance
        base_space: The base PAN_EMPTY_SPACE value

    Returns:
        Updated dict with allowed extra space for each side
    """
    result = dict(allowed_extra)
    for side, space in current_space.items():
        if space < base_space:
            result[side] = 0
    return result


def is_image_visible(
    img_left: float,
    img_right: float,
    img_top: float,
    img_bottom: float,
    view_width: float,
    view_height: float,
) -> bool:
    """Check if any part of the image is visible in the view.

    Args:
        img_left: Left edge of image in screen coordinates
        img_right: Right edge of image in screen coordinates
        img_top: Top edge of image in screen coordinates
        img_bottom: Bottom edge of image in screen coordinates
        view_width: Width of the view
        view_height: Height of the view

    Returns:
        True if any part of the image intersects the view
    """
    # Check for no intersection
    if img_right <= 0 or img_left >= view_width:
        return False
    if img_bottom <= 0 or img_top >= view_height:
        return False
    return True


def calculate_current_space(
    img_left: float,
    img_right: float,
    img_top: float,
    img_bottom: float,
    view_width: float,
    view_height: float,
) -> dict[str, float]:
    """Calculate empty space on each side.

    Args:
        img_left: Left edge of image in screen coordinates
        img_right: Right edge of image in screen coordinates
        img_top: Top edge of image in screen coordinates
        img_bottom: Bottom edge of image in screen coordinates
        view_width: Width of the view
        view_height: Height of the view

    Returns:
        Dict with empty space on each side (positive = empty space)
    """
    return {
        "left": img_left,
        "right": view_width - img_right,
        "top": img_top,
        "bottom": view_height - img_bottom,
    }
