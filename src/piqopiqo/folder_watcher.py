"""Folder watching and workspace refresh utilities."""

from __future__ import annotations

from collections import defaultdict
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
    dev: int
    ino: int


WorkspaceChange = tuple[str, ...]


def _is_image_path(path: str) -> bool:
    return path.lower().endswith(_IMAGE_EXTENSIONS)


def _change_kind(change: object) -> str:
    kind = getattr(change, "name", None)
    if not isinstance(kind, str):
        kind = str(change)
    return kind


def _stat_file_state(file_path: str) -> WorkspaceFileState:
    stat = os.stat(file_path)
    return WorkspaceFileState(
        mtime_ns=int(getattr(stat, "st_mtime_ns", 0)),
        size=int(getattr(stat, "st_size", 0)),
        dev=int(getattr(stat, "st_dev", 0)),
        ino=int(getattr(stat, "st_ino", 0)),
    )


def _iter_workspace_changes(
    changes: Iterable[tuple[object, str]],
) -> list[tuple[str, str]]:
    """Return image changes plus non-image structure changes.

    watchfiles does not reliably emit every contained image when a directory is
    moved or renamed. Non-image add/delete events are therefore forwarded as
    structure hints so the controller can reconcile against a fresh snapshot.
    Ordinary non-image modifications are ignored.
    """
    results: list[tuple[str, str]] = []
    for change, path in changes:
        if not isinstance(path, str):
            continue

        kind = _change_kind(change)
        if not _is_image_path(path):
            kind_lower = kind.lower()
            if "added" not in kind_lower and "deleted" not in kind_lower:
                continue
        results.append((kind, path))
    return results


def _iter_image_changes(
    changes: Iterable[tuple[object, str]],
) -> list[tuple[str, str]]:
    return [
        (kind, path)
        for kind, path in _iter_workspace_changes(changes)
        if _is_image_path(path)
    ]


def build_file_snapshot(file_paths: Iterable[str]) -> dict[str, WorkspaceFileState]:
    snapshot: dict[str, WorkspaceFileState] = {}
    for file_path in file_paths:
        if not isinstance(file_path, str) or not _is_image_path(file_path):
            continue
        try:
            state = _stat_file_state(file_path)
        except OSError:
            continue
        snapshot[file_path] = state
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
                state = _stat_file_state(file_path)
            except OSError:
                continue
            snapshot[file_path] = state
    return snapshot


def normalize_workspace_changes(
    changes: Iterable[WorkspaceChange],
) -> list[WorkspaceChange]:
    moved: dict[str, str] = {}
    added: set[str] = set()
    deleted: set[str] = set()
    modified: set[str] = set()

    for change in changes:
        if len(change) < 2:
            continue
        kind, path = change[0], change[1]
        if not isinstance(path, str) or not path:
            continue
        kind_lower = str(kind).lower()
        if "moved" in kind_lower and len(change) >= 3:
            new_path = change[2]
            if isinstance(new_path, str) and new_path:
                moved[path] = new_path
        elif "added" in kind_lower:
            added.add(path)
        elif "deleted" in kind_lower or "removed" in kind_lower:
            deleted.add(path)
        elif "modified" in kind_lower:
            modified.add(path)

    if moved:
        deleted.difference_update(moved.keys())
        added.difference_update(moved.values())
        modified.difference_update(moved.keys())
        modified.difference_update(moved.values())

    effective_modified = modified - added - deleted
    normalized: list[WorkspaceChange] = []
    normalized.extend(("moved", old, new) for old, new in sorted(moved.items()))
    normalized.extend(("deleted", path) for path in sorted(deleted))
    normalized.extend(("added", path) for path in sorted(added))
    normalized.extend(("modified", path) for path in sorted(effective_modified))
    return normalized


def _file_identity(state: WorkspaceFileState) -> tuple[int, int] | None:
    if state.dev <= 0 or state.ino <= 0:
        return None
    return (state.dev, state.ino)


def diff_workspace_snapshots(
    previous: dict[str, WorkspaceFileState],
    current: dict[str, WorkspaceFileState],
) -> list[WorkspaceChange]:
    previous_paths = set(previous)
    current_paths = set(current)
    deleted_paths = previous_paths - current_paths
    added_paths = current_paths - previous_paths

    deleted_by_identity: dict[tuple[int, int], list[str]] = defaultdict(list)
    added_by_identity: dict[tuple[int, int], list[str]] = defaultdict(list)
    for path in deleted_paths:
        identity = _file_identity(previous[path])
        if identity is not None:
            deleted_by_identity[identity].append(path)
    for path in added_paths:
        identity = _file_identity(current[path])
        if identity is not None:
            added_by_identity[identity].append(path)

    moved: list[tuple[str, str, str]] = []
    paired_deleted: set[str] = set()
    paired_added: set[str] = set()
    for identity in sorted(set(deleted_by_identity) & set(added_by_identity)):
        old_paths = deleted_by_identity[identity]
        new_paths = added_by_identity[identity]
        if len(old_paths) != 1 or len(new_paths) != 1:
            continue
        old_path = old_paths[0]
        new_path = new_paths[0]
        moved.append(("moved", old_path, new_path))
        paired_deleted.add(old_path)
        paired_added.add(new_path)

    changes: list[WorkspaceChange] = []
    changes.extend(sorted(moved, key=lambda item: (item[1], item[2])))
    changes.extend(
        ("deleted", path) for path in sorted(deleted_paths - paired_deleted)
    )
    changes.extend(("added", path) for path in sorted(added_paths - paired_added))

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
            workspace_changes = _iter_workspace_changes(changes)
            if workspace_changes:
                self.changes_detected.emit(workspace_changes)


class WorkspaceWatcherController(QObject):
    """Owns watchfiles integration, suppression, suspension, and refresh diffing."""

    def __init__(
        self,
        apply_changes: Callable[[list[WorkspaceChange]], None],
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

        dispatched = self._filter_suppressed_changes(changes)
        if dispatched:
            self._apply_changes(dispatched)

        self.start()

    def _on_watcher_changes(self, changes: list[WorkspaceChange]) -> None:
        if not changes:
            return

        now = time.monotonic()
        self._suppressed_paths = {
            path: until for path, until in self._suppressed_paths.items() if until > now
        }

        normalized = normalize_workspace_changes(changes)
        if self._requires_snapshot_reconcile(normalized):
            self._reconcile_snapshot()
            return

        image_changes = [
            change
            for change in normalized
            if len(change) >= 2 and _is_image_path(change[1])
        ]
        dispatched = self._filter_suppressed_changes(image_changes)
        touched_paths: set[str] = set()

        for change in image_changes:
            touched_paths.update(self._paths_for_change(change))

        self._apply_snapshot_updates(touched_paths)

        if dispatched:
            self._apply_changes(dispatched)

    def _requires_snapshot_reconcile(self, changes: list[WorkspaceChange]) -> bool:
        has_image_added = False
        has_image_deleted = False
        for change in changes:
            if len(change) < 2:
                continue
            kind = str(change[0]).lower()
            path = change[1]
            if not _is_image_path(path):
                return True
            if "added" in kind:
                has_image_added = True
            elif "deleted" in kind or "removed" in kind:
                has_image_deleted = True
            elif "moved" in kind:
                return True
        return has_image_added and has_image_deleted

    def _reconcile_snapshot(self) -> None:
        current_snapshot = scan_workspace_snapshot(self._root_folder)
        changes = diff_workspace_snapshots(self._snapshot, current_snapshot)
        self._snapshot = current_snapshot

        dispatched = self._filter_suppressed_changes(changes)
        if dispatched:
            self._apply_changes(dispatched)

    def _paths_for_change(self, change: WorkspaceChange) -> list[str]:
        if len(change) >= 3 and str(change[0]).lower() == "moved":
            return [change[1], change[2]]
        if len(change) >= 2:
            return [change[1]]
        return []

    def _filter_suppressed_changes(
        self,
        changes: Iterable[WorkspaceChange],
    ) -> list[WorkspaceChange]:
        dispatched: list[WorkspaceChange] = []
        for change in changes:
            if any(
                path in self._suppressed_paths
                for path in self._paths_for_change(change)
            ):
                continue
            dispatched.append(change)
        return dispatched

    def _apply_snapshot_updates(self, paths: set[str]) -> None:
        for path in paths:
            try:
                state = _stat_file_state(path)
            except OSError:
                self._snapshot.pop(path, None)
                continue
            self._snapshot[path] = state
