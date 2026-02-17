"""Flickr upload manager orchestrating multiprocessing worker execution."""

from __future__ import annotations

from datetime import datetime
import multiprocessing
import threading
import time
from typing import Any

from attrs import define, field
from PySide6.QtCore import QObject, Signal

from .constants import (
    STAGE_MAKE_PUBLIC,
    STAGE_RESET_DATE,
    STAGE_UPLOAD,
)
from .media_worker import (
    run_resolve_tickets_task,
    run_set_date_task,
    run_set_public_task,
    run_upload_task,
)
from .service import generate_timestamps


@define(frozen=True)
class FlickrUploadPhotoFailure:
    file_path: str
    stage: str
    message: str


@define
class FlickrUploadResult:
    total_photos: int = 0
    uploaded_count: int = 0
    reset_date_count: int = 0
    made_public_count: int = 0
    uploaded_photo_ids: list[str] = field(factory=list)
    cancelled: bool = False
    fatal_error: str = ""
    failures: list[FlickrUploadPhotoFailure] = field(factory=list)


class FlickrUploadManager(QObject):
    """Manage Flickr upload stages and progress in background threads/processes."""

    stage_changed = Signal(str)
    progress = Signal(int, int)
    status = Signal(str)
    finished = Signal(object)  # FlickrUploadResult

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        exiftool_path: str,
        token_cache_dir: str,
        max_workers: int,
        parent=None,
    ):
        super().__init__(parent)
        self._api_key = api_key
        self._api_secret = api_secret
        self._exiftool_path = exiftool_path
        self._token_cache_dir = token_cache_dir
        self._max_workers = max(1, int(max_workers))

        self._cancel_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_lock = threading.Lock()

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, items: list[dict]) -> None:
        if self.is_running():
            return

        self._cancel_requested.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(list(items),),
            daemon=True,
        )
        self._thread.start()

    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def stop(self, timeout_s: float = 5.0) -> None:
        self.request_cancel()
        thread = self._thread
        if thread is None:
            return
        thread.join(timeout=max(0.0, float(timeout_s)))

    def _run(self, items: list[dict]) -> None:
        with self._run_lock:
            result = FlickrUploadResult(total_photos=len(items))
            try:
                if not items:
                    return

                photo_pairs = self._run_upload_stage(items, result)
                if result.cancelled or result.fatal_error or not photo_pairs:
                    return

                self._run_reset_date_stage(photo_pairs, result)
                if result.cancelled:
                    return

                self._run_make_public_stage(photo_pairs, result)
            except Exception as ex:  # pragma: no cover - defensive
                result.fatal_error = str(ex)
            finally:
                self.finished.emit(result)

    def _build_worker_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        base = {
            "api_key": self._api_key,
            "api_secret": self._api_secret,
            "token_cache_dir": self._token_cache_dir,
        }
        base.update(payload)
        return base

    def _run_upload_stage(
        self,
        items: list[dict],
        result: FlickrUploadResult,
    ) -> list[dict]:
        self.stage_changed.emit(STAGE_UPLOAD)
        self.progress.emit(0, len(items))

        payloads = [
            self._build_worker_payload(
                {
                    "file_path": str(item["file_path"]),
                    "order": int(item["order"]),
                    "db_metadata": item.get("db_metadata"),
                    "exiftool_path": self._exiftool_path,
                }
            )
            for item in items
        ]

        upload_results = self._run_parallel_pool(
            run_upload_task,
            payloads,
            stage=STAGE_UPLOAD,
            progress_total=len(items),
            result=result,
        )
        if result.cancelled:
            return []

        upload_successes: list[dict] = []
        for row in upload_results:
            if row.get("ok"):
                upload_successes.append(row)
                continue
            result.failures.append(
                FlickrUploadPhotoFailure(
                    file_path=str(row.get("file_path", "")),
                    stage=STAGE_UPLOAD,
                    message=str(row.get("error", "Upload failed")),
                )
            )

        if not upload_successes:
            result.fatal_error = "No photos were successfully uploaded."
            return []

        resolve_payload = self._build_worker_payload(
            {
                "now_ts": int(datetime.now().timestamp()),
                "upload_entries": upload_successes,
                "exiftool_path": self._exiftool_path,
            }
        )

        resolve = run_resolve_tickets_task(resolve_payload)
        for failure in resolve.get("failures", []):
            result.failures.append(
                FlickrUploadPhotoFailure(
                    file_path=str(failure.get("file_path", "")),
                    stage=str(failure.get("stage", STAGE_UPLOAD)),
                    message=str(failure.get("error", "Upload verification warning")),
                )
            )

        if not resolve.get("ok"):
            result.fatal_error = str(
                resolve.get("fatal_error", "Upload verification failed")
            )
            return []

        photo_ids = [str(x) for x in resolve.get("photo_ids", []) if str(x)]
        ordered_successes = sorted(upload_successes, key=lambda row: int(row["order"]))
        photo_pairs = [
            {
                "photo_id": photo_id,
                "file_path": str(entry["file_path"]),
                "order": int(entry["order"]),
            }
            for photo_id, entry in zip(photo_ids, ordered_successes, strict=False)
        ]

        if not photo_pairs:
            result.fatal_error = "No uploaded photo id could be resolved from Flickr."
            return []

        result.uploaded_photo_ids = [row["photo_id"] for row in photo_pairs]
        result.uploaded_count = len(photo_pairs)
        return photo_pairs

    def _run_reset_date_stage(
        self,
        photo_pairs: list[dict],
        result: FlickrUploadResult,
    ) -> None:
        self.stage_changed.emit(STAGE_RESET_DATE)
        total = len(photo_pairs)
        self.progress.emit(0, total)

        now_ts = int(datetime.now().timestamp())
        timestamps = generate_timestamps(now_ts, total)
        payloads = [
            self._build_worker_payload(
                {
                    "photo_id": row["photo_id"],
                    "file_path": row["file_path"],
                    "timestamp": ts,
                }
            )
            for row, ts in zip(photo_pairs, timestamps, strict=True)
        ]

        stage_results = self._run_parallel_pool(
            run_set_date_task,
            payloads,
            stage=STAGE_RESET_DATE,
            progress_total=total,
            result=result,
        )

        if result.cancelled:
            return

        success_count = 0
        for row in stage_results:
            if row.get("ok"):
                success_count += 1
                continue
            result.failures.append(
                FlickrUploadPhotoFailure(
                    file_path=str(row.get("file_path", "")),
                    stage=STAGE_RESET_DATE,
                    message=str(row.get("error", "Failed to reset upload date")),
                )
            )

        result.reset_date_count = success_count

    def _run_make_public_stage(
        self,
        photo_pairs: list[dict],
        result: FlickrUploadResult,
    ) -> None:
        self.stage_changed.emit(STAGE_MAKE_PUBLIC)
        total = len(photo_pairs)
        self.progress.emit(0, total)

        payloads = [
            self._build_worker_payload(
                {
                    "photo_id": row["photo_id"],
                    "file_path": row["file_path"],
                }
            )
            for row in photo_pairs
        ]

        stage_results = self._run_parallel_pool(
            run_set_public_task,
            payloads,
            stage=STAGE_MAKE_PUBLIC,
            progress_total=total,
            result=result,
        )

        if result.cancelled:
            return

        success_count = 0
        for row in stage_results:
            if row.get("ok"):
                success_count += 1
                continue
            result.failures.append(
                FlickrUploadPhotoFailure(
                    file_path=str(row.get("file_path", "")),
                    stage=STAGE_MAKE_PUBLIC,
                    message=str(row.get("error", "Failed to make photo public")),
                )
            )

        result.made_public_count = success_count

    def _run_parallel_pool(
        self,
        func,
        payloads: list[dict],
        *,
        stage: str,
        progress_total: int,
        result: FlickrUploadResult,
    ) -> list[dict]:
        if not payloads:
            return []

        ctx = multiprocessing.get_context("spawn")
        completed = 0
        rows: list[dict] = []

        with ctx.Pool(processes=self._max_workers) as pool:
            pending = [pool.apply_async(func, (payload,)) for payload in payloads]

            while pending:
                if self._cancel_requested.is_set():
                    pool.terminate()
                    pool.join()
                    result.cancelled = True
                    return rows

                still_pending = []
                for task in pending:
                    if not task.ready():
                        still_pending.append(task)
                        continue
                    row = task.get()
                    rows.append(row)
                    completed += 1
                    self.progress.emit(completed, progress_total)
                pending = still_pending

                if pending:
                    time.sleep(0.05)

            pool.close()
            pool.join()

        # make sure progress hits final value
        self.progress.emit(progress_total, progress_total)
        self.status.emit(stage)
        return rows
