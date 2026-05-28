"""Background workers for saving metadata."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThreadPool, Signal

from piqopiqo.qt_workers import PythonOwnedRunnable

from .metadata_db import MetadataDBUnavailableError

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


class MetadataSaveWorker(PythonOwnedRunnable):
    """Background worker to save metadata to database without blocking the UI.

    This unified worker replaces both _LabelSaveWorker and DBSaveWorker.
    """

    class Signals(QObject):
        finished = Signal(str)
        failed = Signal(object)

    def __init__(
        self,
        db_manager,
        file_path: str,
        data: dict,
        *,
        changed_fields: set[str] | None = None,
        source: str = "metadata_save",
        safe_to_replay: bool = True,
    ):
        """Initialize the worker.

        Args:
            db_manager: The database manager used to resolve a fresh DB instance.
            file_path: Path to the file being saved.
            data: Metadata dictionary to save.
        """
        super().__init__()
        self.db_manager = db_manager
        self.file_path = file_path
        self.data = data
        self.changed_fields = {str(field) for field in changed_fields or set() if field}
        self.source = str(source)
        self.safe_to_replay = bool(safe_to_replay)
        self.signals = self.Signals()

    def run(self):
        try:
            db = self.db_manager.get_db_for_image(self.file_path)
            db.save_metadata(self.file_path, self.data)
            self.signals.finished.emit(self.file_path)
        except MetadataDBUnavailableError as exc:
            self.signals.failed.emit({
                "file_path": self.file_path,
                "data": self.data.copy(),
                "changed_fields": set(self.changed_fields),
                "fault": exc.fault,
                "safe_to_replay": self.safe_to_replay,
                "source": self.source,
            })
        except Exception as e:
            logger.error(f"Failed to save metadata for {self.file_path}: {e}")
            self.signals.failed.emit({
                "file_path": self.file_path,
                "data": self.data.copy(),
                "changed_fields": set(self.changed_fields),
                "fault": None,
                "safe_to_replay": False,
                "source": self.source,
                "error_message": str(e),
            })
