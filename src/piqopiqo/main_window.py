"""Main window for the application."""

from __future__ import annotations

from functools import partial
import logging
import threading

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QAction, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import platform
from .components.save_workers import MetadataSaveWorker
from .config import Config, Shortcut
from .db_fields import EDITABLE_FIELDS, DBFields
from .exif_loader import ExifLoaderManager
from .exif_man import ExifManager
from .fullscreen import FullscreenOverlay
from .grid import PhotoGrid
from .metadata_db import MetadataDBManager
from .model import ImageItem, OnFullscreenExitMultipleSelected
from .panels import (
    EditPanel,
    ErrorListDialog,
    ExifPanel,
    FilterPanel,
    LoadingStatusBar,
)
from .shortcuts import parse_shortcut
from .support import save_last_folder
from .thumb_man import ThumbnailManager, scan_folder

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, images, source_folders, root_folder, etHelper):
        super().__init__()
        self.setWindowTitle(Config.APP_NAME)

        self._fullscreen_overlay = None
        self.etHelper = etHelper
        self.root_folder = root_folder
        self.source_folders = source_folders
        self._current_filter = None  # Current folder filter

        # Create metadata database manager
        self.db_manager = MetadataDBManager()

        self._create_menu_bar()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Folder filter panel (at top)
        self.filter_panel = FilterPanel()
        self.filter_panel.filter_changed.connect(self._on_filter_changed)
        main_layout.addWidget(self.filter_panel, 0)

        # Main horizontal splitter: grid | right panel(s)
        main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(main_splitter)

        self.grid = PhotoGrid()
        main_splitter.addWidget(self.grid)

        # Right side: vertical splitter with edit panel and EXIF panel
        if Config.SHOW_EDIT_PANEL:
            right_splitter = QSplitter(Qt.Vertical)

            self.edit_panel = EditPanel(self.db_manager)
            self.edit_panel.edit_finished.connect(self._on_edit_finished)
            self.edit_panel.refresh_requested.connect(self._on_refresh_requested)
            right_splitter.addWidget(self.edit_panel)

            self.exif_panel = ExifPanel()
            right_splitter.addWidget(self.exif_panel)

            # Split evenly between edit and exif panels
            right_splitter.setSizes([200, 200])

            main_splitter.addWidget(right_splitter)
        else:
            self.edit_panel = None
            self.exif_panel = ExifPanel()
            main_splitter.addWidget(self.exif_panel)

        main_splitter.setSizes([int(self.width() * 0.8), int(self.width() * 0.2)])

        # Status bar (standard QMainWindow status bar)
        self.status_bar = LoadingStatusBar()
        self.status_bar.show_errors_requested.connect(self._show_error_dialog)
        self.setStatusBar(self.status_bar)

        # Thumbnail manager
        self.thumb_manager = ThumbnailManager()
        self.thumb_manager.thumb_ready.connect(self.on_thumb_ready)
        self.thumb_manager.progress_updated.connect(self._on_thumb_progress)
        self.thumb_manager.all_completed.connect(self._on_loading_complete)

        # Register all source folders with the thumbnail manager
        for folder in source_folders:
            self.thumb_manager.register_folder(folder)

        # Shared lock for ExifToolHelper (not thread-safe)
        self._exif_lock = threading.Lock()

        # EXIF loader for editable fields (background)
        self.exif_loader = ExifLoaderManager(
            etHelper, self.db_manager, exif_lock=self._exif_lock
        )
        self.exif_loader.exif_loaded.connect(self._on_exif_loaded)
        self.exif_loader.exif_error.connect(self._on_exif_error)
        self.exif_loader.progress_updated.connect(self._on_exif_progress)
        self.exif_loader.all_completed.connect(self._on_loading_complete)

        # EXIF manager for display panel (on-demand)
        self.exif_manager = ExifManager(Config.EXIFTOOL_PATH, common_args=["-G"])
        self.exif_manager.exif_ready.connect(self.on_exif_ready)

        self.grid.request_thumb.connect(self.request_thumb_handler)
        self.grid.request_fullscreen.connect(self._handle_fullscreen_overlay)
        self.grid.selection_changed.connect(self.on_selection_changed)

        # Store all images (unfiltered)
        self._all_images_data = [ImageItem(**data) for data in images]
        self.images_data = self._all_images_data

        # Set up filter panel with folders
        self.filter_panel.set_folders(source_folders)

        self.grid.set_data(self.images_data)

        # Update status bar
        self.status_bar.set_photo_count(len(self._all_images_data))

        # Start background EXIF loading
        self._start_background_exif_loading()

        # Set up keyboard shortcuts
        self._label_save_pool = QThreadPool()
        self._setup_shortcuts()

    def _setup_shortcuts(self):
        """Set up application-wide keyboard shortcuts from config."""
        shortcuts = Config.SHORTCUTS

        # Label shortcuts (1-9 and backtick) - application-wide
        for i in range(1, 10):
            shortcut_enum = Shortcut(f"LABEL_{i}")
            if shortcut_enum in shortcuts:
                # Find label with matching index
                label_name = None
                for sl in Config.STATUS_LABELS:
                    if sl.index == i:
                        label_name = sl.name
                        break

                # do not set to no label if no shortcut defined
                if label_name is None:
                    continue

                sc = QShortcut(
                    parse_shortcut(shortcuts[shortcut_enum]),
                    self,
                )
                sc.setContext(Qt.ApplicationShortcut)

                sc.activated.connect(partial(self._apply_label, label_name))

        # No-label shortcut (backtick)
        if Shortcut.LABEL_NONE in shortcuts:
            sc = QShortcut(
                parse_shortcut(shortcuts[Shortcut.LABEL_NONE]),
                self,
            )
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(partial(self._apply_label, None))

    def _apply_label(self, label_name: str | None):
        """Apply a label to all selected photos."""
        selected_items = self._get_selected_items()
        if not selected_items:
            return

        for item in selected_items:
            # Ensure db_metadata exists
            if item.db_metadata is None:
                db = self.db_manager.get_db_for_image(item.path)
                existing = db.get_metadata(item.path)
                if existing:
                    item.db_metadata = existing.copy()
                else:
                    item.db_metadata = {field: None for field in EDITABLE_FIELDS}

            # Update label
            item.db_metadata[DBFields.LABEL] = label_name

            # Save to DB in background
            db = self.db_manager.get_db_for_image(item.path)
            worker = MetadataSaveWorker(db, item.path, item.db_metadata.copy())
            self._label_save_pool.start(worker)

            # Refresh grid cell immediately
            self.grid.refresh_item(item._global_index)

        # Update fullscreen overlay swatch if open
        if self._fullscreen_overlay is not None:
            self._fullscreen_overlay._update_color_swatch()
            self._fullscreen_overlay.update()

        # Update edit panel if visible
        if self.edit_panel:
            self.edit_panel.update_for_selection(selected_items)

    def _on_edit_finished(self):
        """Return focus to grid after editing."""
        self.grid.setFocus()

    def _on_refresh_requested(self, items: list[ImageItem]):
        """Handle refresh request from edit panel."""
        for item in items:
            self.exif_loader.queue_image(item.path, item.source_folder, force=True)

    def _start_background_exif_loading(self):
        """Queue all images for background EXIF loading."""
        self.exif_loader.reset(target_total=len(self._all_images_data))
        self.exif_loader.prime_from_db(self._all_images_data)

    def _on_thumb_progress(self, completed: int, total: int):
        """Handle thumbnail progress update."""
        self.status_bar.set_thumb_progress(completed, total)

    def _on_exif_progress(self, completed: int, total: int):
        """Handle EXIF loading progress update."""
        self.status_bar.set_exif_progress(completed, total)

    def _on_loading_complete(self):
        """Handle completion of loading (thumbnails or EXIF)."""
        has_errors = self.thumb_manager.has_errors() or self.exif_loader.has_errors()
        self.status_bar.set_has_errors(has_errors)

    def _on_exif_loaded(self, file_path: str, metadata: dict):
        """Handle EXIF data loaded in background."""
        # Find the item and update its db_metadata
        for item in self._all_images_data:
            if item.path == file_path:
                item.db_metadata = metadata

                # Refresh grid item if visible
                self.grid.refresh_item(item._global_index)

                # If this item is selected, update edit panel
                selected_items = self._get_selected_items()
                if item in selected_items and self.edit_panel:
                    self.edit_panel.update_for_selection(selected_items)
                break

    def _on_exif_error(self, file_path: str, error_message: str):
        """Handle EXIF loading error."""
        logger.error(f"EXIF loading error for {file_path}: {error_message}")

    def _show_error_dialog(self):
        """Show dialog with loading errors."""
        dialog = ErrorListDialog(
            self.thumb_manager.get_errors(),
            self.exif_loader.get_errors(),
            self,
        )
        dialog.exec()

    def _get_selected_items(self) -> list[ImageItem]:
        """Get list of currently selected items."""
        return [item for item in self.images_data if item.is_selected]

    def _on_filter_changed(self, folder_path: str | None):
        """Handle folder filter change.

        Args:
            folder_path: Folder to filter by, or None to show all.
        """
        self._current_filter = folder_path
        self._apply_filter()

    def _apply_filter(self):
        """Apply the current filter to the images."""
        if self._current_filter is None:
            # Show all images
            self.images_data = self._all_images_data
            self.status_bar.set_photo_count(len(self._all_images_data))
        else:
            # Filter by source folder
            self.images_data = [
                item
                for item in self._all_images_data
                if item.source_folder == self._current_filter
            ]
            self.status_bar.set_photo_count(
                len(self._all_images_data), len(self.images_data)
            )

        self.grid.set_data(self.images_data)

        # Clear panels since selection changed
        self.exif_panel.update_exif([])
        if self.edit_panel:
            self.edit_panel.update_for_selection([])

    def _create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        open_action = QAction("Open Folder...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.on_open)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        regenerate_action = QAction("Regenerate Thumbnails", self)
        regenerate_action.setShortcut("Ctrl+Shift+R")
        regenerate_action.triggered.connect(self.on_regenerate_thumbnails)
        file_menu.addAction(regenerate_action)

        file_menu.addSeparator()

        settings_action = QAction("Settings...", self)
        settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        settings_action.triggered.connect(self.on_settings)
        file_menu.addAction(settings_action)

        quit_action = QAction(f"Quit {Config.APP_NAME}", self)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = menubar.addMenu("Help")
        about_action = QAction(f"About {Config.APP_NAME}", self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self.on_about)
        help_menu.addAction(about_action)

    def on_about(self):
        pass

    def on_settings(self):
        pass

    def on_open(self):
        """Open a folder using a file dialog."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Open Folder",
            self.root_folder or "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self._load_folder(folder)

    def _load_folder(self, folder: str):
        """Load images from a folder and update the UI."""
        logger.info(f"Loading folder: {folder}")

        # Scan the folder
        images, source_folders = scan_folder(folder)
        logger.info(f"Found {len(images)} images in {len(source_folders)} folder(s)")

        # Save as last folder
        save_last_folder(folder)

        # Update state
        self.root_folder = folder
        self.source_folders = source_folders
        self._current_filter = None

        # Close old database connections and create new manager
        self.db_manager.close_all()

        # Reset progress tracking
        self.thumb_manager.reset_progress()
        self.exif_loader.reset(target_total=0)
        self.status_bar.reset()

        # Clear and re-register folders with thumbnail manager
        self.thumb_manager._folder_thumb_dirs.clear()
        for src_folder in source_folders:
            self.thumb_manager.register_folder(src_folder)

        # Update images data
        self._all_images_data = [ImageItem(**data) for data in images]
        self.images_data = self._all_images_data

        # Update filter panel
        self.filter_panel.set_folders(source_folders)

        self.grid.set_data(self.images_data)

        # Update status bar
        self.status_bar.set_photo_count(len(self._all_images_data))

        # Start background EXIF loading
        self._start_background_exif_loading()

        # Clear panels
        self.exif_panel.update_exif([])
        if self.edit_panel:
            self.edit_panel.update_for_selection([])

    def on_regenerate_thumbnails(self):
        """Regenerate all thumbnails for currently loaded folders."""
        if not self.source_folders:
            logger.warning("No folders loaded, nothing to regenerate")
            return

        logger.info(f"Regenerating thumbnails for {len(self.source_folders)} folder(s)")

        # Clear the thumbnail cache for all registered folders
        self.thumb_manager.clear_all_registered_caches()

        # Reset all image states to trigger re-generation
        for item in self.images_data:
            item.state = 0
            item.pixmap = None

        # Refresh the grid to trigger thumbnail requests
        self.grid.on_scroll(self.grid.scrollbar.value())

    def on_thumb_ready(self, file_path, thumb_type, cache_path):
        # Update the data list directly
        for i, item in enumerate(self.images_data):
            if item.path == file_path:
                pixmap = QPixmap(cache_path)
                state = 1 if thumb_type == "embedded" else 2

                # Update item
                item.pixmap = pixmap
                item.state = state

                # Refresh Grid View
                self.grid.refresh_item(i)
                break

    def on_exif_ready(self, file_path, metadata):
        # TODO index the images_data so do not loop through it
        for item in self.images_data:
            if item.path == file_path:
                item.exif_data = metadata
                # If this item is currently selected, refresh the panel
                selected_indices = {
                    i for i, item in enumerate(self.images_data) if item.is_selected
                }
                if item._global_index in selected_indices:
                    self.on_selection_changed(selected_indices)
                break

    def on_selection_changed(self, selected_indices):
        selected_items = [self.images_data[i] for i in selected_indices]

        # Load db_metadata for selected items if not already loaded
        for item in selected_items:
            if item.db_metadata is None:
                db = self.db_manager.get_db_for_image(item.path)
                item.db_metadata = db.get_metadata(item.path)

        # Check if all selected items have EXIF data (for display panel)
        all_exif_loaded = all(item.exif_data is not None for item in selected_items)

        # Fetch EXIF for display panel (non-editable fields)
        for item in selected_items:
            if item.exif_data is None:
                self.exif_manager.fetch_exif(item.path)

        # Update edit panel immediately (uses DB data)
        if self.edit_panel:
            self.edit_panel.update_for_selection(selected_items)

        # Update EXIF panel only if all EXIF data is loaded
        if all_exif_loaded:
            self.exif_panel.update_exif(selected_items)

    def request_thumb_handler(self, index):
        if 0 <= index < len(self.images_data):
            file_path = self.images_data[index].path
            self.thumb_manager.queue_image(file_path)

    def _handle_fullscreen_overlay(self, selected_indices: list):
        """Display the selected image in a fullscreen overlay."""
        if not selected_indices:
            return

        # Close any existing overlay first
        if self._fullscreen_overlay is not None:
            self._fullscreen_overlay.close()
            self._fullscreen_overlay = None

        start_index = selected_indices[0]

        # Identify the screen the window is currently on
        current_screen = self.screen()
        if not current_screen:
            logger.debug("Could not determine screen")
            return

        # Log resolution info
        log_geo = current_screen.geometry()
        dpr = current_screen.devicePixelRatio()
        buffer_w = int(log_geo.width() * dpr)
        buffer_h = int(log_geo.height() * dpr)

        logger.debug(f"Screen Name:    {current_screen.name()}")
        logger.debug(f"Logical Size:   {log_geo.width()} x {log_geo.height()}")
        logger.debug(f"DPR:            {dpr}")
        logger.debug(f"Render Buffer:  {buffer_w} x {buffer_h}")

        # not actually useful : cannot be used by the macos rendering (without changing
        # the display resolution and flickering => so forget about it)
        # TODO remove
        phy_w, phy_h = platform.get_platform_true_resolution(current_screen)
        logger.info(f"Physical resolution:  {phy_w} x {phy_h}")

        if len(selected_indices) > 1:
            visible_indices = selected_indices
        else:
            visible_indices = list(range(len(self.images_data)))

        self._fullscreen_overlay = FullscreenOverlay(
            self.images_data, visible_indices, start_index
        )

        self._fullscreen_overlay.index_changed.connect(
            self._on_fullscreen_index_changed
        )

        # Handle cleanup and selection logic on close
        def on_fullscreen_close():
            last_viewed_idx = self._fullscreen_overlay.visible_indices[
                self._fullscreen_overlay.current_visible_idx
            ]

            if (
                len(selected_indices) > 1
                and Config.ON_FULLSCREEN_EXIT
                == OnFullscreenExitMultipleSelected.SELECT_LAST_VIEWED
            ):
                self.grid.on_cell_clicked(last_viewed_idx, False, False)
                self.grid._ensure_visible(last_viewed_idx)

            self._fullscreen_overlay = None

        self._fullscreen_overlay.destroyed.connect(on_fullscreen_close)
        self._fullscreen_overlay.show_on_screen(current_screen)

    def _on_fullscreen_index_changed(self, new_index: int):
        """Update grid selection when navigating in fullscreen mode."""
        if self._fullscreen_overlay and len(
            self._fullscreen_overlay.visible_indices
        ) < len(self.images_data):
            # In multi-selection mode, just update the last selected index
            self.grid._last_selected_index = new_index
            self.grid._ensure_visible(new_index)
            # We still need to repaint the grid to show the new "last selected" item
            self.grid.on_scroll(self.grid.scrollbar.value())
        else:
            # In single-selection (all items visible) mode, update the selection
            self.grid.on_cell_clicked(new_index, False, False)
            self.grid._ensure_visible(new_index)

    def closeEvent(self, event):
        # Stop background workers first to avoid noisy teardown.
        if hasattr(self, "exif_loader"):
            self.exif_loader.stop(wait_ms=int(Config.SHUTDOWN_TIMEOUT_S * 1000))
        if hasattr(self, "exif_manager"):
            self.exif_manager.stop(timeout_s=Config.SHUTDOWN_TIMEOUT_S)
        if hasattr(self, "thumb_manager"):
            self.thumb_manager.stop(timeout_s=Config.SHUTDOWN_TIMEOUT_S)
        if hasattr(self, "db_manager"):
            self.db_manager.close_all()
        super().closeEvent(event)
