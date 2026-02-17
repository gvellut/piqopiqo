"""Unified background manager for EXIF extraction, EXIF writing and thumbnails.

All background work runs in multiprocessing worker processes and results are applied
on the Qt thread via signals.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
from pathlib import Path
import queue
import shutil
import time

from attrs import define
from PySide6.QtCore import QObject, QTimer, Signal

from piqopiqo.cache_paths import ensure_thumb_dir
from piqopiqo.metadata.metadata_db import MetadataDBManager
from piqopiqo.settings_state import (
    RuntimeSettingKey,
    UserSettingKey,
    get_runtime_setting,
    get_user_setting,
)

from . import media_worker

logger = logging.getLogger(__name__)


@define
class _FileInfo:
    file_path: str
    source_folder: str
    thumb_dir: str
    base_name: str

    @property
    def embedded_cache_path(self) -> str:
        return str(Path(self.thumb_dir) / "embedded" / f"{self.base_name}.jpg")

    @property
    def hq_cache_path(self) -> str:
        return str(Path(self.thumb_dir) / "hq" / f"{self.base_name}.jpg")

    @property
    def legacy_embedded_cache_path(self) -> str:
        return str(Path(self.thumb_dir) / f"{self.base_name}_embedded.jpg")

    @property
    def legacy_hq_cache_path(self) -> str:
        return str(Path(self.thumb_dir) / f"{self.base_name}_hq.jpg")


@define
class _CombinedNeed:
    want_embedded: bool = False
    want_editable: bool = False
    want_panel: bool = False
    force: bool = False


@define
class _Worker:
    process: multiprocessing.Process
    task_queue: multiprocessing.Queue
    busy: bool = False
    current_task_id: int | None = None


class MediaManager(QObject):
    """Manages EXIF extraction, embedded preview extraction and thumbnail generation."""

    # Thumbnail signals
    thumb_ready = Signal(str, str, str)  # file_path, thumb_type, cache_path
    thumb_progress_updated = Signal(int, int)  # completed, total

    # Editable metadata (EXIF_TO_DB_MAPPING) signals
    editable_ready = Signal(str, dict)  # file_path, metadata
    exif_progress_updated = Signal(int, int)  # completed, total

    # EXIF panel fields signals
    panel_fields_ready = Signal(str, dict)  # file_path, key->value|None

    # Errors / completion
    all_completed = Signal()

    # EXIF write signals (Save EXIF dialog)
    write_progress = Signal(int, int)  # completed, total
    write_file_completed = Signal(str, bool, str)  # file_path, success, error_message
    write_all_completed = Signal()

    def __init__(self, db_manager: MetadataDBManager, parent=None):
        super().__init__(parent)
        self._db_manager = db_manager

        self._ctx = multiprocessing.get_context("spawn")
        self._result_queue: multiprocessing.Queue = self._ctx.Queue()
        self._workers: list[_Worker] = []
        self._next_task_id = 1

        self._file_infos: dict[str, _FileInfo] = {}
        self._visible_paths: set[str] = set()
        self._visible_order: list[str] = []

        self._thumb_done: set[str] = set()
        self._editable_done: set[str] = set()

        self._thumb_total = 0
        self._thumb_completed = 0
        self._exif_total = 0
        self._exif_completed = 0

        self._thumb_errors: dict[str, str] = {}
        self._exif_errors: dict[str, str] = {}

        # Pending tasks
        self._pending_combined_visible: dict[str, _CombinedNeed] = {}
        self._pending_combined_other: dict[str, _CombinedNeed] = {}
        self._pending_hq_visible: set[str] = set()
        self._pending_hq_other: set[str] = set()

        # In-flight tasks
        self._in_flight: dict[int, _Worker] = {}
        self._in_flight_files: set[str] = set()
        self._deferred_combined: dict[str, _CombinedNeed] = {}

        # EXIF panel field keys
        self._panel_field_keys: list[str] = [
            f.key for f in get_runtime_setting(RuntimeSettingKey.EXIF_FIELDS)
        ]

        # EXIF writing state
        self._write_total = 0
        self._write_completed = 0
        self._write_stopped = False
        self._pending_write_items: list[dict] = []

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(50)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()

        self._ensure_min_idle_workers()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def reset_for_folder(
        self, file_paths: list[str], source_folders: list[str]
    ) -> None:
        """Reset internal state for a new folder."""
        self._file_infos.clear()
        self._visible_paths.clear()
        self._visible_order.clear()

        self._thumb_done.clear()
        self._editable_done.clear()
        self._thumb_errors.clear()
        self._exif_errors.clear()

        self._pending_combined_visible.clear()
        self._pending_combined_other.clear()
        self._pending_hq_visible.clear()
        self._pending_hq_other.clear()
        self._in_flight_files.clear()
        self._deferred_combined.clear()

        self._thumb_total = len(file_paths)
        self._thumb_completed = 0
        self._exif_total = len(file_paths)
        self._exif_completed = 0

        self._panel_field_keys = [
            f.key for f in get_runtime_setting(RuntimeSettingKey.EXIF_FIELDS)
        ]

        for folder in source_folders:
            ensure_thumb_dir(folder)

        for file_path in file_paths:
            source_folder = os.path.dirname(file_path)
            thumb_dir = str(ensure_thumb_dir(source_folder))
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            self._file_infos[file_path] = _FileInfo(
                file_path=file_path,
                source_folder=source_folder,
                thumb_dir=thumb_dir,
                base_name=base_name,
            )

        self.thumb_progress_updated.emit(self._thumb_completed, self._thumb_total)
        self.exif_progress_updated.emit(self._exif_completed, self._exif_total)

        # Prime from DB / caches and queue missing work (initially non-visible).
        self._prime_and_queue_initial(file_paths)

    def add_files(self, file_paths: list[str]) -> None:
        """Register new files and enqueue processing for them."""
        added: list[str] = []

        for file_path in file_paths:
            if file_path in self._file_infos:
                continue

            source_folder = os.path.dirname(file_path)
            thumb_dir = str(ensure_thumb_dir(source_folder))
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            self._file_infos[file_path] = _FileInfo(
                file_path=file_path,
                source_folder=source_folder,
                thumb_dir=thumb_dir,
                base_name=base_name,
            )
            added.append(file_path)

        if not added:
            return

        self._thumb_total += len(added)
        self._exif_total += len(added)

        self._prime_and_queue_initial(added)

    def remove_files(self, file_paths: list[str]) -> None:
        """Unregister files and drop any pending work for them."""
        removed = 0
        for file_path in file_paths:
            if file_path not in self._file_infos:
                continue

            removed += 1
            self._file_infos.pop(file_path, None)

            self._visible_paths.discard(file_path)
            if file_path in self._visible_order:
                self._visible_order = [p for p in self._visible_order if p != file_path]

            self._pending_combined_visible.pop(file_path, None)
            self._pending_combined_other.pop(file_path, None)
            self._pending_hq_visible.discard(file_path)
            self._pending_hq_other.discard(file_path)

            self._in_flight_files.discard(file_path)
            self._deferred_combined.pop(file_path, None)

            if file_path in self._thumb_done:
                self._thumb_done.remove(file_path)
                self._thumb_completed = max(0, self._thumb_completed - 1)
            if file_path in self._editable_done:
                self._editable_done.remove(file_path)
                self._exif_completed = max(0, self._exif_completed - 1)

            self._thumb_errors.pop(file_path, None)
            self._exif_errors.pop(file_path, None)

        if removed <= 0:
            return

        self._thumb_total = max(0, self._thumb_total - removed)
        self._exif_total = max(0, self._exif_total - removed)

        self.thumb_progress_updated.emit(self._thumb_completed, self._thumb_total)
        self.exif_progress_updated.emit(self._exif_completed, self._exif_total)

    def update_visible(self, visible_paths_in_order: list[str]) -> None:
        """Update visible items so the scheduler can prioritize them."""
        new_visible = {p for p in visible_paths_in_order if p in self._file_infos}
        self._visible_paths = new_visible
        self._visible_order = [p for p in visible_paths_in_order if p in new_visible]

        self._rebalance_pending_priorities()

    def refresh_exif_field_keys(self, field_keys: list[str]) -> None:
        """Update the EXIF panel field list and backfill missing keys.

        For each photo, this will:
        - delete removed keys from the DB
        - queue extraction if any new key is missing
        """
        # Preserve order, drop duplicates
        seen: set[str] = set()
        new_keys: list[str] = []
        for key in field_keys:
            if not key or key in seen:
                continue
            seen.add(key)
            new_keys.append(key)

        old_keys = set(self._panel_field_keys)
        removed = sorted(old_keys - set(new_keys))

        self._panel_field_keys = new_keys

        for file_path, info in list(self._file_infos.items()):
            db = self._db_manager.get_db_for_folder(info.source_folder)
            if removed:
                try:
                    db.delete_exif_fields(file_path, keys=removed)
                except Exception:
                    pass

            if not db.has_exif_fields(file_path, self._panel_field_keys):
                self._queue_combined(
                    file_path,
                    want_panel=True,
                    to_visible=file_path in self._visible_paths,
                )

    def ensure_panel_fields_loaded_from_db(self, file_paths: list[str]) -> None:
        """Load EXIF panel fields from DB for the given files (no exiftool)."""
        for file_path in file_paths:
            info = self._file_infos.get(file_path)
            if info is None:
                continue

            db = self._db_manager.get_db_for_folder(info.source_folder)
            if not db.has_exif_fields(file_path, self._panel_field_keys):
                self._queue_combined(
                    file_path,
                    want_panel=True,
                    to_visible=file_path in self._visible_paths,
                )
                continue

            stored = db.get_exif_fields(file_path, self._panel_field_keys) or {}
            complete = {k: stored.get(k) for k in self._panel_field_keys}
            self.panel_fields_ready.emit(file_path, complete)

    def _is_lowres_only_mode(self) -> bool:
        return bool(get_runtime_setting(RuntimeSettingKey.GRID_LOWRES_ONLY))

    def request_thumbnail(self, file_path: str) -> None:
        """Ensure a thumbnail is available for a file, prioritizing if visible."""
        info = self._file_infos.get(file_path)
        if info is None:
            return

        self._migrate_legacy_thumbs(info)
        lowres_only = self._is_lowres_only_mode()

        # Fast-path: cache exists.
        if (not lowres_only) and os.path.exists(info.hq_cache_path):
            self.thumb_ready.emit(file_path, "hq", info.hq_cache_path)
            self._mark_thumb_done(file_path)
            return

        if os.path.exists(info.embedded_cache_path):
            self.thumb_ready.emit(file_path, "embedded", info.embedded_cache_path)
            self._mark_thumb_done(file_path)
            # Still generate HQ later if missing.
            if (not lowres_only) and (not os.path.exists(info.hq_cache_path)):
                self._queue_hq(file_path, to_visible=file_path in self._visible_paths)
            return

        self._queue_combined(
            file_path,
            want_embedded=True,
            to_visible=True,
        )

    def regenerate_thumbnails(self, file_paths: list[str]) -> None:
        """Clear cached thumbnails and re-queue generation (embedded then HQ)."""
        for file_path in file_paths:
            info = self._file_infos.get(file_path)
            if info is None:
                continue

            self._migrate_legacy_thumbs(info)

            if file_path in self._thumb_done:
                self._thumb_done.remove(file_path)
                self._thumb_completed = max(0, self._thumb_completed - 1)
                self.thumb_progress_updated.emit(
                    self._thumb_completed, self._thumb_total
                )

            for path in (
                info.embedded_cache_path,
                info.hq_cache_path,
                info.legacy_embedded_cache_path,
                info.legacy_hq_cache_path,
            ):
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass

            self._queue_combined(
                file_path,
                want_embedded=True,
                to_visible=file_path in self._visible_paths,
            )

    def regenerate_exif(self, file_paths: list[str]) -> None:
        """Re-read EXIF for editable + panel fields and overwrite DB values."""
        for file_path in file_paths:
            self._queue_combined(
                file_path,
                want_editable=True,
                want_panel=True,
                to_visible=file_path in self._visible_paths,
                force=True,
            )

    # --- EXIF writing (Save EXIF dialog) ---

    def write_exif(self, items: list[tuple[str, dict]]) -> None:
        self._write_total = len(items)
        self._write_completed = 0
        self._write_stopped = False

        self._pending_write_items = [
            {"file_path": file_path, "tags": tags} for file_path, tags in items
        ]

        self.write_progress.emit(self._write_completed, self._write_total)

    def stop_write(self) -> None:
        self._write_stopped = True
        self._pending_write_items.clear()

    def get_write_progress(self) -> tuple[int, int]:
        return self._write_completed, self._write_total

    # -------------------------------------------------------------------------
    # Errors / progress
    # -------------------------------------------------------------------------

    def get_thumb_errors(self) -> dict[str, str]:
        return self._thumb_errors.copy()

    def get_exif_errors(self) -> dict[str, str]:
        return self._exif_errors.copy()

    def has_errors(self) -> bool:
        return bool(self._thumb_errors or self._exif_errors)

    # -------------------------------------------------------------------------
    # Shutdown
    # -------------------------------------------------------------------------

    def stop(self, timeout_s: float | None = None) -> None:
        """Stop all workers."""
        self._tick_timer.stop()

        deadline = None
        if timeout_s is not None:
            deadline = time.monotonic() + max(0.0, float(timeout_s))

        for worker in list(self._workers):
            try:
                worker.task_queue.put({"kind": "stop"}, block=False)
            except Exception:
                pass

        for worker in list(self._workers):
            try:
                remaining = None
                if deadline is not None:
                    remaining = max(0.0, deadline - time.monotonic())
                worker.process.join(timeout=remaining)
            except Exception:
                pass

        for worker in list(self._workers):
            if worker.process.is_alive():
                try:
                    worker.process.terminate()
                except Exception:
                    pass
                try:
                    worker.process.join(timeout=1.0)
                except Exception:
                    pass

        self._workers.clear()

    # -------------------------------------------------------------------------
    # Internal: priming & queueing
    # -------------------------------------------------------------------------

    def _migrate_legacy_thumbs(self, info: _FileInfo) -> None:
        """Best-effort migration from legacy thumb naming to split folders."""
        candidates = [
            (info.legacy_embedded_cache_path, info.embedded_cache_path),
            (info.legacy_hq_cache_path, info.hq_cache_path),
        ]
        for legacy_path, new_path in candidates:
            try:
                if os.path.exists(new_path) or not os.path.exists(legacy_path):
                    continue

                Path(new_path).parent.mkdir(parents=True, exist_ok=True)
                try:
                    Path(legacy_path).rename(new_path)
                except OSError:
                    shutil.copy2(legacy_path, new_path)
            except Exception:
                continue

    def _prime_and_queue_initial(self, file_paths: list[str]) -> None:
        for file_path in file_paths:
            info = self._file_infos.get(file_path)
            if info is None:
                continue

            self._migrate_legacy_thumbs(info)

            # Editable metadata
            db = self._db_manager.get_db_for_folder(info.source_folder)
            meta = db.get_metadata(file_path)
            if meta is not None:
                self._editable_done.add(file_path)
                self._exif_completed += 1
                self.editable_ready.emit(file_path, meta)
            else:
                self._queue_combined(file_path, want_editable=True)

            # Panel fields (stored in DB as key/value)
            if not db.has_exif_fields(file_path, self._panel_field_keys):
                self._queue_combined(file_path, want_panel=True)

            # Thumbnails
            lowres_only = self._is_lowres_only_mode()
            has_embedded = os.path.exists(info.embedded_cache_path)
            has_hq = os.path.exists(info.hq_cache_path)

            if lowres_only:
                if has_embedded:
                    self._thumb_done.add(file_path)
                    self._thumb_completed += 1
                else:
                    self._queue_combined(file_path, want_embedded=True)
            else:
                if has_hq:
                    self._thumb_done.add(file_path)
                    self._thumb_completed += 1
                elif has_embedded:
                    self._thumb_done.add(file_path)
                    self._thumb_completed += 1
                    self._queue_hq(file_path)
                else:
                    self._queue_combined(file_path, want_embedded=True)

                # If we want HQ thumbnails for everything, queue missing HQ.
                if not has_hq:
                    self._queue_hq(file_path)

        self.thumb_progress_updated.emit(self._thumb_completed, self._thumb_total)
        self.exif_progress_updated.emit(self._exif_completed, self._exif_total)

    def _queue_combined(
        self,
        file_path: str,
        *,
        want_embedded: bool = False,
        want_editable: bool = False,
        want_panel: bool = False,
        to_visible: bool = False,
        force: bool = False,
    ) -> None:
        if file_path not in self._file_infos:
            return

        if file_path in self._in_flight_files:
            need = self._deferred_combined.get(file_path) or _CombinedNeed()
            need.want_embedded = need.want_embedded or want_embedded
            need.want_editable = need.want_editable or want_editable
            need.want_panel = need.want_panel or want_panel
            need.force = need.force or force
            self._deferred_combined[file_path] = need
            return

        if to_visible or file_path in self._visible_paths:
            target = self._pending_combined_visible
            other = self._pending_combined_other
        else:
            target = self._pending_combined_other
            other = self._pending_combined_visible

        need = target.get(file_path) or other.pop(file_path, None) or _CombinedNeed()
        need.want_embedded = need.want_embedded or want_embedded
        need.want_editable = need.want_editable or want_editable
        need.want_panel = need.want_panel or want_panel
        need.force = need.force or force

        # Force means "overwrite DB" so we must actually re-read.
        if force:
            need.want_editable = True
            need.want_panel = True

        target[file_path] = need

    def _queue_hq(self, file_path: str, *, to_visible: bool = False) -> None:
        if self._is_lowres_only_mode():
            return

        if file_path not in self._file_infos:
            return

        if to_visible or file_path in self._visible_paths:
            self._pending_hq_visible.add(file_path)
            self._pending_hq_other.discard(file_path)
        else:
            if file_path not in self._pending_hq_visible:
                self._pending_hq_other.add(file_path)

    def _rebalance_pending_priorities(self) -> None:
        # Combined
        for file_path in list(self._pending_combined_other.keys()):
            if file_path in self._visible_paths:
                self._pending_combined_visible[file_path] = (
                    self._pending_combined_other.pop(file_path)
                )
        for file_path in list(self._pending_combined_visible.keys()):
            if file_path not in self._visible_paths:
                self._pending_combined_other[file_path] = (
                    self._pending_combined_visible.pop(file_path)
                )

        # HQ thumbs
        for file_path in list(self._pending_hq_other):
            if file_path in self._visible_paths:
                self._pending_hq_other.remove(file_path)
                self._pending_hq_visible.add(file_path)
        for file_path in list(self._pending_hq_visible):
            if file_path not in self._visible_paths:
                self._pending_hq_visible.remove(file_path)
                self._pending_hq_other.add(file_path)

    # -------------------------------------------------------------------------
    # Internal: worker management & scheduler
    # -------------------------------------------------------------------------

    def _ensure_min_idle_workers(self) -> None:
        while len(self._workers) < max(
            1, int(get_runtime_setting(RuntimeSettingKey.MIN_IDLE_WORKERS))
        ):
            self._spawn_worker()

    def _spawn_worker(self) -> None:
        task_q: multiprocessing.Queue = self._ctx.Queue()
        proc = self._ctx.Process(
            target=media_worker.worker_main,
            args=(task_q, self._result_queue),
            daemon=True,
        )
        proc.start()
        self._workers.append(_Worker(process=proc, task_queue=task_q))

    def _stop_extra_idle_workers(self) -> None:
        min_idle = max(1, int(get_runtime_setting(RuntimeSettingKey.MIN_IDLE_WORKERS)))
        if len(self._workers) <= min_idle:
            return

        if self._has_pending_work():
            return

        idle_workers = [w for w in self._workers if not w.busy]
        while len(self._workers) > min_idle and idle_workers:
            worker = idle_workers.pop()
            try:
                worker.task_queue.put({"kind": "stop"}, block=False)
            except Exception:
                pass
            try:
                worker.process.join(timeout=0.2)
            except Exception:
                pass
            try:
                self._workers.remove(worker)
            except ValueError:
                pass

    def _has_pending_work(self) -> bool:
        return bool(
            self._pending_write_items
            or self._pending_combined_visible
            or self._pending_combined_other
            or self._pending_hq_visible
            or self._pending_hq_other
        )

    def _get_idle_worker(self) -> _Worker | None:
        for worker in self._workers:
            if not worker.busy and worker.process.is_alive():
                return worker
        return None

    def _tick(self) -> None:
        self._drain_results()
        self._schedule_work()
        self._stop_extra_idle_workers()
        self._ensure_min_idle_workers()

    def _drain_results(self) -> None:
        while True:
            try:
                result = self._result_queue.get_nowait()
            except queue.Empty:
                break

            task_id = int(result.get("task_id", -1))
            worker = self._in_flight.pop(task_id, None)
            if worker is not None:
                worker.busy = False
                worker.current_task_id = None

            kind = result.get("kind")
            if kind == "combined":
                self._handle_combined_result(result)
            elif kind == "hq_thumb":
                self._handle_hq_result(result)
            elif kind == "write_exif":
                self._handle_write_result(result)

        if not self._has_pending_work() and not any(w.busy for w in self._workers):
            self.all_completed.emit()

    def _schedule_work(self) -> None:
        # Scale workers up if there's backpressure.
        if self._has_pending_work() and self._get_idle_worker() is None:
            max_workers = int(get_runtime_setting(RuntimeSettingKey.MAX_WORKERS))
            if len(self._workers) < max_workers:
                self._spawn_worker()

        while True:
            worker = self._get_idle_worker()
            if worker is None:
                break

            task = self._pop_next_task()
            if task is None:
                break

            task_id = int(task["task_id"])
            try:
                worker.task_queue.put(task, block=False)
            except Exception:
                break

            worker.busy = True
            worker.current_task_id = task_id
            self._in_flight[task_id] = worker

    def _pop_next_task(self) -> dict | None:
        # Highest priority: user-initiated EXIF writes.
        if self._pending_write_items and not self._write_stopped:
            batch_size = int(
                get_runtime_setting(RuntimeSettingKey.MAX_EXIFTOOLS_IMAGE_BATCH)
            )
            batch = self._pending_write_items[:batch_size]
            self._pending_write_items = self._pending_write_items[batch_size:]

            return {
                "task_id": self._new_task_id(),
                "kind": "write_exif",
                "exiftool_path": get_user_setting(UserSettingKey.EXIFTOOL_PATH),
                "items": batch,
            }

        combined_need = self._pop_combined_batch(visible=True)
        if combined_need is not None:
            return combined_need

        if self._pending_hq_visible:
            file_path = self._pop_from_set_in_visible_order(self._pending_hq_visible)
            if file_path is not None:
                return self._make_hq_task(file_path)

        combined_need = self._pop_combined_batch(visible=False)
        if combined_need is not None:
            return combined_need

        if self._pending_hq_other:
            file_path = next(iter(self._pending_hq_other))
            self._pending_hq_other.remove(file_path)
            return self._make_hq_task(file_path)

        return None

    def _pop_from_set_in_visible_order(self, items: set[str]) -> str | None:
        for file_path in self._visible_order:
            if file_path in items:
                items.remove(file_path)
                return file_path
        # Fallback
        if items:
            file_path = next(iter(items))
            items.remove(file_path)
            return file_path
        return None

    def _pop_combined_batch(self, *, visible: bool) -> dict | None:
        pending = (
            self._pending_combined_visible if visible else self._pending_combined_other
        )
        if not pending:
            return None

        batch_size = int(
            get_runtime_setting(RuntimeSettingKey.MAX_EXIFTOOLS_IMAGE_BATCH)
        )

        # Pick a folder to batch together (thumb_dir is per folder).
        first_path = None
        if visible:
            for candidate in self._visible_order:
                if candidate in pending:
                    first_path = candidate
                    break
        if first_path is None:
            first_path = next(iter(pending.keys()))

        info = self._file_infos.get(first_path)
        if info is None:
            pending.pop(first_path, None)
            return None

        source_folder = info.source_folder
        thumb_dir = info.thumb_dir

        selected: list[str] = []

        # Prefer visible order inside the folder.
        if visible:
            for candidate in self._visible_order:
                if len(selected) >= batch_size:
                    break
                if candidate in pending:
                    c_info = self._file_infos.get(candidate)
                    if c_info and c_info.source_folder == source_folder:
                        selected.append(candidate)

        if len(selected) < batch_size:
            for candidate in list(pending.keys()):
                if len(selected) >= batch_size:
                    break
                c_info = self._file_infos.get(candidate)
                if (
                    c_info
                    and c_info.source_folder == source_folder
                    and candidate not in selected
                ):
                    selected.append(candidate)

        files_payload = []
        for file_path in selected:
            need = pending.pop(file_path, None)
            if need is None:
                continue
            self._in_flight_files.add(file_path)
            files_payload.append(
                {
                    "file_path": file_path,
                    "want_embedded": bool(need.want_embedded),
                    "want_editable": bool(need.want_editable),
                    "want_panel": bool(need.want_panel),
                }
            )

        if not files_payload:
            return None

        return {
            "task_id": self._new_task_id(),
            "kind": "combined",
            "source_folder": source_folder,
            "thumb_dir": thumb_dir,
            "exiftool_path": get_user_setting(UserSettingKey.EXIFTOOL_PATH),
            "panel_field_keys": list(self._panel_field_keys),
            "files": files_payload,
        }

    def _make_hq_task(self, file_path: str) -> dict:
        info = self._file_infos[file_path]
        return {
            "task_id": self._new_task_id(),
            "kind": "hq_thumb",
            "file_path": file_path,
            "thumb_dir": info.thumb_dir,
            "max_dim": int(get_runtime_setting(RuntimeSettingKey.THUMB_MAX_DIM)),
        }

    def _new_task_id(self) -> int:
        task_id = self._next_task_id
        self._next_task_id += 1
        return task_id

    # -------------------------------------------------------------------------
    # Internal: results handling
    # -------------------------------------------------------------------------

    def _handle_combined_result(self, result: dict) -> None:
        items = list(result.get("items") or [])

        for entry in items:
            file_path = str(entry.get("file_path"))
            self._in_flight_files.discard(file_path)

            info = self._file_infos.get(file_path)
            if info is None:
                continue

            entry_error = entry.get("error") or result.get("error")
            if entry_error:
                self._exif_errors[file_path] = str(entry_error)

            # Editable metadata
            editable_meta = entry.get("editable_metadata")
            if isinstance(editable_meta, dict):
                db = self._db_manager.get_db_for_folder(info.source_folder)
                try:
                    db.save_metadata(file_path, editable_meta)
                    self.editable_ready.emit(file_path, editable_meta)
                    if file_path not in self._editable_done:
                        self._editable_done.add(file_path)
                        self._exif_completed += 1
                        self.exif_progress_updated.emit(
                            self._exif_completed, self._exif_total
                        )
                except Exception as e:
                    self._exif_errors[file_path] = str(e)

            # Panel fields
            panel_fields = entry.get("panel_fields")
            if isinstance(panel_fields, dict):
                db = self._db_manager.get_db_for_folder(info.source_folder)
                try:
                    db.save_exif_fields(file_path, panel_fields)
                    self.panel_fields_ready.emit(file_path, panel_fields)
                except Exception as e:
                    self._exif_errors[file_path] = str(e)

            # Embedded preview
            embedded_path = entry.get("embedded_cache_path")
            if isinstance(embedded_path, str) and embedded_path:
                self.thumb_ready.emit(file_path, "embedded", embedded_path)
                self._mark_thumb_done(file_path)

            # Queue HQ if missing
            if (not self._is_lowres_only_mode()) and (
                not os.path.exists(info.hq_cache_path)
            ):
                self._queue_hq(file_path, to_visible=file_path in self._visible_paths)

            deferred = self._deferred_combined.pop(file_path, None)
            if deferred is not None:
                db = self._db_manager.get_db_for_folder(info.source_folder)
                if deferred.force:
                    self._queue_combined(
                        file_path,
                        want_embedded=deferred.want_embedded,
                        want_editable=deferred.want_editable,
                        want_panel=deferred.want_panel,
                        to_visible=file_path in self._visible_paths,
                        force=True,
                    )
                else:
                    still_want_embedded = deferred.want_embedded and not os.path.exists(
                        info.embedded_cache_path
                    )
                    still_want_editable = deferred.want_editable and (
                        db.get_metadata(file_path) is None
                    )
                    still_want_panel = deferred.want_panel and (
                        not db.has_exif_fields(file_path, self._panel_field_keys)
                    )
                    if still_want_embedded or still_want_editable or still_want_panel:
                        self._queue_combined(
                            file_path,
                            want_embedded=still_want_embedded,
                            want_editable=still_want_editable,
                            want_panel=still_want_panel,
                            to_visible=file_path in self._visible_paths,
                        )

    def _handle_hq_result(self, result: dict) -> None:
        file_path = str(result.get("file_path"))
        info = self._file_infos.get(file_path)
        if info is None:
            return

        ok = bool(result.get("ok"))
        if ok:
            cache_path = result.get("cache_path")
            if isinstance(cache_path, str) and cache_path:
                self.thumb_ready.emit(file_path, "hq", cache_path)
                self._mark_thumb_done(file_path)
        else:
            self._thumb_errors[file_path] = str(result.get("error") or "HQ failed")

    def _handle_write_result(self, result: dict) -> None:
        results = list(result.get("results") or [])

        for entry in results:
            if self._write_stopped:
                return

            file_path = str(entry.get("file_path"))
            ok = bool(entry.get("ok"))
            err = str(entry.get("error") or "")

            self._write_completed += 1
            self.write_file_completed.emit(file_path, ok, err)
            self.write_progress.emit(self._write_completed, self._write_total)

        if self._write_completed >= self._write_total and not self._write_stopped:
            self.write_all_completed.emit()

    def _mark_thumb_done(self, file_path: str) -> None:
        if file_path in self._thumb_done:
            return
        self._thumb_done.add(file_path)
        self._thumb_completed += 1
        self.thumb_progress_updated.emit(self._thumb_completed, self._thumb_total)
