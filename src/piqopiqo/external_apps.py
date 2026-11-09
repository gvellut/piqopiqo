"""External application integration (file manager, viewer, editor)."""

from collections import defaultdict
import logging
from pathlib import Path
import subprocess

from .model import ImageItem

logger = logging.getLogger(__name__)


def get_reveal_in_file_manager_label_macos() -> str:
    """Return the Finder label used for macOS reveal actions."""
    return "Reveal in Finder"


def reveal_path_in_file_manager_macos(path: str) -> None:
    """Open a folder in Finder or reveal a single file."""
    if not path:
        return

    try:
        import showinfm

        showinfm.show_in_file_manager(path)
    except Exception as e:
        logger.error("Failed to reveal path in Finder: %s", e)


def reveal_in_file_manager_macos(photos: list[ImageItem]) -> None:
    """Open each photo's folder in Finder with its photos selected together."""
    if not photos:
        return

    try:
        from Cocoa import NSURL, NSWorkspace

        urls_by_folder = defaultdict(list)
        for photo in photos:
            path = Path(photo.path).resolve()
            urls_by_folder[path.parent].append(NSURL.fileURLWithPath_(str(path)))

        workspace = NSWorkspace.sharedWorkspace()
        for urls in urls_by_folder.values():
            workspace.activateFileViewerSelectingURLs_(urls)
    except Exception as e:
        logger.error("Failed to reveal photos in Finder: %s", e)


def open_in_external_app_macos(app_name: str, paths: list[str]) -> None:
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
