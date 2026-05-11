"""Shared helpers for Qt worker runnables."""

from __future__ import annotations

from PySide6.QtCore import QRunnable


class PythonOwnedRunnable(QRunnable):
    """QRunnable whose lifetime is owned by Python instead of Qt."""

    def __init__(self) -> None:
        super().__init__()
        self.setAutoDelete(False)
