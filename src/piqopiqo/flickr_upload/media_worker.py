"""Multiprocessing worker entrypoints for Flickr upload workflows.

This module must stay free of Qt imports.
"""

from __future__ import annotations

from datetime import datetime
import logging
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any

from attrs import define

from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.exif_write import build_exif_tags

from .auth import create_flickr_client
from .constants import (
    API_RETRIES,
    CHECK_TICKETS_SLEEP_S,
    MAX_NUM_CHECKS,
    QUICK_TIMEOUT_S,
    STAGE_MAKE_PUBLIC,
    STAGE_RESET_DATE,
    STAGE_UPLOAD,
    UPLOAD_TIMEOUT_S,
)
from .service import (
    TicketStatus,
    classify_ticket_complete,
    format_flickr_tags_from_db_keywords,
    retry,
)

logger = logging.getLogger(__name__)


@define
class PhotoTicketStatus:
    status: TicketStatus
    photo_id: str | None
    file_path: str
    order: int
    api_tags: str | None


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _to_int_timestamp(value: datetime | int | float) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp())
    return int(value)


def _create_temp_copy(source_path: str) -> str:
    suffix = Path(source_path).suffix
    with tempfile.NamedTemporaryFile(
        prefix="piqo_flickr_",
        suffix=suffix,
        delete=False,
    ) as tmp:
        temp_path = tmp.name
    shutil.copy2(source_path, temp_path)
    return temp_path


def _write_exif_to_temp_file(
    temp_path: str,
    exiftool_path: str,
    db_metadata: dict,
) -> None:
    tags = build_exif_tags(db_metadata)
    if not tags:
        return

    import exiftool

    with exiftool.ExifToolHelper(
        executable=exiftool_path,
        common_args=["-use", "MWG"],
    ) as helper:
        helper.set_tags(temp_path, tags, params=["-overwrite_original"])


def _extract_title_and_tags(db_metadata: dict | None) -> tuple[str | None, str | None]:
    if not db_metadata:
        return None, None

    title = db_metadata.get(DBFields.TITLE)
    if title is not None:
        title = str(title).strip() or None

    flickr_tags = format_flickr_tags_from_db_keywords(
        db_metadata.get(DBFields.KEYWORDS)
    )
    return title, flickr_tags


def run_upload_task(task: dict) -> dict:
    """Upload one photo asynchronously and return its ticket id."""
    file_path = str(task["file_path"])
    order = int(task.get("order", 0))
    api_key = str(task["api_key"])
    api_secret = str(task["api_secret"])
    token_cache_dir = str(task["token_cache_dir"])
    exiftool_path = str(task.get("exiftool_path") or "")
    db_metadata = task.get("db_metadata")

    temp_path = None
    flickr_tags = None

    try:
        temp_path = _create_temp_copy(file_path)

        if isinstance(db_metadata, dict) and db_metadata:
            if not exiftool_path:
                raise ValueError("Exiftool path is empty; cannot update temp EXIF tags")
            _write_exif_to_temp_file(temp_path, exiftool_path, db_metadata)

        title, flickr_tags = _extract_title_and_tags(
            db_metadata if isinstance(db_metadata, dict) else None
        )

        flickr = create_flickr_client(
            api_key,
            api_secret,
            token_cache_dir=token_cache_dir,
            response_format="parsed-json",
        )

        def _upload_call():
            return flickr.upload(
                filename=temp_path,
                title=title,
                tags=flickr_tags,
                is_public=0,
                format="etree",
                timeout=UPLOAD_TIMEOUT_S,
                **{"async": 1},
            )

        response = retry(API_RETRIES, _upload_call)
        if response is None:
            raise RuntimeError("Upload returned no response")

        ticket_node = response.find("ticketid")
        ticket_id = ticket_node.text if ticket_node is not None else None
        if not ticket_id:
            raise RuntimeError("No ticket id returned by Flickr upload")

        return {
            "ok": True,
            "stage": STAGE_UPLOAD,
            "file_path": file_path,
            "order": order,
            "ticket_id": str(ticket_id),
            "api_tags": flickr_tags,
            "db_metadata": db_metadata,
        }
    except Exception as ex:
        return {
            "ok": False,
            "stage": STAGE_UPLOAD,
            "file_path": file_path,
            "order": order,
            "error": str(ex),
        }
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                logger.debug("Failed deleting temp upload file: %s", temp_path)


def _extract_ticket_rows(response: dict) -> list[dict]:
    uploader = response.get("uploader") if isinstance(response, dict) else None
    if not isinstance(uploader, dict):
        return []
    return [row for row in _as_list(uploader.get("ticket")) if isinstance(row, dict)]


def _get_uploaded_photos_indirect(
    flickr,
    number: int,
    since_time: datetime | int | float | None,
    margin_s: int = 10,
) -> tuple[list[dict], bool]:
    date_s = None
    if since_time is not None:
        date_s = _to_int_timestamp(since_time) - int(margin_s)

    photos_uploaded: list[dict] = []
    page = 1
    per_page = min(max(number, 10), 500)

    while len(photos_uploaded) < number:
        kwargs: dict[str, Any] = {
            "user_id": "me",
            "page": page,
            "per_page": per_page,
            "sort": "date-posted-desc",
            "extras": "date_taken,tags",
        }
        if date_s is not None:
            kwargs["min_upload_date"] = date_s

        page_response = flickr.photos.search(**kwargs)
        photos_root = page_response.get("photos", {})
        rows = _as_list(photos_root.get("photo"))
        rows = [row for row in rows if isinstance(row, dict)]

        if not rows:
            break

        photos_uploaded.extend(rows)

        try:
            pages = int(photos_root.get("pages", 1))
            current_page = int(photos_root.get("page", page))
        except (TypeError, ValueError):
            break

        if current_page >= pages:
            break
        page += 1

    if len(photos_uploaded) < number:
        return [], True

    photos_uploaded = photos_uploaded[:number]
    photos_uploaded.sort(key=lambda row: str(row.get("datetaken", "")))
    return photos_uploaded, False


def _reupload_photos_without_tags(
    flickr,
    upload_entries: list[dict],
    uploaded_photos: list[dict],
    *,
    exiftool_path: str,
) -> list[dict]:
    """Re-upload photos whose tags are unexpectedly empty after async upload."""
    failures: list[dict] = []
    ordered_entries = sorted(upload_entries, key=lambda row: int(row["order"]))

    for idx in range(min(len(ordered_entries), len(uploaded_photos))):
        local = ordered_entries[idx]
        remote = uploaded_photos[idx]

        flickr_photo_tags = str(remote.get("tags", "") or "").strip()
        if flickr_photo_tags:
            continue

        local_tags = local.get("api_tags")
        if not local_tags:
            continue

        remote_photo_id = str(remote.get("id", "") or "")
        if not remote_photo_id:
            failures.append(
                {
                    "stage": STAGE_UPLOAD,
                    "file_path": str(local.get("file_path", "")),
                    "error": "Missing photo id while retrying tag reupload.",
                }
            )
            continue

        temp_path = None
        try:
            file_path = str(local["file_path"])
            temp_path = _create_temp_copy(file_path)

            db_metadata = local.get("db_metadata")
            if isinstance(db_metadata, dict) and db_metadata:
                if not exiftool_path:
                    raise ValueError(
                        "Exiftool path is empty; cannot update temp EXIF tags"
                    )
                _write_exif_to_temp_file(temp_path, exiftool_path, db_metadata)

            def _replace_call(
                temp_path=temp_path,
                remote_photo_id=remote_photo_id,
            ):
                return flickr.replace(
                    temp_path,
                    remote_photo_id,
                    format="rest",
                    timeout=UPLOAD_TIMEOUT_S,
                )

            def _add_tags_call(
                remote_photo_id=remote_photo_id,
                local_tags=local_tags,
            ):
                return flickr.photos.addTags(photo_id=remote_photo_id, tags=local_tags)

            retry(API_RETRIES, _replace_call)
            retry(API_RETRIES, _add_tags_call)
        except Exception as ex:
            failures.append(
                {
                    "stage": STAGE_UPLOAD,
                    "file_path": str(local.get("file_path", "")),
                    "error": f"Reupload failed: {ex}",
                }
            )
        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    logger.debug("Failed deleting temp replace file: %s", temp_path)

    return failures


def run_resolve_tickets_task(task: dict) -> dict:
    """Resolve upload tickets and return ordered Flickr photo ids."""
    api_key = str(task["api_key"])
    api_secret = str(task["api_secret"])
    token_cache_dir = str(task["token_cache_dir"])
    now_ts = int(task["now_ts"])
    upload_entries = list(task.get("upload_entries") or [])
    exiftool_path = str(task.get("exiftool_path") or "")

    flickr = create_flickr_client(
        api_key,
        api_secret,
        token_cache_dir=token_cache_dir,
        response_format="parsed-json",
    )

    ticket_status: dict[str, PhotoTicketStatus] = {}
    for entry in upload_entries:
        ticket_id = str(entry.get("ticket_id", "") or "")
        if not ticket_id:
            continue
        ticket_status[ticket_id] = PhotoTicketStatus(
            status=TicketStatus.INCOMPLETE,
            photo_id=None,
            file_path=str(entry.get("file_path", "")),
            order=int(entry.get("order", 0)),
            api_tags=entry.get("api_tags"),
        )

    if not ticket_status:
        return {
            "ok": False,
            "fatal_error": "No upload ticket to resolve.",
            "photo_ids": [],
            "failures": [],
        }

    checks = 0
    while True:
        to_check = [
            k
            for k, status in ticket_status.items()
            if status.status == TicketStatus.INCOMPLETE
        ]
        if not to_check:
            break

        response = flickr.photos.upload.checkTickets(tickets=",".join(to_check))
        rows = _extract_ticket_rows(response)

        incomplete_found = False
        for row in rows:
            ticket_id = str(row.get("id", "") or "")
            if ticket_id not in ticket_status:
                continue

            current = ticket_status[ticket_id]
            current_status = classify_ticket_complete(row.get("complete"))

            if current_status == TicketStatus.INCOMPLETE:
                incomplete_found = True
                continue

            if current_status == TicketStatus.COMPLETE:
                ticket_status[ticket_id] = PhotoTicketStatus(
                    status=TicketStatus.COMPLETE,
                    photo_id=str(row.get("photoid", "") or ""),
                    file_path=current.file_path,
                    order=current.order,
                    api_tags=current.api_tags,
                )
                continue

            ticket_status[ticket_id] = PhotoTicketStatus(
                status=TicketStatus.INVALID,
                photo_id=None,
                file_path=current.file_path,
                order=current.order,
                api_tags=current.api_tags,
            )

        if incomplete_found:
            checks += 1
            if checks >= MAX_NUM_CHECKS:
                break
            time.sleep(CHECK_TICKETS_SLEEP_S)
        else:
            break

    sorted_statuses = sorted(ticket_status.values(), key=lambda row: row.order)

    invalid = [row for row in sorted_statuses if row.status == TicketStatus.INVALID]
    if invalid:
        names = ", ".join(os.path.basename(row.file_path) for row in invalid)
        return {
            "ok": False,
            "fatal_error": (
                f"Not all photos uploaded: invalid Flickr upload ticket(s): {names}."
            ),
            "photo_ids": [],
            "failures": [],
        }

    incomplete = [
        row for row in sorted_statuses if row.status == TicketStatus.INCOMPLETE
    ]
    if incomplete:
        uploaded, not_found = _get_uploaded_photos_indirect(
            flickr,
            len(upload_entries),
            now_ts,
        )
        if not_found:
            return {
                "ok": False,
                "fatal_error": (
                    "Not all photos uploaded: incomplete ticket state could not be "
                    "reconciled from photostream."
                ),
                "photo_ids": [],
                "failures": [],
            }

        failures = _reupload_photos_without_tags(
            flickr,
            upload_entries,
            uploaded,
            exiftool_path=exiftool_path,
        )
        return {
            "ok": True,
            "fatal_error": "",
            "photo_ids": [
                str(photo.get("id", "")) for photo in uploaded if photo.get("id")
            ],
            "failures": failures,
        }

    return {
        "ok": True,
        "fatal_error": "",
        "photo_ids": [
            row.photo_id
            for row in sorted_statuses
            if row.status == TicketStatus.COMPLETE and row.photo_id
        ],
        "failures": [],
    }


def run_set_date_task(task: dict) -> dict:
    """Reset one photo uploaded date timestamp."""
    photo_id = str(task["photo_id"])
    timestamp = int(task["timestamp"])
    api_key = str(task["api_key"])
    api_secret = str(task["api_secret"])
    token_cache_dir = str(task["token_cache_dir"])
    file_path = str(task.get("file_path") or "")

    try:
        flickr = create_flickr_client(
            api_key,
            api_secret,
            token_cache_dir=token_cache_dir,
            response_format="parsed-json",
        )

        def _set_dates_call():
            return flickr.photos.setDates(
                photo_id=photo_id,
                date_posted=timestamp,
                timeout=QUICK_TIMEOUT_S,
            )

        retry(API_RETRIES, _set_dates_call)
        return {
            "ok": True,
            "stage": STAGE_RESET_DATE,
            "photo_id": photo_id,
            "file_path": file_path,
        }
    except Exception as ex:
        return {
            "ok": False,
            "stage": STAGE_RESET_DATE,
            "photo_id": photo_id,
            "file_path": file_path,
            "error": str(ex),
        }


def run_set_public_task(task: dict) -> dict:
    """Set one photo visibility to public."""
    photo_id = str(task["photo_id"])
    api_key = str(task["api_key"])
    api_secret = str(task["api_secret"])
    token_cache_dir = str(task["token_cache_dir"])
    file_path = str(task.get("file_path") or "")

    try:
        flickr = create_flickr_client(
            api_key,
            api_secret,
            token_cache_dir=token_cache_dir,
            response_format="parsed-json",
        )

        def _set_public_call():
            return flickr.photos.setPerms(
                photo_id=photo_id,
                is_public=1,
                is_family=0,
                is_friend=0,
                timeout=QUICK_TIMEOUT_S,
            )

        retry(API_RETRIES, _set_public_call)
        return {
            "ok": True,
            "stage": STAGE_MAKE_PUBLIC,
            "photo_id": photo_id,
            "file_path": file_path,
        }
    except Exception as ex:
        return {
            "ok": False,
            "stage": STAGE_MAKE_PUBLIC,
            "photo_id": photo_id,
            "file_path": file_path,
            "error": str(ex),
        }
