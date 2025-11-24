import os
import sys

import click
from PySide6.QtWidgets import QApplication

from piqopiqo.config import Config
from piqopiqo.gui.window import MainWindow
from piqopiqo.scanner import scan_folder


@click.command()
@click.argument("folder", type=click.Path(exists=True))
def cli(folder):
    """PiqoPiqo Image Viewer"""
    # 1. Ensure Cache Dir Exists
    if not os.path.exists(Config.CACHE_DIR):
        os.makedirs(Config.CACHE_DIR)

    # 2. Scan Data
    print(f"Scanning {folder}...")
    images = scan_folder(folder)
    print(f"Found {len(images)} images.")

    # 3. Launch GUI
    app = QApplication(sys.argv)
    window = MainWindow(images)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    cli()
