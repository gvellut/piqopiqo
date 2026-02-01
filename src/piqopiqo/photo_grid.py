"""Backward compatibility: re-export from grid/ and main_window."""

from .grid import PagedPhotoGrid, PhotoCell
from .main_window import MainWindow

__all__ = ["MainWindow", "PagedPhotoGrid", "PhotoCell"]
