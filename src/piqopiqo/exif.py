"""EXIF management utilities for reading and writing EXIF data in background."""

from __future__ import annotations

import logging
import multiprocessing
import signal
import time

import exiftool
from PySide6.QtCore import QObject, Signal

from .config import Config

logger = logging.getLogger(__name__)


def _pool_worker_init() -> None:
    """Initializer for Pool workers.

    Ignore SIGINT in workers so Ctrl-C only affects the main process.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def exif_read_task(
    file_path: str, exiftool_path: str | None, common_args: list[str]
) -> tuple[str, dict]:
    """Fetch EXIF metadata in a separate process."""
    with exiftool.ExifToolHelper(
        executable=exiftool_path, common_args=common_args
    ) as helper:
        metadata = helper.get_metadata(file_path)
        if not metadata:
            return (file_path, {})
        return (file_path, metadata[0])


def exif_write_task(
    file_path: str,
    tags: dict,
    exiftool_path: str | None,
) -> tuple[str, bool, str]:
    """Write EXIF metadata to file in a separate process.

    Args:
        file_path: Path to the image file.
        tags: Dictionary of EXIF tags to write.
        exiftool_path: Path to exiftool executable (or None for default).

    Returns:
        Tuple of (file_path, success, error_message).
    """
    try:
        # Use MWG module for cross-format metadata writing
        common_args = ["-use", "MWG"]
        with exiftool.ExifToolHelper(
            executable=exiftool_path, common_args=common_args
        ) as helper:
            helper.set_tags(file_path, tags, params=["-overwrite_original"])
        return (file_path, True, "")
    except Exception as e:
        return (file_path, False, str(e))


class ExifManager(QObject):
    """Manager for reading and writing EXIF metadata in background processes.

    Used for reading the EXIF for direct display in the EXIF panel

    For reading: use fetch_exif() which emits exif_ready signal.
    For writing: use write_exif() which emits write_progress/write_file_completed/
    write_all_completed signals.
    """

    # Read signals
    exif_ready = Signal(str, dict)  # file_path, metadata

    # Write signals
    write_progress = Signal(int, int)  # completed, total
    write_file_completed = Signal(str, bool, str)  # file_path, success, error_message
    write_all_completed = Signal()

    def __init__(
        self,
        exiftool_path: str | None,
        common_args: list[str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.exiftool_path = exiftool_path
        # no -n (machine format) : displayed to the user
        self.common_args = common_args or ["-G", "-use", "MWG"]

        # Read pool (always active)
        self.pool = multiprocessing.Pool(
            Config.MAX_WORKERS,
            initializer=_pool_worker_init,
        )
        self.pending: set[str] = set()

        # Write pool (created on demand)
        self._write_pool: multiprocessing.Pool | None = None
        self._write_total = 0
        self._write_completed = 0
        self._write_errors: dict[str, str] = {}
        self._write_pending: set[str] = set()
        self._write_stopped = False

    # -------------------------------------------------------------------------
    # Read operations
    # -------------------------------------------------------------------------

    def fetch_exif(self, file_path: str):
        """Queue a file for EXIF reading."""
        if file_path in self.pending:
            return

        self.pending.add(file_path)
        self.pool.apply_async(
            exif_read_task,
            (file_path, self.exiftool_path, self.common_args),
            callback=self._on_read_done,
            error_callback=lambda e, fp=file_path: self._on_read_error(fp, e),
        )

    def _on_read_done(self, result: tuple[str, dict]):
        file_path, metadata = result
        if file_path in self.pending:
            self.pending.remove(file_path)
        self.exif_ready.emit(file_path, metadata)

    def _on_read_error(self, file_path: str, error: Exception):
        if file_path in self.pending:
            self.pending.remove(file_path)
        logger.error(f"Error fetching EXIF for {file_path}: {error}")
        self.exif_ready.emit(file_path, {})

    # -------------------------------------------------------------------------
    # Write operations
    # -------------------------------------------------------------------------

    def write_exif(self, items: list[tuple[str, dict]]):
        """Start writing EXIF data for a list of items.

        Args:
            items: List of (file_path, tags_dict) tuples.
        """
        self._write_total = len(items)
        self._write_completed = 0
        self._write_errors = {}
        self._write_pending = set()
        self._write_stopped = False

        self._write_pool = multiprocessing.Pool(
            Config.MAX_WORKERS,
            initializer=_pool_worker_init,
        )

        for file_path, tags in items:
            self._write_pending.add(file_path)
            self._write_pool.apply_async(
                exif_write_task,
                (file_path, tags, self.exiftool_path),
                callback=self._on_write_done,
                error_callback=lambda e, fp=file_path: self._on_write_error(fp, e),
            )

    def _on_write_done(self, result: tuple[str, bool, str]):
        if self._write_stopped:
            return

        file_path, success, error_message = result
        if file_path in self._write_pending:
            self._write_pending.remove(file_path)

        self._write_completed += 1

        if not success:
            self._write_errors[file_path] = error_message

        self.write_file_completed.emit(file_path, success, error_message)
        self.write_progress.emit(self._write_completed, self._write_total)

        if self._write_completed >= self._write_total:
            self.write_all_completed.emit()

    def _on_write_error(self, file_path: str, error: Exception):
        if self._write_stopped:
            return

        if file_path in self._write_pending:
            self._write_pending.remove(file_path)

        self._write_completed += 1
        self._write_errors[file_path] = str(error)

        self.write_file_completed.emit(file_path, False, str(error))
        self.write_progress.emit(self._write_completed, self._write_total)

        if self._write_completed >= self._write_total:
            self.write_all_completed.emit()

    def stop_write(self):
        """Stop the write process (does not undo completed writes)."""
        self._write_stopped = True
        if self._write_pool:
            self._write_pool.terminate()
            self._write_pool.join()
            self._write_pool = None

    def get_write_errors(self) -> dict[str, str]:
        """Get dictionary of file paths to error messages."""
        return self._write_errors.copy()

    def get_write_progress(self) -> tuple[int, int]:
        """Get current write progress as (completed, total)."""
        return self._write_completed, self._write_total

    # -------------------------------------------------------------------------
    # Shutdown
    # -------------------------------------------------------------------------

    def stop(self, timeout_s: float | None = None):
        """Stop all EXIF worker pools.

        If timeout_s is provided and the pool does not stop within that time,
        the pool will be terminated.
        """
        # Stop write pool first
        self.stop_write()

        # Stop read pool
        if getattr(self, "pool", None) is None:
            return

        pool = self.pool
        self.pool = None

        if timeout_s is None:
            pool.close()
            pool.join()
            return

        deadline = time.monotonic() + max(0.0, float(timeout_s))
        pool.close()

        processes = getattr(pool, "_pool", None) or []
        for proc in processes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            proc.join(remaining)

        if any(proc.is_alive() for proc in processes):
            logger.warning("EXIF pool shutdown timed out; terminating workers")
            try:
                pool.terminate()
            except Exception:
                pass
            for proc in processes:
                proc.join(1.0)
