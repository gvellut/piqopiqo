"""Thumbnail utilities.

`ThumbnailManager` is deprecated and superseded by
`piqopiqo.background.media_man.MediaManager`.

The `scan_folder()` helper is still used to build the initial photo list.
"""

from datetime import datetime
import hashlib
import logging
import multiprocessing
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from PIL import Image
from PySide6.QtCore import QObject, Signal

from ..config import Config

logger = logging.getLogger(__name__)


def _pool_worker_init() -> None:
    """Initializer for Pool workers.

    Ignore SIGINT in workers so Ctrl-C only affects the main process.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def get_folder_cache_id(folder_path: str) -> str:
    """Compute a unique cache ID for a folder based on its absolute path.

    Args:
        folder_path: Path to the folder.

    Returns:
        A 32-character hex string hash of the folder path.
    """
    abs_path = os.path.abspath(folder_path)
    return hashlib.md5(abs_path.encode("utf-8")).hexdigest()


def get_cache_dir_for_folder(folder_path: str) -> Path:
    """Get the cache directory for a specific folder.

    Args:
        folder_path: Path to the source folder.

    Returns:
        Path to the cache directory for this folder.
    """
    cache_id = get_folder_cache_id(folder_path)
    return Path(Config.CACHE_BASE_DIR) / cache_id


def get_thumb_dir_for_folder(folder_path: str) -> Path:
    """Get the thumbnail cache directory for a specific folder.

    Args:
        folder_path: Path to the source folder.

    Returns:
        Path to the thumb subdirectory in the cache.
    """
    return get_cache_dir_for_folder(folder_path) / "thumb"


def ensure_thumb_dir(folder_path: str) -> Path:
    """Ensure the thumbnail directory exists for a folder.

    Args:
        folder_path: Path to the source folder.

    Returns:
        Path to the thumb directory (created if needed).
    """
    thumb_dir = get_thumb_dir_for_folder(folder_path)
    thumb_dir.mkdir(parents=True, exist_ok=True)
    return thumb_dir


def clear_thumb_cache_for_folder(folder_path: str) -> None:
    """Clear the thumbnail cache for a specific folder.

    Args:
        folder_path: Path to the source folder.
    """
    thumb_dir = get_thumb_dir_for_folder(folder_path)
    if thumb_dir.exists():
        shutil.rmtree(thumb_dir)
        logger.info(f"Cleared thumbnail cache for: {folder_path}")


def clear_thumb_cache_for_folders(folder_paths: list[str]) -> None:
    """Clear the thumbnail cache for multiple folders.

    Args:
        folder_paths: List of folder paths to clear cache for.
    """
    for folder_path in folder_paths:
        clear_thumb_cache_for_folder(folder_path)


# Worker functions run in separate processes, so they receive all needed params
def worker_task(file_path: str, thumb_dir: str, exiftool_path: str, max_dim: int):
    """Generate thumbnail for an image (embedded first, then HQ fallback).

    Args:
        file_path: Path to the source image.
        thumb_dir: Path to the thumbnail cache directory.
        exiftool_path: Path to exiftool executable.
        max_dim: Maximum dimension for HQ thumbnails.

    Returns:
        Tuple of (thumb_type, file_path, cache_path) or (None, None, None).
    """
    filename = os.path.basename(file_path)
    base_name = os.path.splitext(filename)[0]
    cache_path_embedded = os.path.join(thumb_dir, f"{base_name}_embedded.jpg")
    cache_path_hq = os.path.join(thumb_dir, f"{base_name}_hq.jpg")

    # Try embedded first
    if generate_embedded(file_path, cache_path_embedded, exiftool_path):
        return ("embedded", file_path, cache_path_embedded)

    # Fallback to HQ
    if generate_hq(file_path, cache_path_hq, max_dim):
        return ("hq", file_path, cache_path_hq)

    return (None, None, None)


def hq_worker_task(file_path: str, thumb_dir: str, max_dim: int):
    """Generate high-quality thumbnail for an image.

    Args:
        file_path: Path to the source image.
        thumb_dir: Path to the thumbnail cache directory.
        max_dim: Maximum dimension for thumbnails.

    Returns:
        Tuple of (thumb_type, file_path, cache_path) or (None, None, None).
    """
    filename = os.path.basename(file_path)
    base_name = os.path.splitext(filename)[0]
    cache_path_hq = os.path.join(thumb_dir, f"{base_name}_hq.jpg")

    if generate_hq(file_path, cache_path_hq, max_dim):
        return ("hq", file_path, cache_path_hq)
    return (None, None, None)


class ThumbnailManager(QObject):
    """Manages thumbnail generation for images across multiple source folders."""

    thumb_ready = Signal(str, str, str)
    progress_updated = Signal(int, int)  # completed, total
    all_completed = Signal()  # emitted when all tasks are done

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = multiprocessing.Pool(
            Config.MAX_WORKERS,
            initializer=_pool_worker_init,
        )
        self.pending = set()
        # Map from source folder path to its thumb directory
        self._folder_thumb_dirs: dict[str, Path] = {}
        # Progress tracking
        self._total_queued = 0
        self._completed = 0
        self._errors: dict[str, str] = {}

    def register_folder(self, folder_path: str) -> Path:
        """Register a source folder and create its cache directory.

        Args:
            folder_path: Path to the source folder.

        Returns:
            Path to the thumb directory for this folder.
        """
        if folder_path not in self._folder_thumb_dirs:
            thumb_dir = ensure_thumb_dir(folder_path)
            self._folder_thumb_dirs[folder_path] = thumb_dir
            logger.debug(f"Registered folder cache: {folder_path} -> {thumb_dir}")
        return self._folder_thumb_dirs[folder_path]

    def get_thumb_dir_for_image(self, file_path: str) -> Path:
        """Get the thumb directory for an image based on its parent folder.

        Args:
            file_path: Path to the image file.

        Returns:
            Path to the thumb directory for this image's folder.
        """
        folder_path = os.path.dirname(file_path)
        return self.register_folder(folder_path)

    def queue_image(self, file_path: str):
        """Queue an image for thumbnail generation.

        Args:
            file_path: Path to the image file.
        """
        if file_path in self.pending:
            return

        self.pending.add(file_path)
        self._total_queued += 1

        # Get the thumb directory for this image's source folder
        thumb_dir = self.get_thumb_dir_for_image(file_path)

        filename = os.path.basename(file_path)
        base_name = os.path.splitext(filename)[0]
        cache_path_hq = thumb_dir / f"{base_name}_hq.jpg"

        # If HQ already exists, use it
        if cache_path_hq.exists():
            self.thumb_ready.emit(file_path, "hq", str(cache_path_hq))
            self.pending.remove(file_path)
            self._completed += 1
            self.progress_updated.emit(self._completed, self._total_queued)
            self._check_all_completed()
            return

        # Queue the worker task
        self.pool.apply_async(
            worker_task,
            (file_path, str(thumb_dir), Config.EXIFTOOL_PATH, Config.THUMB_MAX_DIM),
            callback=self.on_task_done,
            error_callback=lambda e, fp=file_path: self._on_task_error(fp, e),
        )
        self.progress_updated.emit(self._completed, self._total_queued)

    def on_task_done(self, result):
        """Handle completion of a thumbnail generation task."""
        thumb_type, file_path, cache_path = result
        if file_path and file_path in self.pending:
            self.pending.remove(file_path)

        self._completed += 1
        self.progress_updated.emit(self._completed, self._total_queued)

        if thumb_type is None and file_path:
            self._errors[file_path] = "Failed to generate thumbnail"

        if thumb_type:
            self.thumb_ready.emit(file_path, thumb_type, cache_path)

            # If we got an embedded preview, also queue HQ generation
            if thumb_type == "embedded":
                self.queue_hq(file_path)

        self._check_all_completed()

    def _on_task_error(self, file_path: str, error: Exception):
        """Handle worker task error."""
        if file_path in self.pending:
            self.pending.remove(file_path)

        self._completed += 1
        self._errors[file_path] = str(error)
        self.progress_updated.emit(self._completed, self._total_queued)
        logger.error(f"Thumbnail generation error for {file_path}: {error}")
        self._check_all_completed()

    def _check_all_completed(self):
        """Check if all tasks are completed and emit signal."""
        if self._completed >= self._total_queued and self._total_queued > 0:
            self.all_completed.emit()

    def queue_hq(self, file_path: str):
        """Queue high-quality thumbnail generation for an image.

        Args:
            file_path: Path to the image file.
        """
        if file_path in self.pending:
            return

        self.pending.add(file_path)
        thumb_dir = self.get_thumb_dir_for_image(file_path)

        self.pool.apply_async(
            hq_worker_task,
            (file_path, str(thumb_dir), Config.THUMB_MAX_DIM),
            callback=self.on_hq_task_done,
        )

    def on_hq_task_done(self, result):
        """Handle completion of an HQ thumbnail generation task."""
        thumb_type, file_path, cache_path = result
        if file_path and file_path in self.pending:
            self.pending.remove(file_path)
        if thumb_type:
            self.thumb_ready.emit(file_path, thumb_type, cache_path)

    def clear_and_requeue_image(self, file_path: str):
        """Clear cached thumbnails for a single image and re-queue generation."""
        thumb_dir = self.get_thumb_dir_for_image(file_path)
        basename = os.path.splitext(os.path.basename(file_path))[0]

        for suffix in ["_embedded.jpg", "_hq.jpg"]:
            cache_file = thumb_dir / f"{basename}{suffix}"
            if cache_file.exists():
                try:
                    cache_file.unlink()
                    logger.debug(f"Deleted cache file: {cache_file}")
                except OSError as e:
                    logger.warning(f"Failed to delete cache file {cache_file}: {e}")

        # Allow re-queuing by removing from pending set
        self.pending.discard(file_path)
        self.queue_image(file_path)

    def get_registered_folders(self) -> list[str]:
        """Get list of all registered source folders.

        Returns:
            List of folder paths that have been registered.
        """
        return list(self._folder_thumb_dirs.keys())

    def clear_all_registered_caches(self):
        """Clear thumbnail caches for all registered folders."""
        clear_thumb_cache_for_folders(list(self._folder_thumb_dirs.keys()))
        # Re-create the directories
        for folder_path in list(self._folder_thumb_dirs.keys()):
            self._folder_thumb_dirs[folder_path] = ensure_thumb_dir(folder_path)

    def get_errors(self) -> dict[str, str]:
        """Get dictionary of file paths with errors."""
        return self._errors.copy()

    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self._errors) > 0

    def reset_progress(self):
        """Reset counters for new folder load."""
        self._total_queued = 0
        self._completed = 0
        self._errors.clear()

    def get_progress(self) -> tuple[int, int]:
        """Get current progress.

        Returns:
            Tuple of (completed, total).
        """
        return self._completed, self._total_queued

    def stop(self, timeout_s: float | None = None):
        """Stop the thumbnail manager and close the worker pool.

        If timeout_s is provided and the pool does not stop within that time,
        the pool will be terminated.
        """
        if getattr(self, "pool", None) is None:
            return

        pool = self.pool
        self.pool = None

        if timeout_s is None:
            pool.close()
            pool.join()
            return

        deadline = time.monotonic() + max(0.0, float(timeout_s))
        pool.close()

        processes = getattr(pool, "_pool", None) or []
        for proc in processes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            proc.join(remaining)

        if any(proc.is_alive() for proc in processes):
            logger.warning("Thumbnail pool shutdown timed out; terminating workers")
            try:
                pool.terminate()
            except Exception:
                pass
            for proc in processes:
                proc.join(1.0)


def scan_folder(root_path: str) -> tuple[list[dict], list[str]]:
    """Recursively scans a folder for images.

    Args:
        root_path: Path to the root folder to scan.

    Returns:
        Tuple of (images list, unique folders list).
        Each image dict contains: path, name, state, created, source_folder.
        Unique folders list contains paths of all folders with images.
    """
    images = []
    unique_folders = set()

    for root, _, files in os.walk(root_path):
        folder_has_images = False
        for file in files:
            if file.lower().endswith((".jpg", ".jpeg", ".png")):
                path = os.path.join(root, file)
                images.append(
                    {
                        "path": path,
                        "name": file,
                        "state": 0,  # not processed
                        "created": datetime.fromtimestamp(
                            os.path.getctime(path)
                        ).strftime("%Y-%m-%d %H:%M:%S"),
                        "source_folder": root,
                    }
                )
                folder_has_images = True
        if folder_has_images:
            unique_folders.add(root)

    sorted_images = sorted(images, key=lambda x: x["name"])
    sorted_folders = sorted(unique_folders)

    return sorted_images, sorted_folders


def generate_embedded(source: str, dest_path: str, exiftool_path: str | None) -> bool:
    """Extract embedded thumbnail from an image using exiftool.

    Args:
        source: Path to the source image.
        dest_path: Path to save the extracted thumbnail.
        exiftool_path: Path to exiftool executable (None uses default).

    Returns:
        True if extraction succeeded and produced a non-empty file.
    """
    try:
        exe = exiftool_path if exiftool_path else "exiftool"
        cmd = [exe, "-b", "-PreviewImage", source]
        with open(dest_path, "wb") as f:
            subprocess.run(cmd, stdout=f, stderr=subprocess.DEVNULL)
        return os.path.getsize(dest_path) > 0
    except Exception:
        return False


def generate_hq(source: str, dest_path: str, max_dim: int) -> bool:
    """Generate a high-quality thumbnail from an image.

    Args:
        source: Path to the source image.
        dest_path: Path to save the thumbnail.
        max_dim: Maximum width/height for the thumbnail.

    Returns:
        True if generation succeeded.
    """
    try:
        img = Image.open(source)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail((max_dim, max_dim))
        img.save(dest_path, "JPEG", quality=80)
        return True
    except Exception:
        return False
