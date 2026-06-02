"""QRunnable workers for GPX workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import threading
from typing import Any

from PySide6.QtCore import QObject, Signal

from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import (
    MetadataDBUnavailableError,
    parse_exif_datetime,
)
from piqopiqo.qt_workers import PythonOwnedRunnable

from .ocr_time_shift import extract_time_shift_from_photo
from .service import apply_gpx_to_folders

EXIF_TIME_TAKEN_TAG = "EXIF:DateTimeOriginal"


def _parse_original_time_taken(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None

    parsed = parse_exif_datetime(value)
    if parsed is not None:
        return parsed

    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _read_original_time_taken_from_exif(
    file_paths: list[str],
    exiftool_path: str | None,
) -> dict[str, datetime | None] | None:
    if not file_paths:
        return {}

    try:
        import exiftool

        with exiftool.ExifToolHelper(executable=exiftool_path or None) as helper:
            rows = helper.get_metadata(
                file_paths,
                ["-G", "-n", f"-{EXIF_TIME_TAKEN_TAG}"],
            )
    except Exception:
        return None

    if not rows:
        return {file_path: None for file_path in file_paths}

    out: dict[str, datetime | None] = {}
    for index, row in enumerate(rows):
        if any(str(key).endswith(":Error") or key == "Error" for key in row):
            continue

        source_file = row.get("SourceFile")
        if not isinstance(source_file, str) or not source_file:
            if index >= len(file_paths):
                continue
            source_file = file_paths[index]

        out[source_file] = _parse_original_time_taken(row.get(EXIF_TIME_TAKEN_TAG))

    return out


def load_original_time_taken_by_path(
    file_paths: list[str],
    db_manager,
    *,
    exiftool_path: str | None,
) -> dict[str, datetime | None]:
    exif_times = _read_original_time_taken_from_exif(
        file_paths,
        exiftool_path,
    )
    if exif_times is None:
        exif_times = {}

    out: dict[str, datetime | None] = {}
    for file_path in file_paths:
        if file_path in exif_times:
            out[file_path] = exif_times[file_path]
            continue

        db = db_manager.get_db_for_image(file_path)
        cached_fields = db.get_exif_fields(file_path, [EXIF_TIME_TAKEN_TAG])
        if not cached_fields or EXIF_TIME_TAKEN_TAG not in cached_fields:
            out[file_path] = None
            continue
        out[file_path] = _parse_original_time_taken(
            cached_fields.get(EXIF_TIME_TAKEN_TAG)
        )

    return out


class ExtractGpsTimeShiftWorkerSignals(QObject):
    finished = Signal(str, str)  # extracted clock, extracted shift
    error = Signal(str)


class ExtractGpsTimeShiftWorker(PythonOwnedRunnable):
    def __init__(
        self,
        *,
        photo_path: str,
        exif_time: datetime,
    ):
        super().__init__()
        self._photo_path = photo_path
        self._exif_time = exif_time
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


class ApplyGpxWorker(PythonOwnedRunnable):
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


@dataclass(frozen=True)
class ClearGpsResult:
    updated_paths: list[str]
    processed: int
    total: int
    cancelled: bool = False
    db_unavailable: bool = False


class ClearGpsWorkerSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(object)  # ClearGpsResult
    error = Signal(str)


class ClearGpsWorker(PythonOwnedRunnable):
    def __init__(
        self,
        *,
        db_manager,
        file_paths: list[str],
        exiftool_path: str | None,
    ):
        super().__init__()
        self._db_manager = db_manager
        self._file_paths = list(file_paths)
        self._exiftool_path = exiftool_path
        self._cancel_requested = threading.Event()
        self.signals = ClearGpsWorkerSignals()

    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def run(self) -> None:
        total = len(self._file_paths)
        processed = 0
        updated_paths: list[str] = []
        self.signals.progress.emit(0, total)

        try:
            original_time_taken_by_path = load_original_time_taken_by_path(
                self._file_paths,
                self._db_manager,
                exiftool_path=self._exiftool_path,
            )
            for file_path in self._file_paths:
                if self._cancel_requested.is_set():
                    self.signals.finished.emit(
                        ClearGpsResult(
                            updated_paths=updated_paths,
                            processed=processed,
                            total=total,
                            cancelled=True,
                        )
                    )
                    return

                db = self._db_manager.get_db_for_image(file_path)
                metadata = db.get_metadata(file_path)
                if metadata is not None:
                    updated_metadata = metadata.copy()
                    updated_metadata[DBFields.LATITUDE] = None
                    updated_metadata[DBFields.LONGITUDE] = None
                    updated_metadata[DBFields.TIME_TAKEN] = (
                        original_time_taken_by_path.get(file_path)
                    )
                    db.save_metadata(file_path, updated_metadata)
                    updated_paths.append(file_path)

                processed += 1
                self.signals.progress.emit(processed, total)
        except MetadataDBUnavailableError:
            self.signals.finished.emit(
                ClearGpsResult(
                    updated_paths=updated_paths,
                    processed=processed,
                    total=total,
                    db_unavailable=True,
                )
            )
            return
        except Exception as ex:
            self.signals.error.emit(str(ex))
            return

        self.signals.finished.emit(
            ClearGpsResult(
                updated_paths=updated_paths,
                processed=processed,
                total=total,
            )
        )
