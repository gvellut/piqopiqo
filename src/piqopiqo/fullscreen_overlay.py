"""Backward compatibility: re-export from fullscreen/."""

from .fullscreen.overlay import FullscreenOverlay
from .fullscreen.zoom import ZoomDirection, ZoomState

__all__ = ["FullscreenOverlay", "ZoomDirection", "ZoomState"]
