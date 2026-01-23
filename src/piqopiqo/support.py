"""Platform-specific support directory utilities."""

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import sys

logger = logging.getLogger(__name__)

APP_NAME = "PiqoPiqo"


def get_support_dir() -> Path:
    """Get the platform-specific application support directory.

    Returns:
        Path to the support directory:
        - macOS: ~/Library/Application Support/PiqoPiqo/
        - Windows: %APPDATA%/PiqoPiqo/
        - Linux: ~/.config/piqopiqo/
    """
    if sys.platform == "darwin":
        # macOS
        base = Path.home() / "Library" / "Application Support"
        support_dir = base / APP_NAME
    elif sys.platform == "win32":
        # Windows
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = Path(appdata)
        else:
            base = Path.home() / "AppData" / "Roaming"
        support_dir = base / APP_NAME
    else:
        # Linux and others
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            base = Path(xdg_config)
        else:
            base = Path.home() / ".config"
        support_dir = base / APP_NAME.lower()

    # Create directory if it doesn't exist
    support_dir.mkdir(parents=True, exist_ok=True)
    return support_dir


def get_cache_base_dir() -> Path:
    """Get the base directory for all cache data.

    Returns:
        Path to the cache base directory inside the support directory.
    """
    cache_dir = get_support_dir() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def save_last_folder(folder_path: str) -> None:
    """Save the last opened folder path to persistent storage.

    Args:
        folder_path: The absolute path to the folder.
    """
    support_dir = get_support_dir()
    last_folder_file = support_dir / "last_folder.json"

    data = {
        "path": folder_path,
        "timestamp": datetime.now().isoformat(),
    }

    try:
        with open(last_folder_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Saved last folder: {folder_path}")
    except OSError as e:
        logger.error(f"Failed to save last folder: {e}")


def get_last_folder() -> str | None:
    """Get the last opened folder path from persistent storage.

    Returns:
        The folder path if it exists and is valid, None otherwise.
    """
    support_dir = get_support_dir()
    last_folder_file = support_dir / "last_folder.json"

    if not last_folder_file.exists():
        return None

    try:
        with open(last_folder_file, encoding="utf-8") as f:
            data = json.load(f)

        folder_path = data.get("path")
        if folder_path and os.path.isdir(folder_path):
            logger.debug(f"Loaded last folder: {folder_path}")
            return folder_path
        else:
            logger.debug(f"Last folder no longer exists: {folder_path}")
            return None
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load last folder: {e}")
        return None


def clear_last_folder() -> None:
    """Remove the last folder file."""
    support_dir = get_support_dir()
    last_folder_file = support_dir / "last_folder.json"

    if last_folder_file.exists():
        try:
            last_folder_file.unlink()
            logger.debug("Cleared last folder")
        except OSError as e:
            logger.error(f"Failed to clear last folder: {e}")
