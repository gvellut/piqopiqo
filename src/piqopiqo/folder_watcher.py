"""Folder watcher based on watchfiles.

Runs in a Python thread (not QThread) and emits Qt signals with file changes.
"""

from __future__ import annotations

from collections.abc import Iterable
import logging
import threading

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

try:
    from watchfiles import Change, watch
except ImportError:  # pragma: no cover
    Change = None
    watch = None


def _iter_image_changes(
    changes: Iterable[tuple[object, str]],
) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for change, path in changes:
        if not isinstance(path, str):
            continue
        lower = path.lower()
        if not lower.endswith((".jpg", ".jpeg", ".png")):
            continue

        kind = getattr(change, "name", None)
        if not isinstance(kind, str):
            kind = str(change)
        results.append((kind, path))
    return results


class FolderWatcher(QObject):
    changes_detected = Signal(list)  # list[tuple[str, str]] (kind, path)

    def __init__(self, root_folder: str, parent=None):
        super().__init__(parent)
        self._root_folder = root_folder
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if watch is None:
            logger.warning("watchfiles is not installed; folder watching is disabled")
            return

        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 1.0) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=float(timeout_s))
        self._thread = None

    def _run(self) -> None:  # pragma: no cover
        assert watch is not None

        for changes in watch(
            self._root_folder,
            stop_event=self._stop_event,
            recursive=True,
        ):
            image_changes = _iter_image_changes(changes)
            if image_changes:
                self.changes_detected.emit(image_changes)
