import logging
import os
from pathlib import Path
import shutil
import signal
import sys
import threading

import click
import exiftool
from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

# try:
#     from pyqtauto.server import start_server
# except ImportError:
start_server = None

from .config import Config, apply_env_overrides
from .main_window import MainWindow
from .support import get_cache_base_dir, get_last_folder, save_last_folder
from .thumb_man import scan_folder
from .utils import setup_logging


# Helper to find the icon whether running as script or frozen app
def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


@click.command()
@click.argument("folder", type=click.Path(exists=True), required=False)
def cli(folder):
    logger = logging.getLogger(__package__)
    setup_logging(logger)

    # Apply environment variable overrides to config
    apply_env_overrides()

    # Handle cache base directory
    if Config.CACHE_BASE_DIR is not None:
        # User specified a custom path - ensure it exists
        cache_path = Path(Config.CACHE_BASE_DIR)
        cache_path.mkdir(parents=True, exist_ok=True)
    else:
        # Not set, use support directory as fallback
        Config.CACHE_BASE_DIR = str(get_cache_base_dir())

    if Config.CLEAR_CACHE_ON_START:
        cache_dir = Path(Config.CACHE_BASE_DIR)
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)

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

    # Start pyqtauto server for automation testing
    if start_server is not None:
        server = start_server(force=True)
        if server:
            logger.info(f"PyQtAuto server on port {server.port}")

    app.setApplicationName(Config.APP_NAME)
    app.setApplicationDisplayName(Config.APP_NAME)

    icon_path = resource_path("app.icns")
    app.setWindowIcon(QIcon(icon_path))

    # by default: the common args are -G -n => numeric values like shutter speed
    # are 0.0025 instead of 1/400
    with exiftool.ExifToolHelper(
        executable=Config.EXIFTOOL_PATH, common_args=["-G"]
    ) as etHelper:
        window = MainWindow(images, source_folders, folder, etHelper)
        if Config.INITIAL_RESOLUTION:
            try:
                w, h = Config.INITIAL_RESOLUTION.split("x")
                window.resize(int(w), int(h))
                window.show()
            except (ValueError, AttributeError):
                logger.warning(
                    f"Invalid INITIAL_RESOLUTION: {Config.INITIAL_RESOLUTION}, "
                    "opening maximized"
                )
                window.showMaximized()
        else:
            window.showMaximized()

        # Make Ctrl-C in the launching terminal behave like a graceful quit.
        _sigint_kill_timer: threading.Timer | None = None
        _sigint_requested = False

        def _handle_sigint(_signum, _frame):
            nonlocal _sigint_kill_timer, _sigint_requested

            if _sigint_requested:
                return
            _sigint_requested = True

            if _sigint_kill_timer is None:
                _sigint_kill_timer = threading.Timer(
                    float(Config.SHUTDOWN_TIMEOUT_S),
                    lambda: os.kill(os.getpid(), signal.SIGKILL),
                )
                _sigint_kill_timer.daemon = True
                _sigint_kill_timer.start()

            # Schedule Qt-side shutdown on the event loop (safer than calling
            # QWidget/QApplication methods directly from a signal handler).
            def _request_quit():
                try:
                    window.close()
                finally:
                    inst = QApplication.instance()
                    if inst is not None:
                        inst.quit()

            QTimer.singleShot(0, _request_quit)

        signal.signal(signal.SIGINT, _handle_sigint)

        # Keep the Python interpreter cycling so SIGINT is handled promptly
        # while the Qt event loop is running.
        _sigint_timer = QTimer()
        _sigint_timer.start(250)
        _sigint_timer.timeout.connect(lambda: None)

        exit_code = app.exec()
    sys.exit(exit_code)


if __name__ == "__main__":
    cli()
