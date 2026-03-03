"""External application integration (file manager, viewer, editor)."""

import logging
import subprocess
import sys

from .model import ImageItem

logger = logging.getLogger(__name__)


def get_reveal_in_file_manager_label() -> str:
    """Return a platform-specific label for reveal actions."""
    if sys.platform == "darwin":
        return "Reveal in Finder"
    if sys.platform == "win32":
        return "Reveal in Explorer"
    return "Reveal in File Manager"


def reveal_paths_in_file_manager(paths: list[str]) -> None:
    """Reveal filesystem paths in the system file manager."""
    if not paths:
        return

    try:
        import showinfm

        showinfm.show_in_file_manager(paths)
    except Exception as e:
        logger.error("Failed to reveal paths in file manager: %s", e)


def reveal_path_in_file_manager(path: str) -> None:
    """Reveal a single path in the system file manager."""
    if not path:
        return
    reveal_paths_in_file_manager([path])


def reveal_in_file_manager(photos: list[ImageItem]) -> None:
    """Reveal photos in the system file manager.

    Groups files by folder and opens each folder with its files selected.

    Args:
        photos: List of ImageItem objects to reveal.
    """
    paths = [photo.path for photo in photos]
    reveal_paths_in_file_manager(paths)


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
