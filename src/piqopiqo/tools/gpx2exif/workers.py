"""QRunnable workers for GPX workflows."""

from __future__ import annotations

from datetime import datetime
import threading

from PySide6.QtCore import QObject, QRunnable, Signal

from .ocr_time_shift import extract_time_shift_from_photo
from .service import apply_gpx_to_folders


class ExtractGpsTimeShiftWorkerSignals(QObject):
    finished = Signal(str, str)  # extracted clock, extracted shift
    error = Signal(str)


class ExtractGpsTimeShiftWorker(QRunnable):
    def __init__(
        self,
        *,
        photo_path: str,
        exif_time: datetime,
        gcp_project: str,
        gcp_sa_key_path: str,
    ):
        super().__init__()
        self._photo_path = photo_path
        self._exif_time = exif_time
        self._gcp_project = gcp_project
        self._gcp_sa_key_path = gcp_sa_key_path
        self._cancel_requested = threading.Event()
        self.signals = ExtractGpsTimeShiftWorkerSignals()

    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def run(self) -> None:
        if self._cancel_requested.is_set():
            return

        try:
            extracted_clock, shift = extract_time_shift_from_photo(
                photo_path=self._photo_path,
                exif_time=self._exif_time,
                gcp_project=self._gcp_project,
                gcp_sa_key_path=self._gcp_sa_key_path,
            )
        except Exception as ex:  # pragma: no cover - external API failure
            if not self._cancel_requested.is_set():
                self.signals.error.emit(str(ex))
            return

        if not self._cancel_requested.is_set():
            self.signals.finished.emit(extracted_clock, shift)


class ApplyGpxWorkerSignals(QObject):
    folder_changed = Signal(str)
    progress = Signal(int, int)
    finished = Signal(object)  # ApplyGpxResult
    error = Signal(str)


class ApplyGpxWorker(QRunnable):
    def __init__(
        self,
        *,
        root_folder: str,
        folder_to_files: dict[str, list[str]],
        gpx_path: str,
        db_manager,
        timezone_name: str,
        ignore_offset: bool,
        kml_folder: str,
        update_db: bool,
        exiftool_path: str,
    ):
        super().__init__()
        self._root_folder = root_folder
        self._folder_to_files = folder_to_files
        self._gpx_path = gpx_path
        self._db_manager = db_manager
        self._timezone_name = timezone_name
        self._ignore_offset = ignore_offset
        self._kml_folder = kml_folder
        self._update_db = update_db
        self._exiftool_path = exiftool_path
        self._cancel_requested = threading.Event()
        self.signals = ApplyGpxWorkerSignals()

    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def _on_progress(self, completed: int, total: int) -> None:
        self.signals.progress.emit(completed, total)

    def _on_folder_changed(self, relative_folder: str) -> None:
        self.signals.folder_changed.emit(relative_folder)

    def run(self) -> None:
        try:
            result = apply_gpx_to_folders(
                root_folder=self._root_folder,
                folder_to_files=self._folder_to_files,
                gpx_path=self._gpx_path,
                db_manager=self._db_manager,
                timezone_name=self._timezone_name,
                ignore_offset=self._ignore_offset,
                kml_folder=self._kml_folder,
                update_db=self._update_db,
                exiftool_path=self._exiftool_path,
                cancel_event=self._cancel_requested,
                progress_callback=self._on_progress,
                folder_callback=self._on_folder_changed,
            )
        except Exception as ex:
            self.signals.error.emit(str(ex))
            return

        self.signals.finished.emit(result)
