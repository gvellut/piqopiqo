"""Backward compatibility: re-export from components/."""

from .components import EllidedLabel, MetadataSaveWorker, get_label_color

__all__ = ["EllidedLabel", "get_label_color", "MetadataSaveWorker"]
