"""Background workers for saving metadata."""

from __future__ import annotations

import logging

from PySide6.QtCore import QRunnable, QThreadPool

logger = logging.getLogger(__name__)


def drain_qthread_pool(
    pool: QThreadPool, timeout_ms: int, *, clear_queued: bool = True
) -> bool:
    """Bounded shutdown helper for QThreadPool-backed background work."""
    # Expire idle Qt pool threads immediately during shutdown so the Python
    # interpreter is less likely to outlive thread finalizers.
    if hasattr(pool, "setExpiryTimeout"):
        pool.setExpiryTimeout(0)
    if clear_queued:
        pool.clear()
    return bool(pool.waitForDone(max(0, int(timeout_ms))))


class MetadataSaveWorker(QRunnable):
    """Background worker to save metadata to database without blocking the UI.

    This unified worker replaces both _LabelSaveWorker and DBSaveWorker.
    """

    def __init__(self, db, file_path: str, data: dict):
        """Initialize the worker.

        Args:
            db: The database instance to save to.
            file_path: Path to the file being saved.
            data: Metadata dictionary to save.
        """
        super().__init__()
        self.db = db
        self.file_path = file_path
        self.data = data

    def run(self):
        try:
            self.db.save_metadata(self.file_path, self.data)
        except Exception as e:
            logger.error(f"Failed to save metadata for {self.file_path}: {e}")
