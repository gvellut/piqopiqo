"""EXIF management utilities for fetching EXIF data in background."""

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


def exif_worker_task(
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


class ExifManager(QObject):
    """Manager for fetching EXIF metadata in background processes."""

    exif_ready = Signal(str, dict)

    def __init__(
        self,
        exiftool_path: str | None,
        common_args: list[str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.exiftool_path = exiftool_path
        self.common_args = common_args or ["-G"]
        self.pool = multiprocessing.Pool(
            Config.MAX_WORKERS,
            initializer=_pool_worker_init,
        )
        self.pending: set[str] = set()

    def fetch_exif(self, file_path: str):
        if file_path in self.pending:
            return

        self.pending.add(file_path)
        self.pool.apply_async(
            exif_worker_task,
            (file_path, self.exiftool_path, self.common_args),
            callback=self._on_task_done,
            error_callback=lambda e, fp=file_path: self._on_task_error(fp, e),
        )

    def _on_task_done(self, result: tuple[str, dict]):
        file_path, metadata = result
        if file_path in self.pending:
            self.pending.remove(file_path)
        self.exif_ready.emit(file_path, metadata)

    def _on_task_error(self, file_path: str, error: Exception):
        if file_path in self.pending:
            self.pending.remove(file_path)
        logger.error(f"Error fetching EXIF for {file_path}: {error}")
        self.exif_ready.emit(file_path, {})

    def stop(self, timeout_s: float | None = None):
        """Stop the EXIF worker pool.

        If timeout_s is provided and the pool does not stop within that time,
        the pool will be terminated.
        """
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


# Backward compatibility: re-export ExifPanel from panels
from .panels.exif_panel import ExifPanel  # noqa: E402, F401
