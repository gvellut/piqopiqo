"""Multiprocessing worker entrypoints for background media processing.

This module must stay free of Qt imports. It is imported by spawned worker
processes.
"""

from __future__ import annotations

from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Any

from PIL import Image

from piqopiqo.keyword_utils import format_keywords, parse_keywords
from piqopiqo.metadata.db_fields import EXIF_TO_DB_MAPPING, GPS_REF_FIELDS, DBFields
from piqopiqo.metadata.metadata_db import parse_exif_datetime, parse_exif_gps

logger = logging.getLogger(__name__)


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return None
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _is_nonempty_file(path: str) -> bool:
    try:
        return os.path.getsize(path) > 0
    except OSError:
        return False


def extract_editable_metadata(exif_data: dict) -> dict:
    """Extract editable metadata fields from EXIF data."""
    result: dict[str, Any] = {}

    for db_field, exif_fields in EXIF_TO_DB_MAPPING.items():
        value = None
        for exif_field in exif_fields:
            if exif_field in exif_data:
                value = exif_data[exif_field]
                break

        if db_field in (DBFields.LATITUDE, DBFields.LONGITUDE):
            ref_field = GPS_REF_FIELDS[db_field]
            ref = exif_data.get(ref_field)
            value = parse_exif_gps(value, ref)

        if db_field == DBFields.KEYWORDS:
            if isinstance(value, list):
                value = format_keywords([str(k) for k in value])
            elif isinstance(value, str):
                keywords = parse_keywords(value)
                value = format_keywords(keywords)

        if db_field == DBFields.TIME_TAKEN and isinstance(value, str):
            value = parse_exif_datetime(value)

        if db_field == DBFields.ORIENTATION:
            # set the orientation to 1 if not there
            try:
                value = int(value)
                if not (1 <= value <= 8):
                    value = 1
            except (ValueError, TypeError):
                value = 1

        result[db_field] = value

    return result


def _build_mapping_tag_args() -> list[str]:
    tags: set[str] = set()
    for exif_fields in EXIF_TO_DB_MAPPING.values():
        tags.update(exif_fields)
    tags.update(GPS_REF_FIELDS.values())
    # exiftool syntax: -TAG
    return [f"-{tag}" for tag in sorted(tags)]


def _build_panel_tag_args(panel_field_keys: list[str]) -> list[str]:
    return [f"-{key}" for key in panel_field_keys]


def _index_metadata_by_sourcefile(
    file_paths: list[str], metadata_list: list[dict] | None
) -> dict[str, dict]:
    if not metadata_list:
        return {}

    indexed: dict[str, dict] = {}
    for entry in metadata_list:
        source_file = entry.get("SourceFile")
        if isinstance(source_file, str) and source_file:
            indexed[source_file] = entry

    if indexed:
        return indexed

    # Fallback: assume exiftool returned 1:1 in the input order
    if len(metadata_list) == len(file_paths):
        return dict(zip(file_paths, metadata_list, strict=False))

    return {}


def _extract_embedded_previews(
    helper,
    *,
    file_paths: list[str],
    thumb_dir: str,
    exiftool_path: str | None,
) -> dict[str, str | None]:
    """Extract embedded preview JPEGs to the thumb cache.

    Returns mapping file_path -> cache_path (or None if missing).
    """
    if not file_paths:
        return {}

    embedded_dir = Path(thumb_dir) / "embedded"
    embedded_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(embedded_dir / "%f.jpg")

    try:
        # Use ThumbnailImage instead of PreviewImage
        # PreviewImage is fine on Fuji (640x480): but on Panasonic : 1440x1080
        # it seems to create some stutter when displayed on the grid (~50 images)
        # TODO check again if comes from that
        # So use ThumbnailImage : 160x120 (used only as a placeholder while waiting
        # for the HQ thumbnail to be shown so fine
        helper.execute("-b", "-ThumbnailImage", "-w", pattern, *file_paths)
    except Exception:
        pass

    results: dict[str, str | None] = {}
    for file_path in file_paths:
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        cache_path = str(embedded_dir / f"{base_name}.jpg")
        results[file_path] = cache_path if _is_nonempty_file(cache_path) else None
    return results


def run_combined_task(task: dict) -> dict:
    """Run a combined EXIF + embedded-preview extraction task."""
    task_id = int(task["task_id"])
    source_folder = str(task["source_folder"])
    thumb_dir = str(task["thumb_dir"])
    exiftool_path = task.get("exiftool_path")
    panel_field_keys = list(task.get("panel_field_keys") or [])
    files: list[dict] = list(task.get("files") or [])

    import exiftool  # imported here to keep module import cheap in the parent

    items: list[dict] = []
    error: str | None = None

    now_iso = datetime.now().isoformat()

    try:
        with exiftool.ExifToolHelper(executable=exiftool_path) as helper:
            embedded_targets = [
                f["file_path"] for f in files if bool(f.get("want_embedded"))
            ]
            embedded_map = _extract_embedded_previews(
                helper,
                file_paths=[str(p) for p in embedded_targets],
                thumb_dir=thumb_dir,
                exiftool_path=exiftool_path,
            )

            want_editable_paths = [
                f["file_path"] for f in files if bool(f.get("want_editable"))
            ]
            want_panel_paths = [
                f["file_path"] for f in files if bool(f.get("want_panel"))
            ]

            editable_index: dict[str, dict] = {}
            panel_index: dict[str, dict] = {}

            if want_editable_paths:
                mapping_params = ["-G", "-n", "-use", "MWG", *_build_mapping_tag_args()]
                editable_list = helper.get_metadata(
                    [str(p) for p in want_editable_paths], mapping_params
                )
                editable_index = _index_metadata_by_sourcefile(
                    [str(p) for p in want_editable_paths], editable_list
                )

            if want_panel_paths:
                panel_params = [
                    "-G",
                    "-use",
                    "MWG",
                    *_build_panel_tag_args(panel_field_keys),
                ]
                panel_list = helper.get_metadata(
                    [str(p) for p in want_panel_paths], panel_params
                )
                panel_index = _index_metadata_by_sourcefile(
                    [str(p) for p in want_panel_paths], panel_list
                )

            for file_entry in files:
                file_path = str(file_entry["file_path"])

                editable_meta: dict | None = None
                if bool(file_entry.get("want_editable")):
                    raw = editable_index.get(file_path, {})
                    editable_meta = extract_editable_metadata(raw) if raw else {}

                panel_fields: dict[str, str | None] | None = None
                if bool(file_entry.get("want_panel")):
                    raw = panel_index.get(file_path, {})
                    panel_fields = {
                        key: _safe_str(raw.get(key)) for key in panel_field_keys
                    }

                items.append(
                    {
                        "file_path": file_path,
                        "source_folder": source_folder,
                        "editable_metadata": editable_meta,
                        "panel_fields": panel_fields,
                        "embedded_cache_path": embedded_map.get(file_path),
                        "now_iso": now_iso,
                    }
                )

    except Exception as e:
        logger.exception("Combined task failed")
        error = str(e)
        # Still return per-file stubs so the parent can mark completion.
        for file_entry in files:
            file_path = str(file_entry["file_path"])
            items.append(
                {
                    "file_path": file_path,
                    "source_folder": source_folder,
                    "editable_metadata": (
                        {} if bool(file_entry.get("want_editable")) else None
                    ),
                    "panel_fields": (
                        {key: None for key in panel_field_keys}
                        if bool(file_entry.get("want_panel"))
                        else None
                    ),
                    "embedded_cache_path": None,
                    "now_iso": now_iso,
                    "error": error,
                }
            )

    return {"task_id": task_id, "kind": "combined", "items": items, "error": error}


def generate_hq_thumbnail(source: str, dest_path: str, max_dim: int) -> bool:
    try:
        img = Image.open(source)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail((max_dim, max_dim))
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(dest_path, "JPEG", quality=80)
        return True
    except Exception:
        return False


def run_hq_thumb_task(task: dict) -> dict:
    task_id = int(task["task_id"])
    file_path = str(task["file_path"])
    thumb_dir = str(task["thumb_dir"])
    max_dim = int(task["max_dim"])

    base_name = os.path.splitext(os.path.basename(file_path))[0]
    cache_path = str(Path(thumb_dir) / "hq" / f"{base_name}.jpg")

    ok = generate_hq_thumbnail(file_path, cache_path, max_dim)
    return {
        "task_id": task_id,
        "kind": "hq_thumb",
        "file_path": file_path,
        "cache_path": cache_path if ok else None,
        "ok": bool(ok),
        "error": None if ok else "Failed to generate HQ thumbnail",
    }


def run_write_exif_task(task: dict) -> dict:
    task_id = int(task["task_id"])
    exiftool_path = task.get("exiftool_path")
    items: list[dict] = list(task.get("items") or [])

    import exiftool

    results: list[dict] = []
    try:
        # use overwrite_original_in_place instead of overwrite_original since
        # with overwrite_original the modified files have only the "added" change
        # with overwrite_original_in_place: it is modified
        common_args = ["-use", "MWG", "-overwrite_original_in_place", "-n"]
        with exiftool.ExifToolHelper(
            executable=exiftool_path, common_args=common_args
        ) as helper:
            for entry in items:
                file_path = str(entry["file_path"])
                tags = dict(entry.get("tags") or {})
                try:
                    helper.set_tags(file_path, tags)
                    results.append({"file_path": file_path, "ok": True, "error": ""})
                except Exception as e:
                    results.append(
                        {"file_path": file_path, "ok": False, "error": str(e)}
                    )
    except Exception as e:
        for entry in items:
            results.append(
                {"file_path": str(entry["file_path"]), "ok": False, "error": str(e)}
            )

    return {"task_id": task_id, "kind": "write_exif", "results": results}


def worker_main(task_queue, result_queue) -> None:
    """Worker loop."""
    try:
        import signal

        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:
        pass

    while True:
        task = task_queue.get()
        if task is None:
            break

        kind = task.get("kind")
        if kind == "stop":
            break

        try:
            if kind == "combined":
                result = run_combined_task(task)
            elif kind == "hq_thumb":
                result = run_hq_thumb_task(task)
            elif kind == "write_exif":
                result = run_write_exif_task(task)
            else:
                result = {
                    "task_id": int(task.get("task_id", -1)),
                    "kind": str(kind),
                    "error": f"Unknown task kind: {kind}",
                }
        except Exception as e:
            result = {
                "task_id": int(task.get("task_id", -1)),
                "kind": str(kind),
                "error": str(e),
            }

        result_queue.put(result)
