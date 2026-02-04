"""Background EXIF loader for editable metadata fields."""

import logging
import threading

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .config import Config
from .keyword_utils import format_keywords, parse_keywords
from .metadata.db_fields import EXIF_TO_DB_MAPPING, GPS_REF_FIELDS, DBFields
from .metadata.metadata_db import MetadataDBManager, parse_exif_datetime, parse_exif_gps

logger = logging.getLogger(__name__)


def extract_editable_metadata(exif_data: dict) -> dict:
    """Extract editable metadata fields from EXIF data.

    Args:
        exif_data: Raw EXIF data dictionary from exiftool.

    Returns:
        Dictionary with DB field names as keys.
    """
    result = {}

    for db_field, exif_fields in EXIF_TO_DB_MAPPING.items():
        value = None
        for exif_field in exif_fields:
            if exif_field in exif_data:
                value = exif_data[exif_field]
                break

        # Special handling for GPS
        if db_field in (DBFields.LATITUDE, DBFields.LONGITUDE):
            ref_field = GPS_REF_FIELDS[db_field]
            ref = exif_data.get(ref_field)
            value = parse_exif_gps(value, ref)

        # Special handling for keywords (may be array or string with quotes)
        if db_field == DBFields.KEYWORDS:
            if isinstance(value, list):
                # Format list using proper quoting for commas
                value = format_keywords([str(k) for k in value])
            elif isinstance(value, str):
                # Parse and re-format to normalize (handles quoted values)
                keywords = parse_keywords(value)
                value = format_keywords(keywords)

        # Parse EXIF datetime string to datetime object
        if db_field == DBFields.TIME_TAKEN and isinstance(value, str):
            value = parse_exif_datetime(value)

        # Parse orientation as integer (1-8)
        if db_field == DBFields.ORIENTATION and value is not None:
            try:
                value = int(value)
                # Validate range (1-8 are valid EXIF orientation values)
                if not (1 <= value <= 8):
                    value = 1  # Default to normal orientation
            except (ValueError, TypeError):
                value = 1

        result[db_field] = value

    return result


class ExifLoaderWorkerSignals(QObject):
    """Signals for ExifLoaderWorker."""

    finished = Signal(str, dict)  # file_path, metadata
    error = Signal(str, str)  # file_path, error_message


class ExifLoaderWorker(QRunnable):
    """Worker that loads EXIF data for a single image."""

    def __init__(
        self,
        file_path: str,
        source_folder: str,
        etHelper,
        db_manager: MetadataDBManager,
        exif_lock: threading.Lock | None = None,
    ):
        super().__init__()
        self.file_path = file_path
        self.source_folder = source_folder
        self.etHelper = etHelper
        self.db_manager = db_manager
        self.exif_lock = exif_lock
        self.signals = ExifLoaderWorkerSignals()

    def run(self):
        try:
            # Read EXIF data
            if self.exif_lock is None:
                exif_results = self.etHelper.get_metadata(self.file_path)
            else:
                with self.exif_lock:
                    exif_results = self.etHelper.get_metadata(self.file_path)
            if not exif_results:
                self.signals.error.emit(self.file_path, "No EXIF data found")
                return

            exif_data = exif_results[0]

            # Extract editable fields
            metadata = extract_editable_metadata(exif_data)

            # Save to database
            db = self.db_manager.get_db_for_folder(self.source_folder)
            db.save_metadata(self.file_path, metadata)

            self.signals.finished.emit(self.file_path, metadata)

        except Exception as e:
            logger.error(f"Failed to load EXIF for {self.file_path}: {e}")
            self.signals.error.emit(self.file_path, str(e))


class ExifLoaderManager(QObject):
    """Background EXIF loader for editable metadata fields."""

    # Signals
    exif_loaded = Signal(str, dict)  # file_path, metadata_dict
    exif_error = Signal(str, str)  # file_path, error_message
    progress_updated = Signal(int, int)  # completed, total
    all_completed = Signal()  # emitted when all tasks are done

    def __init__(
        self,
        etHelper,
        db_manager: MetadataDBManager,
        exif_lock: threading.Lock | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.etHelper = etHelper
        self.db_manager = db_manager
        self._exif_lock = exif_lock
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(Config.MAX_WORKERS)
        self._pending: set[str] = set()
        self._target_total = 0
        self._completed = 0
        self._errors: dict[str, str] = {}

    def prime_from_db(self, images: list):
        """Prime in-memory metadata from DB for fast initial grid display.

        For items missing metadata in the DB, they will be queued for EXIF loading.

        Args:
            images: List of ImageItem objects.
        """
        for item in images:
            db = self.db_manager.get_db_for_folder(item.source_folder)
            meta = db.get_metadata(item.path)
            if meta:
                self._completed += 1
                self.progress_updated.emit(self._completed, self._target_total)
                self.exif_loaded.emit(item.path, meta)
            else:
                self.queue_image(item.path, item.source_folder, force=True)

        self._check_all_completed()

    def queue_image(self, file_path: str, source_folder: str, force: bool = False):
        """Queue an image for EXIF loading.

        Args:
            file_path: Path to the image file.
            source_folder: Path to the source folder.
            force: If True, reload even if already in DB.
        """
        # When called after completion (e.g. Refresh button), extend target total
        if force and self._target_total > 0 and self._completed >= self._target_total:
            self._target_total = self._completed + 1

        if file_path in self._pending:
            return

        self._pending.add(file_path)

        worker = ExifLoaderWorker(
            file_path,
            source_folder,
            self.etHelper,
            self.db_manager,
            self._exif_lock,
        )
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)

        self.progress_updated.emit(self._completed, self._target_total)

    def queue_images(self, images: list):
        """Queue all images from a list.

        Args:
            images: List of ImageItem objects.
        """
        for item in images:
            self.queue_image(item.path, item.source_folder)

    def _on_worker_finished(self, file_path: str, metadata: dict):
        """Handle worker completion."""
        if file_path in self._pending:
            self._pending.remove(file_path)

        self._completed += 1
        self.progress_updated.emit(self._completed, self._target_total)
        self.exif_loaded.emit(file_path, metadata)

        self._check_all_completed()

    def _on_worker_error(self, file_path: str, error_message: str):
        """Handle worker error."""
        if file_path in self._pending:
            self._pending.remove(file_path)

        self._completed += 1
        self._errors[file_path] = error_message
        self.progress_updated.emit(self._completed, self._target_total)
        self.exif_error.emit(file_path, error_message)

        self._check_all_completed()

    def _check_all_completed(self):
        """Check if all tasks are completed and emit signal."""
        if self._completed >= self._target_total and self._target_total > 0:
            self.all_completed.emit()

    def get_errors(self) -> dict[str, str]:
        """Get dictionary of file paths with errors."""
        return self._errors.copy()

    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self._errors) > 0

    def reset(self, target_total: int = 0):
        """Reset counters for new folder load."""
        self._target_total = target_total
        self._completed = 0
        self._errors.clear()
        self._pending.clear()

    def get_progress(self) -> tuple[int, int]:
        """Get current progress.

        Returns:
            Tuple of (completed, total).
        """
        return self._completed, self._target_total

    def stop(self, wait_ms: int = 2000) -> None:
        """Stop background work.

        Clears queued jobs and waits briefly for running jobs to finish.
        """
        self.thread_pool.clear()
        self.thread_pool.waitForDone(wait_ms)
