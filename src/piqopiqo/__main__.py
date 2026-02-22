import logging
import os
import shutil
import signal
import sys
import threading

import click
import Foundation
from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

try:
    from pyqtauto.server import start_server
except ImportError:
    start_server = None

from .cache_paths import set_cache_base_dir
from .folder_scan import scan_folder
from .main_window import MainWindow
from .settings_state import (
    APP_NAME,
    ORG_DOMAIN,
    ORG_NAME,
    RuntimeSettingKey,
    StateKey,
    UserSettingKey,
    get_runtime_setting,
    get_state_value,
    get_user_setting,
    init_qsettings_store,
    set_state_value,
)
from .utils import setup_logging


# Helper to find the icon whether running as script or frozen app
def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def suppress_macos_menus():
    if sys.platform == "darwin":
        defaults = Foundation.NSUserDefaults.standardUserDefaults()
        # Suppress Emoji & Symbols
        defaults.setBool_forKey_(True, "NSDisabledCharacterPaletteMenuItem")
        # Suppress Dictation
        defaults.setBool_forKey_(True, "NSDisabledDictationMenuItem")
        # Suppress "Enter Full Screen" from appearing in View menus app-wide
        defaults.setBool_forKey_(False, "NSFullScreenMenuItemEverywhere")
        # Remove Autofill (macOS 14+)
        defaults.setBool_forKey_(True, "NSDisabledAutofillMenuItem")
        # Remove Passwords (often linked to Autofill)
        defaults.setBool_forKey_(True, "NSDisabledPasswordsMenuItem")


@click.command()
@click.argument("folder", type=click.Path(exists=True), required=False)
@click.option("--dyn", is_flag=True, default=False, help="Ignore saved state/settings")
def cli(folder, dyn):
    logger = logging.getLogger(__package__)
    setup_logging(logger)

    suppress_macos_menus()

    # Launch GUI
    app = QApplication(sys.argv)

    # Set application identity (must be before QSettings creation)
    app.setOrganizationName(ORG_NAME)
    app.setOrganizationDomain(ORG_DOMAIN)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)

    # Initialize state/settings store (uses QSettings with org/app set above)
    init_qsettings_store(dyn=dyn)

    # Resolve cache base path in parent process and propagate to cache helpers.
    cache_base = get_user_setting(UserSettingKey.CACHE_BASE_DIR)
    try:
        cache_path = set_cache_base_dir(cache_base or None)
    except OSError:
        logger.warning(
            "Cannot use configured cache base dir %r, fallback to default",
            cache_base,
        )
        cache_path = set_cache_base_dir(None)

    if bool(get_runtime_setting(RuntimeSettingKey.CLEAR_CACHE_ON_START)):
        if cache_path.exists():
            shutil.rmtree(cache_path)
            cache_path.mkdir(parents=True, exist_ok=True)

    # Start pyqtauto server for automation testing
    if start_server is not None:
        server = start_server(force=True)
        if server:
            logger.info(f"PyQtAuto server on port {server.port}")

    # Determine which folder to open
    if folder is None:
        last = get_state_value(StateKey.LAST_FOLDER)
        if last and os.path.isdir(last):
            folder = last
            logger.info(f"Opening last folder: {folder}")

    # Scan folder if provided
    images = []
    source_folders = []
    if folder:
        print(f"Scanning {folder}...")
        images, source_folders = scan_folder(folder)
        print(f"Found {len(images)} images in {len(source_folders)} folder(s).")
        # Save as last folder
        set_state_value(StateKey.LAST_FOLDER, folder)

    icon_path = resource_path("app.icns")
    app.setWindowIcon(QIcon(icon_path))

    window = MainWindow(images, source_folders, folder)
    app.aboutToQuit.connect(window.shutdown_for_quit)

    initial_resolution = get_runtime_setting(RuntimeSettingKey.INITIAL_RESOLUTION)
    if initial_resolution:
        # Testing override - ignore saved geometry
        try:
            w, h = str(initial_resolution).split("x")
            window.resize(int(w), int(h))
            window.show()
        except (ValueError, AttributeError):
            logger.warning(
                f"Invalid INITIAL_RESOLUTION: {initial_resolution}, opening maximized"
            )
            window.showMaximized()
    else:
        geo = get_state_value(StateKey.WINDOW_GEOMETRY)
        if geo is not None:
            window.restoreGeometry(geo)
            win_st = get_state_value(StateKey.WINDOW_STATE)
            if win_st is not None:
                window.restoreState(win_st)
            window.show()
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
                float(get_runtime_setting(RuntimeSettingKey.SHUTDOWN_TIMEOUT_S)),
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
