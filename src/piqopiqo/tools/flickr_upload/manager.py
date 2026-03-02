"""Flickr upload manager orchestrating multiprocessing worker execution."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import multiprocessing
import threading
import time
from typing import Any

from attrs import define, field
from PySide6.QtCore import QObject, Signal

from .albums import FlickrAlbumPlan
from .constants import MAX_NUM_CHECKS, FlickrStage
from .media_worker import (
    run_add_to_album_task,
    run_create_album_task,
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
    album_id: str = ""
    album_title: str = ""
    album_user_nsid: str = ""
    album_url: str = ""
    album_created: bool = False
    album_added_count: int = 0
    cancelled: bool = False
    fatal_error: str = ""
    failures: list[FlickrUploadPhotoFailure] = field(factory=list)


class FlickrUploadManager(QObject):
    """Manage Flickr upload stages and progress in background threads/processes."""

    stage_changed = Signal(str)
    progress = Signal(int, int)
    status = Signal(str)
    album_status = Signal(str)
    finished = Signal(object)  # FlickrUploadResult

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        exiftool_path: str,
        token_cache_dir: str,
        max_workers: int,
        album_plan: FlickrAlbumPlan | None = None,
        on_album_id_resolved: Callable[[str], None] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._api_key = api_key
        self._api_secret = api_secret
        self._exiftool_path = exiftool_path
        self._token_cache_dir = token_cache_dir
        self._max_workers = max(1, int(max_workers))
        self._album_plan = album_plan if album_plan is not None else FlickrAlbumPlan()
        self._on_album_id_resolved = on_album_id_resolved

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

                # start time
                upload_ts = int(datetime.now().timestamp())

                photo_pairs = self._run_upload_stage(upload_ts, items, result)
                if result.cancelled or result.fatal_error or not photo_pairs:
                    return

                self._run_reset_date_stage(upload_ts, photo_pairs, result)
                if result.cancelled:
                    return

                self._run_make_public_stage(photo_pairs, result)
                if result.cancelled:
                    return

                self._run_add_to_album_stage(photo_pairs, result)
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
        upload_ts: int,
        items: list[dict],
        result: FlickrUploadResult,
    ) -> list[dict]:
        self.stage_changed.emit(FlickrStage.STAGE_UPLOAD.label)
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
            stage=FlickrStage.STAGE_UPLOAD.label,
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
                    stage=FlickrStage.STAGE_UPLOAD.label,
                    message=str(row.get("error", "Upload failed")),
                )
            )

        if not upload_successes:
            result.fatal_error = "No photos were successfully uploaded."
            return []

        resolve_payload = self._build_worker_payload(
            {
                "upload_ts": upload_ts,
                "upload_entries": upload_successes,
                "exiftool_path": self._exiftool_path,
            }
        )

        self.stage_changed.emit(FlickrStage.STAGE_CHECK_UPLOAD_STATUS.label)
        self.progress.emit(0, 0)
        self.status.emit(f"Check 0/{MAX_NUM_CHECKS}")

        def _on_check_progress(check_num: int, check_total: int) -> None:
            self.progress.emit(0, 0)
            self.status.emit(f"Check {int(check_num)}/{int(check_total)}")

        resolve = run_resolve_tickets_task(
            resolve_payload,
            check_progress_callback=_on_check_progress,
        )
        self.status.emit("")
        for failure in resolve.get("failures", []):
            result.failures.append(
                FlickrUploadPhotoFailure(
                    file_path=str(failure.get("file_path", "")),
                    stage=str(failure.get("stage", FlickrStage.STAGE_UPLOAD.label)),
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
        upload_ts: int,
        photo_pairs: list[dict],
        result: FlickrUploadResult,
    ) -> None:
        self.stage_changed.emit(FlickrStage.STAGE_RESET_DATE.label)
        total = len(photo_pairs)
        self.progress.emit(0, total)

        timestamps = generate_timestamps(upload_ts, total)
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
            stage=FlickrStage.STAGE_RESET_DATE.label,
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
                    stage=FlickrStage.STAGE_RESET_DATE.label,
                    message=str(row.get("error", "Failed to reset upload date")),
                )
            )

        result.reset_date_count = success_count

    def _run_make_public_stage(
        self,
        photo_pairs: list[dict],
        result: FlickrUploadResult,
    ) -> None:
        self.stage_changed.emit(FlickrStage.STAGE_MAKE_PUBLIC.label)
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
            stage=FlickrStage.STAGE_MAKE_PUBLIC.label,
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
                    stage=FlickrStage.STAGE_MAKE_PUBLIC.label,
                    message=str(row.get("error", "Failed to make photo public")),
                )
            )

        result.made_public_count = success_count

    def _run_add_to_album_stage(
        self,
        photo_pairs: list[dict],
        result: FlickrUploadResult,
    ) -> None:
        plan = self._album_plan
        if not plan.has_input():
            return

        self.stage_changed.emit(FlickrStage.STAGE_ADD_TO_ALBUM.label)
        self.progress.emit(0, 0)

        album_id = plan.album_id
        album_title = plan.album_title.strip() or album_id
        album_user_nsid = plan.user_nsid
        album_url = plan.album_url
        if plan.is_create:
            album_title = plan.album_title.strip() or plan.normalized_raw_text()
            self.album_status.emit(f"Creating album '{album_title}'...")

            if not photo_pairs:
                result.failures.append(
                    FlickrUploadPhotoFailure(
                        file_path="",
                        stage=FlickrStage.STAGE_ADD_TO_ALBUM.label,
                        message="No uploaded photo available to create album.",
                    )
                )
                return

            create_row = run_create_album_task(
                self._build_worker_payload(
                    {
                        "album_title": album_title,
                        "primary_photo_id": str(photo_pairs[0]["photo_id"]),
                    }
                )
            )
            if not create_row.get("ok"):
                result.failures.append(
                    FlickrUploadPhotoFailure(
                        file_path="",
                        stage=FlickrStage.STAGE_ADD_TO_ALBUM.label,
                        message=str(create_row.get("error", "Failed to create album")),
                    )
                )
                return

            album_id = str(create_row.get("album_id") or "").strip()
            if not album_id:
                result.failures.append(
                    FlickrUploadPhotoFailure(
                        file_path="",
                        stage=FlickrStage.STAGE_ADD_TO_ALBUM.label,
                        message=(
                            "Album creation succeeded but no album id was returned."
                        ),
                    )
                )
                return

            album_title = str(create_row.get("album_title") or album_title).strip()
            album_user_nsid = str(create_row.get("user_nsid") or "").strip()
            album_url = str(create_row.get("album_url") or "").strip()
            result.album_created = True
            result.album_id = album_id
            result.album_title = album_title or album_id
            result.album_user_nsid = album_user_nsid
            result.album_url = album_url

            if self._on_album_id_resolved is not None:
                try:
                    self._on_album_id_resolved(album_id)
                except Exception as ex:  # pragma: no cover - defensive callback guard
                    result.failures.append(
                        FlickrUploadPhotoFailure(
                            file_path="",
                            stage=FlickrStage.STAGE_ADD_TO_ALBUM.label,
                            message=(
                                "Album created but failed to persist album id to "
                                f"folder metadata: {ex}"
                            ),
                        )
                    )

        album_id = str(album_id or "").strip()
        if not album_id:
            return

        display_title = album_title or album_id
        result.album_id = album_id
        result.album_title = display_title
        result.album_user_nsid = album_user_nsid
        result.album_url = album_url
        self.album_status.emit(f"Adding to album '{display_title}'...")

        add_row = run_add_to_album_task(
            self._build_worker_payload(
                {
                    "album_id": album_id,
                    "photo_ids": [str(row["photo_id"]) for row in photo_pairs],
                }
            )
        )

        if not add_row.get("ok"):
            result.failures.append(
                FlickrUploadPhotoFailure(
                    file_path="",
                    stage=FlickrStage.STAGE_ADD_TO_ALBUM.label,
                    message=str(add_row.get("error", "Failed to add photos to album")),
                )
            )
            return

        result.album_added_count = int(add_row.get("added_count") or len(photo_pairs))
        self.status.emit(FlickrStage.STAGE_ADD_TO_ALBUM.label)

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
