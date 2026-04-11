"""Folder watching and workspace refresh utilities."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import logging
import os
import threading
import time

from attrs import define
from PySide6.QtCore import QObject, Signal
from watchfiles import watch

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


@define(frozen=True)
class WorkspaceFileState:
    mtime_ns: int
    size: int


def _is_image_path(path: str) -> bool:
    return path.lower().endswith(_IMAGE_EXTENSIONS)


def _iter_image_changes(
    changes: Iterable[tuple[object, str]],
) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for change, path in changes:
        if not isinstance(path, str):
            continue
        if not _is_image_path(path):
            continue

        kind = getattr(change, "name", None)
        if not isinstance(kind, str):
            kind = str(change)
        results.append((kind, path))
    return results


def build_file_snapshot(file_paths: Iterable[str]) -> dict[str, WorkspaceFileState]:
    snapshot: dict[str, WorkspaceFileState] = {}
    for file_path in file_paths:
        if not isinstance(file_path, str) or not _is_image_path(file_path):
            continue
        try:
            stat = os.stat(file_path)
        except OSError:
            continue
        snapshot[file_path] = WorkspaceFileState(
            mtime_ns=int(getattr(stat, "st_mtime_ns", 0)),
            size=int(getattr(stat, "st_size", 0)),
        )
    return snapshot


def scan_workspace_snapshot(root_folder: str | None) -> dict[str, WorkspaceFileState]:
    if not root_folder or not os.path.isdir(root_folder):
        return {}

    snapshot: dict[str, WorkspaceFileState] = {}
    for root, _, files in os.walk(root_folder):
        for file_name in files:
            if not _is_image_path(file_name):
                continue
            file_path = os.path.join(root, file_name)
            try:
                stat = os.stat(file_path)
            except OSError:
                continue
            snapshot[file_path] = WorkspaceFileState(
                mtime_ns=int(getattr(stat, "st_mtime_ns", 0)),
                size=int(getattr(stat, "st_size", 0)),
            )
    return snapshot


def normalize_workspace_changes(
    changes: Iterable[tuple[str, str]],
) -> list[tuple[str, str]]:
    added: set[str] = set()
    deleted: set[str] = set()
    modified: set[str] = set()

    for kind, path in changes:
        if not isinstance(path, str) or not path:
            continue
        kind_lower = str(kind).lower()
        if "added" in kind_lower:
            added.add(path)
        elif "deleted" in kind_lower or "removed" in kind_lower:
            deleted.add(path)
        elif "modified" in kind_lower:
            modified.add(path)

    effective_modified = modified - added - deleted
    normalized: list[tuple[str, str]] = []
    normalized.extend(("deleted", path) for path in sorted(deleted))
    normalized.extend(("added", path) for path in sorted(added))
    normalized.extend(("modified", path) for path in sorted(effective_modified))
    return normalized


def diff_workspace_snapshots(
    previous: dict[str, WorkspaceFileState],
    current: dict[str, WorkspaceFileState],
) -> list[tuple[str, str]]:
    previous_paths = set(previous)
    current_paths = set(current)

    changes: list[tuple[str, str]] = []
    changes.extend(("deleted", path) for path in sorted(previous_paths - current_paths))
    changes.extend(("added", path) for path in sorted(current_paths - previous_paths))

    modified = sorted(
        path
        for path in (previous_paths & current_paths)
        if previous[path] != current[path]
    )
    changes.extend(("modified", path) for path in modified)
    return changes


class FolderWatcher(QObject):
    changes_detected = Signal(list)  # list[tuple[str, str]] (kind, path)

    def __init__(self, root_folder: str, parent=None):
        super().__init__(parent)
        self._root_folder = root_folder
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
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
        for changes in watch(
            self._root_folder,
            stop_event=self._stop_event,
            recursive=True,
        ):
            image_changes = _iter_image_changes(changes)
            if image_changes:
                self.changes_detected.emit(image_changes)


class WorkspaceWatcherController(QObject):
    """Owns watchfiles integration, suppression, suspension, and refresh diffing."""

    def __init__(
        self,
        apply_changes: Callable[[list[tuple[str, str]]], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._apply_changes = apply_changes
        self._root_folder: str | None = None
        self._snapshot: dict[str, WorkspaceFileState] = {}
        self._watcher: FolderWatcher | None = None
        self._suppressed_paths: dict[str, float] = {}
        self._suspended = False

    def set_workspace(
        self,
        root_folder: str | None,
        file_paths: Iterable[str],
    ) -> None:
        self.stop()
        self._root_folder = root_folder
        self._snapshot = build_file_snapshot(file_paths)
        self._suppressed_paths.clear()
        self._suspended = False

    def clear_workspace(self) -> None:
        self.stop()
        self._root_folder = None
        self._snapshot = {}
        self._suppressed_paths.clear()
        self._suspended = False

    def start(self) -> None:
        if not self._root_folder or self._suspended:
            return

        self.stop()
        watcher = FolderWatcher(self._root_folder, parent=self)
        watcher.changes_detected.connect(self._on_watcher_changes)
        watcher.start()
        self._watcher = watcher

    def stop(self) -> None:
        watcher = self._watcher
        self._watcher = None
        if watcher is None:
            return

        try:
            watcher.changes_detected.disconnect(self._on_watcher_changes)
        except RuntimeError:
            pass

        watcher.stop(timeout_s=1.0)

    def suppress_paths(self, paths: list[str], duration_s: float = 2.0) -> None:
        expiry = time.monotonic() + max(0.0, float(duration_s))
        for path in paths:
            self._suppressed_paths[path] = expiry

    def clear_suppressed(self) -> None:
        self._suppressed_paths.clear()

    def suspend(self) -> None:
        if not self._root_folder or self._suspended:
            return

        self._suspended = True
        self.stop()

    def resume_and_refresh(self) -> None:
        if not self._root_folder:
            self._suspended = False
            return

        current_snapshot = scan_workspace_snapshot(self._root_folder)
        changes = diff_workspace_snapshots(self._snapshot, current_snapshot)
        self._snapshot = current_snapshot
        self._suspended = False

        if changes:
            self._apply_changes(changes)

        self.start()

    def _on_watcher_changes(self, changes: list[tuple[str, str]]) -> None:
        if not changes:
            return

        now = time.monotonic()
        self._suppressed_paths = {
            path: until
            for path, until in self._suppressed_paths.items()
            if until > now
        }

        normalized = normalize_workspace_changes(changes)
        dispatched: list[tuple[str, str]] = []
        touched_paths: set[str] = set()

        for kind, path in normalized:
            touched_paths.add(path)
            if path in self._suppressed_paths:
                continue
            dispatched.append((kind, path))

        self._apply_snapshot_updates(touched_paths)

        if dispatched:
            self._apply_changes(dispatched)

    def _apply_snapshot_updates(self, paths: set[str]) -> None:
        for path in paths:
            try:
                stat = os.stat(path)
            except OSError:
                self._snapshot.pop(path, None)
                continue
            self._snapshot[path] = WorkspaceFileState(
                mtime_ns=int(getattr(stat, "st_mtime_ns", 0)),
                size=int(getattr(stat, "st_size", 0)),
            )
