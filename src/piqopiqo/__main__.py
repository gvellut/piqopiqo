import logging
import sys

import click
import exiftool
from PySide6.QtWidgets import QApplication

from .config import Config, apply_env_overrides
from .photo_grid import MainWindow
from .support import get_cache_base_dir, get_last_folder, save_last_folder
from .thumb_man import scan_folder
from .utils import setup_logging


@click.command()
@click.argument("folder", type=click.Path(exists=True), required=False)
def cli(folder):
    logger = logging.getLogger(__package__)
    setup_logging(logger)

    # Apply environment variable overrides to config
    apply_env_overrides()

    # Set cache base directory from support directory (can be overridden by env var)
    if Config.CACHE_BASE_DIR is None:
        Config.CACHE_BASE_DIR = str(get_cache_base_dir())

    # Determine which folder to open
    if folder is None:
        # Try to load last opened folder
        folder = get_last_folder()
        if folder:
            logger.info(f"Opening last folder: {folder}")

    # Scan folder if provided
    images = []
    source_folders = []
    if folder:
        print(f"Scanning {folder}...")
        images, source_folders = scan_folder(folder)
        print(f"Found {len(images)} images in {len(source_folders)} folder(s).")
        # Save as last folder
        save_last_folder(folder)

    # Launch GUI
    app = QApplication(sys.argv)

    app.setApplicationName(Config.APP_NAME)
    app.setApplicationDisplayName(Config.APP_NAME)

    # by default: the common args are -G -n => numeric values like shutter speed
    # are 0.0025 instead of 1/400
    with exiftool.ExifToolHelper(
        executable=Config.EXIFTOOL_PATH, common_args=["-G"]
    ) as etHelper:
        window = MainWindow(images, source_folders, folder, etHelper)
        window.show()

        exit_code = app.exec()
    sys.exit(exit_code)


if __name__ == "__main__":
    cli()
