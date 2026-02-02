"""Background workers for saving metadata."""

from __future__ import annotations

import logging

from PySide6.QtCore import QRunnable

logger = logging.getLogger(__name__)


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
