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
import sys

logger = logging.getLogger(__name__)

_APP_NAME = "PiqoPiqo"
_CACHE_BASE_DIR: Path | None = None


def _default_support_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
        support_dir = base / _APP_NAME
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        support_dir = base / _APP_NAME
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg_config) if xdg_config else Path.home() / ".config"
        support_dir = base / _APP_NAME.lower()

    support_dir.mkdir(parents=True, exist_ok=True)
    return support_dir


def _default_cache_base_dir() -> Path:
    cache_dir = _default_support_dir() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def set_cache_base_dir(base_dir: str | os.PathLike[str] | None) -> Path:
    """Set the process cache base directory used by cache helpers."""
    global _CACHE_BASE_DIR

    if base_dir is None:
        _CACHE_BASE_DIR = _default_cache_base_dir()
    else:
        _CACHE_BASE_DIR = Path(base_dir)
        _CACHE_BASE_DIR.mkdir(parents=True, exist_ok=True)

    return _CACHE_BASE_DIR


def get_cache_base_dir() -> Path:
    """Return the configured cache base directory."""
    if _CACHE_BASE_DIR is None:
        return set_cache_base_dir(None)
    return _CACHE_BASE_DIR


def get_folder_cache_id(folder_path: str) -> str:
    """Compute a unique cache ID for a folder based on its absolute path."""
    abs_path = os.path.abspath(folder_path)
    return hashlib.md5(abs_path.encode("utf-8")).hexdigest()


def get_cache_dir_for_folder(folder_path: str) -> Path:
    """Get the cache directory for a specific folder."""
    cache_id = get_folder_cache_id(folder_path)
    return get_cache_base_dir() / cache_id


def get_thumb_dir_for_folder(folder_path: str) -> Path:
    """Get the thumbnail cache directory for a specific folder."""
    return get_cache_dir_for_folder(folder_path) / "thumb"


def get_thumb_embedded_dir_for_folder(folder_path: str) -> Path:
    """Get the embedded-preview thumbnail cache directory for a folder."""
    return get_thumb_dir_for_folder(folder_path) / "embedded"


def get_thumb_hq_dir_for_folder(folder_path: str) -> Path:
    """Get the HQ thumbnail cache directory for a folder."""
    return get_thumb_dir_for_folder(folder_path) / "hq"


def ensure_thumb_dir(folder_path: str) -> Path:
    """Ensure the thumbnail directories exist for a folder."""
    thumb_dir = get_thumb_dir_for_folder(folder_path)
    # Split caches by quality level to avoid filename suffixes and allow
    # different retention policies in memory.
    (thumb_dir / "embedded").mkdir(parents=True, exist_ok=True)
    (thumb_dir / "hq").mkdir(parents=True, exist_ok=True)
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
