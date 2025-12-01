import logging
import os
import sys

import click
from PySide6.QtWidgets import QApplication

from .config import Config
from .gui.gemini_photos import MainWindow
from .scanner import scan_folder
from .utils import setup_logging


@click.command()
@click.argument("folder", type=click.Path(exists=True))
def cli(folder):
    logger = logging.getLogger(__package__)
    setup_logging(logger)

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

    # 3. Launch GUI
    app = QApplication(sys.argv)

    app.setApplicationName(Config.APP_NAME)
    app.setApplicationDisplayName(Config.APP_NAME)

    window = MainWindow(images)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    cli()
