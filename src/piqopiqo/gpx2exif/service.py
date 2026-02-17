"""Service layer for GPX-based metadata updates."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import logging
from pathlib import Path
import threading
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from attrs import define, field

from piqopiqo.metadata.db_fields import DBFields

from .constants import DEFAULT_GPX_TOLERANCE_SECONDS
from .gpx_processing import (
    build_kml_output_path,
    compute_position,
    get_gpx_time_range,
    load_gpx_segments,
    to_relative_folder,
    write_kml,
)
from .time_shift import parse_time_shift

if TYPE_CHECKING:
    from piqopiqo.metadata.metadata_db import MetadataDBManager

logger = logging.getLogger(__name__)


@define
class ApplyGpxFolderResult:
    folder: str
    relative_folder: str
    processed: int = 0
    updated: int = 0
    kml_path: str | None = None
    cancelled: bool = False
    rolled_back: bool = False
    errors: list[str] = field(factory=list)


@define
class ApplyGpxResult:
    processed: int = 0
    updated: int = 0
    cancelled: bool = False
    kml_paths: list[str] = field(factory=list)
    updated_paths: list[str] = field(factory=list)
    folder_results: list[ApplyGpxFolderResult] = field(factory=list)
    errors: list[str] = field(factory=list)


def _parse_exif_offset(value: str | None) -> timedelta:
    if not value:
        return timedelta(0)

    text = str(value).strip()
    if not text:
        return timedelta(0)

    sign = 1
    if text.startswith("+"):
        text = text[1:]
    elif text.startswith("-"):
        sign = -1
        text = text[1:]

    parts = text.split(":")
    if len(parts) not in (2, 3):
        return timedelta(0)

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2]) if len(parts) == 3 else 0
    except ValueError:
        return timedelta(0)

    return timedelta(hours=sign * hours, minutes=sign * minutes, seconds=sign * seconds)


def _read_exif_offsets(
    file_paths: list[str],
    exiftool_path: str,
) -> dict[str, timedelta]:
    if not file_paths:
        return {}

    import exiftool

    params = ["-G", "-EXIF:OffsetTimeOriginal"]
    with exiftool.ExifToolHelper(executable=exiftool_path) as helper:
        metadata_list = helper.get_metadata(file_paths, params=params)

    offsets: dict[str, timedelta] = {path: timedelta(0) for path in file_paths}
    for metadata in metadata_list:
        source = metadata.get("SourceFile")
        if not isinstance(source, str) or source not in offsets:
            continue
        offsets[source] = -_parse_exif_offset(metadata.get("EXIF:OffsetTimeOriginal"))

    return offsets


def _resolve_timezone_correction(
    timezone_name: str, gpx_start_utc: datetime
) -> timedelta:
    name = timezone_name.strip()
    if not name:
        return timedelta(0)

    if name == "auto":
        local_zone = datetime.now().astimezone().tzinfo
        if local_zone is None:
            return timedelta(0)
        offset = gpx_start_utc.astimezone(local_zone).utcoffset() or timedelta(0)
        return -offset

    try:
        zone = ZoneInfo(name)
    except ZoneInfoNotFoundError as ex:
        raise ValueError(f"Unknown timezone: {name}") from ex

    offset = gpx_start_utc.astimezone(zone).utcoffset() or timedelta(0)
    return -offset


def _to_utc_for_matching(
    photo_time: datetime,
    folder_shift: timedelta,
    extra_shift: timedelta,
) -> datetime:
    if photo_time.tzinfo is None:
        return (photo_time + folder_shift + extra_shift).replace(tzinfo=UTC)
    return photo_time.astimezone(UTC) + folder_shift + extra_shift


def _parse_folder_shift(raw_value: str | None) -> timedelta:
    if raw_value is None or not str(raw_value).strip():
        return timedelta(0)
    return parse_time_shift(str(raw_value).strip())


def apply_gpx_to_folders(
    *,
    root_folder: str,
    folder_to_files: dict[str, list[str]],
    gpx_path: str,
    db_manager: MetadataDBManager,
    timezone_name: str,
    ignore_offset: bool,
    kml_folder: str,
    update_db: bool,
    exiftool_path: str,
    tolerance_seconds: int = DEFAULT_GPX_TOLERANCE_SECONDS,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    folder_callback: Callable[[str], None] | None = None,
) -> ApplyGpxResult:
    """Process all source folders against one GPX file."""
    result = ApplyGpxResult()
    cancel_token = cancel_event or threading.Event()

    segments = load_gpx_segments(gpx_path)
    gpx_start, _ = get_gpx_time_range(segments)
    tolerance = timedelta(seconds=abs(int(tolerance_seconds)))

    folder_items = sorted(folder_to_files.items(), key=lambda item: item[0])
    total = sum(len(paths) for _, paths in folder_items)
    processed = 0

    if progress_callback is not None:
        progress_callback(0, total)

    timezone_correction: timedelta | None = None
    if timezone_name.strip():
        timezone_correction = _resolve_timezone_correction(timezone_name, gpx_start)

    for folder_path, file_paths in folder_items:
        relative_folder = to_relative_folder(root_folder, folder_path)
        folder_result = ApplyGpxFolderResult(
            folder=folder_path,
            relative_folder=relative_folder,
        )
        result.folder_results.append(folder_result)

        if folder_callback is not None:
            folder_callback(relative_folder)

        db = db_manager.get_db_for_folder(folder_path)
        try:
            folder_shift = _parse_folder_shift(db.get_time_shift())
        except ValueError as ex:
            message = f"Invalid time shift for {relative_folder}: {ex}"
            folder_result.errors.append(message)
            result.errors.append(message)
            folder_shift = timedelta(0)

        exif_offsets: dict[str, timedelta] = {}
        if timezone_correction is None and not ignore_offset:
            try:
                exif_offsets = _read_exif_offsets(file_paths, exiftool_path)
            except Exception as ex:  # pragma: no cover - external tool failure
                message = (
                    f"Failed to read EXIF offsets for {relative_folder}: {ex}. "
                    "Using +00:00."
                )
                folder_result.errors.append(message)
                result.errors.append(message)
                exif_offsets = {path: timedelta(0) for path in file_paths}

        snapshot: dict[str, dict] = {}
        folder_updated_paths: set[str] = set()
        folder_positions: list[tuple[tuple[float, float], str]] = []

        for file_path in sorted(file_paths):
            if cancel_token.is_set():
                folder_result.cancelled = True
                result.cancelled = True
                break

            metadata = db.get_metadata(file_path)
            if metadata is None:
                folder_result.errors.append(
                    f"Metadata not found for {Path(file_path).name}; skipped."
                )
                processed += 1
                folder_result.processed += 1
                if progress_callback is not None:
                    progress_callback(processed, total)
                continue

            time_taken = metadata.get(DBFields.TIME_TAKEN)
            if isinstance(time_taken, str):
                try:
                    time_taken = datetime.strptime(time_taken, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    time_taken = None

            extra_shift = timedelta(0)
            if timezone_correction is not None:
                extra_shift = timezone_correction
            elif not ignore_offset:
                extra_shift = exif_offsets.get(file_path, timedelta(0))

            position: tuple[float, float] | None = None
            if isinstance(time_taken, datetime):
                match_time = _to_utc_for_matching(time_taken, folder_shift, extra_shift)
                position = compute_position(match_time, segments, tolerance)

            if update_db:
                snapshot[file_path] = metadata.copy()
                updated_metadata = metadata.copy()

                if isinstance(time_taken, datetime):
                    updated_metadata[DBFields.TIME_TAKEN] = time_taken + folder_shift

                if position is None:
                    updated_metadata[DBFields.LATITUDE] = None
                    updated_metadata[DBFields.LONGITUDE] = None
                else:
                    lat, lon = position
                    updated_metadata[DBFields.LATITUDE] = lat
                    updated_metadata[DBFields.LONGITUDE] = lon

                db.save_metadata(file_path, updated_metadata)
                folder_updated_paths.add(file_path)

            if position is not None:
                folder_positions.append((position, file_path))

            processed += 1
            folder_result.processed += 1
            if progress_callback is not None:
                progress_callback(processed, total)

        if folder_result.cancelled:
            if update_db and folder_updated_paths:
                for file_path in sorted(folder_updated_paths):
                    previous = snapshot.get(file_path)
                    if previous is not None:
                        db.save_metadata(file_path, previous)
                folder_result.rolled_back = True
            break

        kml_path = build_kml_output_path(root_folder, folder_path, kml_folder)
        write_kml(folder_positions, kml_path)
        folder_result.kml_path = kml_path
        result.kml_paths.append(kml_path)

        if update_db:
            folder_result.updated = len(folder_updated_paths)
            result.updated_paths.extend(sorted(folder_updated_paths))

    result.processed = processed
    # Keep stable order and remove duplicates if any.
    seen: set[str] = set()
    deduped_updated_paths: list[str] = []
    for path in result.updated_paths:
        if path in seen:
            continue
        seen.add(path)
        deduped_updated_paths.append(path)
    result.updated_paths = deduped_updated_paths
    result.updated = len(result.updated_paths)

    if progress_callback is not None:
        progress_callback(result.processed, total)

    return result
