"""Utility functions for status labels."""

from __future__ import annotations

from piqopiqo.config import Config


def get_label_color(label: str) -> str | None:
    """Get color hex for a label name from STATUS_LABELS.

    Args:
        label: The label name to look up.

    Returns:
        The color hex string, or None if not found.
    """
    for sl in Config.STATUS_LABELS:
        if sl.name == label:
            return sl.color
    return None
