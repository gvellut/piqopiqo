import logging
import os
import sys

import click
import exiftool
from PySide6.QtWidgets import QApplication

from .config import Config, apply_env_overrides
from .photo_grid import MainWindow
from .thumb_man import scan_folder
from .utils import setup_logging


@click.command()
@click.argument("folder", type=click.Path(exists=True))
def cli(folder):
    logger = logging.getLogger(__package__)
    setup_logging(logger)

    # Apply environment variable overrides to config
    apply_env_overrides()

    # 1. Ensure Cache Dir Exists
    if not os.path.exists(Config.CACHE_DIR):
        os.makedirs(Config.CACHE_DIR)
    else:
        if Config.CLEAR_CACHE_ON_START:
            # Clear existing cache
            for f in os.listdir(Config.CACHE_DIR):
                fp = os.path.join(Config.CACHE_DIR, f)
                if os.path.isfile(fp):
                    os.remove(fp)

    # TODO keep a watcher for the folder ; instead of scanning only at the beginning
    # TODO or at least : support duplicating images
    print(f"Scanning {folder}...")
    images = scan_folder(folder)
    print(f"Found {len(images)} images.")

    # 2. Start ExifTool

    # 3. Launch GUI
    app = QApplication(sys.argv)

    app.setApplicationName(Config.APP_NAME)
    app.setApplicationDisplayName(Config.APP_NAME)

    # by default : the commong args are -G -n => numeric values like shutter speed
    # are  0.0025 isntead of 1/400
    with exiftool.ExifToolHelper(
        executable=Config.EXIF_TOOL_PATH, common_args=["-G"]
    ) as etHelper:
        window = MainWindow(images, etHelper)
        window.show()

    exit_code = app.exec()
    sys.exit(exit_code)


if __name__ == "__main__":
    cli()
