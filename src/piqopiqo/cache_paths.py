"""Cache directory utilities.

Keep this module free of Qt imports so it can be reused in multiprocessing
workers and in database code without pulling GUI dependencies.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import shutil

from .config import Config

logger = logging.getLogger(__name__)


def get_folder_cache_id(folder_path: str) -> str:
    """Compute a unique cache ID for a folder based on its absolute path."""
    abs_path = os.path.abspath(folder_path)
    return hashlib.md5(abs_path.encode("utf-8")).hexdigest()


def get_cache_dir_for_folder(folder_path: str) -> Path:
    """Get the cache directory for a specific folder."""
    cache_id = get_folder_cache_id(folder_path)
    return Path(Config.CACHE_BASE_DIR) / cache_id


def get_thumb_dir_for_folder(folder_path: str) -> Path:
    """Get the thumbnail cache directory for a specific folder."""
    return get_cache_dir_for_folder(folder_path) / "thumb"


def ensure_thumb_dir(folder_path: str) -> Path:
    """Ensure the thumbnail directory exists for a folder."""
    thumb_dir = get_thumb_dir_for_folder(folder_path)
    thumb_dir.mkdir(parents=True, exist_ok=True)
    return thumb_dir


def clear_thumb_cache_for_folder(folder_path: str) -> None:
    """Clear the thumbnail cache for a specific folder."""
    thumb_dir = get_thumb_dir_for_folder(folder_path)
    if thumb_dir.exists():
        shutil.rmtree(thumb_dir)
        logger.info(f"Cleared thumbnail cache for: {folder_path}")


def clear_thumb_cache_for_folders(folder_paths: list[str]) -> None:
    """Clear the thumbnail cache for multiple folders."""
    for folder_path in folder_paths:
        clear_thumb_cache_for_folder(folder_path)
