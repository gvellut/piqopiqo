"""Platform-specific support directory utilities."""

import logging
import os
from pathlib import Path
import sys

from .state import APP_NAME

logger = logging.getLogger(__name__)


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
