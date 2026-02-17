"""External application integration (file manager, viewer, editor)."""

import logging
import subprocess

from .model import ImageItem

logger = logging.getLogger(__name__)


def reveal_in_file_manager(photos: list[ImageItem]) -> None:
    """Reveal photos in the system file manager.

    Groups files by folder and opens each folder with its files selected.

    Args:
        photos: List of ImageItem objects to reveal.
    """
    import showinfm

    paths = [photo.path for photo in photos]
    showinfm.show_in_file_manager(paths)


def open_in_external_app(app_name: str, paths: list[str]) -> None:
    """Open files in an external application.

    On macOS, uses ``open -a AppNameOrPath file1 file2 ...``.

    Args:
        app_name: The application name or path
            (e.g. "Preview", "/Applications/Preview.app").
        paths: List of file paths to open.
    """
    if not app_name or not paths:
        return

    try:
        cmd = ["open", "-a", app_name] + paths
        subprocess.Popen(cmd)
        logger.info(f"Opened {len(paths)} file(s) in {app_name}")
    except Exception as e:
        logger.error(f"Failed to open in {app_name}: {e}")
