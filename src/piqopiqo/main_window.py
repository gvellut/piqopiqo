"""Main window for the application."""

from __future__ import annotations

from datetime import datetime
from functools import partial
import logging
import os
import shutil
import threading

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QAction, QActionGroup, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from send2trash import send2trash

from . import platform
from .config import Config, Shortcut
from .exif import ExifManager
from .exif_loader import ExifLoaderManager
from .fullscreen import FullscreenOverlay
from .grid import PhotoGrid
from .metadata.db_fields import EDITABLE_FIELDS, DBFields
from .metadata.metadata_db import MetadataDBManager
from .metadata.save_workers import MetadataSaveWorker
from .model import (
    FilterCriteria,
    ImageItem,
    LabelUndoEntry,
    OnFullscreenExitMultipleSelected,
)
from .orientation import rotate_orientation_left, rotate_orientation_right
from .panels import (
    EditPanel,
    ErrorListDialog,
    ExifPanel,
    FilterPanel,
    LoadingStatusBar,
)
from .photo_model import PhotoListModel, SortOrder
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
        self._current_filter: FilterCriteria | None = None  # Current filter criteria

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
        self.exif_manager = ExifManager(Config.EXIFTOOL_PATH)
        self.exif_manager.exif_ready.connect(self.on_exif_ready)

        self.grid.request_thumb.connect(self.request_thumb_handler)
        self.grid.request_fullscreen.connect(self._handle_fullscreen_overlay)
        self.grid.selection_changed.connect(self.on_selection_changed)
        self.grid.context_menu_requested.connect(self._show_context_menu)

        # Create photo list model
        self.photo_model = PhotoListModel(
            self.thumb_manager,
            self.exif_loader,
            self.db_manager,
            parent=self,
        )
        photos = [ImageItem(**data) for data in images]
        self.photo_model.set_photos(photos, source_folders)

        # Connect model signals
        self.photo_model.photos_changed.connect(self._on_model_changed)
        self.photo_model.photo_added.connect(self._on_photo_added)
        self.photo_model.photo_removed.connect(self._on_photo_removed)

        # Set up filter panel with folders
        self.filter_panel.set_folders(source_folders)

        self.grid.set_data(self.photo_model.photos)

        # Update status bar
        self.status_bar.set_photo_count(len(self.photo_model.all_photos))

        # Start background EXIF loading
        self._start_background_exif_loading()

        # Set up keyboard shortcuts
        self._label_save_pool = QThreadPool()
        self._setup_shortcuts()

        # Undo state for label changes
        self._label_undo_entry: LabelUndoEntry | None = None
        self._label_undo_is_redo: bool = False  # False = Undo mode, True = Redo mode
        # Start as True so first edit creates a new undo entry
        self._selection_changed_since_edit: bool = True

    @property
    def images_data(self) -> list[ImageItem]:
        """Filtered photo list (from model)."""
        return self.photo_model.photos

    @property
    def _all_images_data(self) -> list[ImageItem]:
        """All photos (from model)."""
        return self.photo_model.all_photos

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

        # Select All shortcut
        if Shortcut.SELECT_ALL in shortcuts:
            sc = QShortcut(
                parse_shortcut(shortcuts[Shortcut.SELECT_ALL]),
                self,
            )
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self._select_all_photos)

    def _select_all_photos(self):
        """Select all visible photos (after filtering)."""
        photos = self.photo_model.photos
        if not photos:
            return

        for photo in photos:
            photo.is_selected = True

        # Update grid's last selected index
        self.grid._last_selected_index = len(photos) - 1

        # Emit selection changed and refresh grid
        selected_indices = set(range(len(photos)))
        self.grid.selection_changed.emit(selected_indices)
        self.grid.on_scroll(self.grid.scrollbar.value())

    def _apply_label(self, label_name: str | None):
        """Apply a label to all selected photos."""
        selected_items = self._get_selected_items()
        if not selected_items:
            return

        # Capture previous labels before making changes
        previous_labels: dict[str, str | None] = {}
        for item in selected_items:
            # Ensure db_metadata exists
            if item.db_metadata is None:
                db = self.db_manager.get_db_for_image(item.path)
                existing = db.get_metadata(item.path)
                if existing:
                    item.db_metadata = existing.copy()
                else:
                    item.db_metadata = {field: None for field in EDITABLE_FIELDS}

            # Capture the current label before changing
            previous_labels[item.path] = item.db_metadata.get(DBFields.LABEL)

        # Create undo entry if selection changed since last edit
        if self._selection_changed_since_edit:
            # New undo session: create new entry with captured previous labels
            self._label_undo_entry = LabelUndoEntry(
                items=list(selected_items),
                previous_labels=previous_labels,
                new_labels={item.path: label_name for item in selected_items},
            )
            self._selection_changed_since_edit = False
        else:
            # Same selection: update the new_labels in existing entry
            if self._label_undo_entry is not None:
                self._label_undo_entry.new_labels = {
                    item.path: label_name for item in selected_items
                }

        # Reset to undo mode and enable the menu action
        self._label_undo_is_redo = False
        self._undo_label_action.setText("Undo label")
        self._undo_label_action.setEnabled(True)

        # Apply the label changes
        for item in selected_items:
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

    def _on_rotate_left(self):
        """Rotate selected photos 90° counter-clockwise."""
        self._apply_rotation(rotate_orientation_left)

    def _on_rotate_right(self):
        """Rotate selected photos 90° clockwise."""
        self._apply_rotation(rotate_orientation_right)

    def _apply_rotation(self, rotate_func):
        """Apply rotation to selected photos.

        Args:
            rotate_func: Function that takes current orientation and returns new.
        """
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

            # Get current orientation and rotate
            current_orientation = item.db_metadata.get(DBFields.ORIENTATION)
            new_orientation = rotate_func(current_orientation)
            item.db_metadata[DBFields.ORIENTATION] = new_orientation

            # Save to DB in background
            db = self.db_manager.get_db_for_image(item.path)
            worker = MetadataSaveWorker(db, item.path, item.db_metadata.copy())
            self._label_save_pool.start(worker)

            # Refresh grid cell immediately
            self.grid.refresh_item(item._global_index)

        # If fullscreen is open and showing one of these photos, reload image
        if self._fullscreen_overlay is not None:
            self._fullscreen_overlay._load_pixmap_at_current_index()
            self._fullscreen_overlay.update()

    def _on_undo_redo_label(self):
        """Handle undo/redo label action."""
        if self._label_undo_entry is None:
            return

        entry = self._label_undo_entry

        if self._label_undo_is_redo:
            # Redo: apply the new labels
            labels_to_apply = entry.new_labels
            self._undo_label_action.setText("Undo label")
            self._label_undo_is_redo = False
        else:
            # Undo: apply the previous labels
            labels_to_apply = entry.previous_labels
            self._undo_label_action.setText("Redo label")
            self._label_undo_is_redo = True

        # Apply the labels to the items
        for item in entry.items:
            if item.path in labels_to_apply:
                label_value = labels_to_apply[item.path]

                # Ensure db_metadata exists
                if item.db_metadata is None:
                    item.db_metadata = {field: None for field in EDITABLE_FIELDS}

                item.db_metadata[DBFields.LABEL] = label_value

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

        # Update edit panel for current selection
        selected_items = self._get_selected_items()
        if self.edit_panel and selected_items:
            self.edit_panel.update_for_selection(selected_items)

    def _on_edit_finished(self):
        """Return focus to grid after editing, unless still in edit panel."""
        focus_widget = QApplication.focusWidget()
        # Only return focus to grid if focus left the edit panel entirely
        if focus_widget is None or not self.edit_panel.isAncestorOf(focus_widget):
            self.grid.setFocus()

    def _on_refresh_requested(self, items: list[ImageItem]):
        """Handle refresh request from edit panel."""
        for item in items:
            self.exif_loader.queue_image(item.path, item.source_folder, force=True)

    def _start_background_exif_loading(self):
        """Queue all images for background EXIF loading."""
        self.exif_loader.reset(target_total=len(self.photo_model.all_photos))
        self.exif_loader.prime_from_db(self.photo_model.all_photos)

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

    def _on_filter_changed(self, criteria: FilterCriteria):
        """Handle filter change.

        Args:
            criteria: Filter criteria to apply.
        """
        self.photo_model.set_filter(criteria)

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

        refresh_action = QAction("Refresh Folder", self)
        refresh_action.triggered.connect(self._on_refresh_folder)
        file_menu.addAction(refresh_action)

        file_menu.addSeparator()

        clear_data_action = QAction("Clear All Data", self)
        clear_data_action.triggered.connect(self._on_clear_all_data)
        file_menu.addAction(clear_data_action)

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

        # Edit menu
        edit_menu = menubar.addMenu("Edit")

        self._undo_label_action = QAction("Undo label", self)
        # no shortcut for Undo label
        # self._undo_label_action.setShortcut("Ctrl+Z")
        self._undo_label_action.setEnabled(False)
        self._undo_label_action.triggered.connect(self._on_undo_redo_label)
        edit_menu.addAction(self._undo_label_action)

        # Image menu
        image_menu = menubar.addMenu("Image")

        rotate_left_action = QAction("Rotate Left", self)
        rotate_left_action.triggered.connect(self._on_rotate_left)
        image_menu.addAction(rotate_left_action)

        rotate_right_action = QAction("Rotate Right", self)
        rotate_right_action.triggered.connect(self._on_rotate_right)
        image_menu.addAction(rotate_right_action)

        # View menu
        view_menu = menubar.addMenu("View")

        # Sort submenu
        sort_menu = view_menu.addMenu("Sort By")
        sort_group = QActionGroup(self)
        sort_group.setExclusive(True)

        sort_time = QAction("Time Taken", self, checkable=True)
        sort_time.triggered.connect(lambda: self._set_sort_order(SortOrder.TIME_TAKEN))
        sort_group.addAction(sort_time)
        sort_menu.addAction(sort_time)

        sort_name = QAction("File Name", self, checkable=True, checked=True)
        sort_name.triggered.connect(lambda: self._set_sort_order(SortOrder.FILE_NAME))
        sort_group.addAction(sort_name)
        sort_menu.addAction(sort_name)

        sort_folder = QAction("File Name by Folder", self, checkable=True)
        sort_folder.triggered.connect(
            lambda: self._set_sort_order(SortOrder.FILE_NAME_BY_FOLDER)
        )
        sort_group.addAction(sort_folder)
        sort_menu.addAction(sort_folder)

        self._sort_actions = {
            SortOrder.TIME_TAKEN: sort_time,
            SortOrder.FILE_NAME: sort_name,
            SortOrder.FILE_NAME_BY_FOLDER: sort_folder,
        }

        view_menu.addSeparator()

        view_menu.addSeparator()

        regenerate_action = QAction("Regenerate Thumbnails", self)
        regenerate_action.triggered.connect(self.on_regenerate_thumbnails)
        view_menu.addAction(regenerate_action)

        # Tools menu
        tools_menu = menubar.addMenu("Tools")

        copy_sd_action = QAction("Copy from SD...", self)
        copy_sd_action.triggered.connect(self._on_copy_from_sd)
        tools_menu.addAction(copy_sd_action)

        tools_menu.addSeparator()

        save_exif_action = QAction("Save exif", self)
        save_exif_action.triggered.connect(self._on_save_exif)
        tools_menu.addAction(save_exif_action)

        help_menu = menubar.addMenu("Help")
        about_action = QAction(f"About {Config.APP_NAME}", self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self.on_about)
        help_menu.addAction(about_action)

    def on_about(self):
        pass

    def on_settings(self):
        pass

    def _on_copy_from_sd(self):
        from .copy_sd import launch_copy_sd

        launch_copy_sd(self)

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

        # Update photo model (replaces old _all_images_data and images_data)
        photos = [ImageItem(**data) for data in images]
        self.photo_model.set_photos(photos, source_folders)

        # Update filter panel
        self.filter_panel.set_folders(source_folders)

        self.grid.set_data(self.photo_model.photos)

        # Update status bar
        self.status_bar.set_photo_count(len(self.photo_model.all_photos))

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

    def _on_save_exif(self):
        """Save DB metadata to EXIF for selected or all filtered photos."""
        from .panels.save_exif_dialog import SaveExifDialog

        # Get items to process: selected if any, otherwise all filtered
        selected = self.photo_model.get_selected_photos()
        if selected:
            items = selected
        else:
            items = list(self.images_data)

        if not items:
            return

        dialog = SaveExifDialog(items, self.exif_manager, self)
        result = dialog.exec()

        if result == QDialog.DialogCode.Accepted:
            # Reload EXIF for processed items to reflect any changes
            processed_paths = set(dialog.get_processed_paths())
            for item in self._all_images_data:
                if item.path in processed_paths:
                    # Clear cached EXIF data so it gets reloaded
                    item.exif_data = None
                    # Queue for EXIF panel reload if item is visible/selected
                    self.exif_manager.fetch_exif(item.path)

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
        # Mark selection as changed for undo tracking
        self._selection_changed_since_edit = True

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
        phy_w, phy_h = platform.get_screen_true_resolution(current_screen)
        logger.debug(f"Physical resolution:  {phy_w} x {phy_h}")

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

    # --- Model signal handlers ---

    def _on_model_changed(self):
        """Handle model data change - refresh grid."""
        self.grid.set_data(self.photo_model.photos)
        total = len(self.photo_model.all_photos)
        filtered = len(self.photo_model.photos)
        if total == filtered:
            self.status_bar.set_photo_count(total)
        else:
            self.status_bar.set_photo_count(total, filtered)

    def _on_photo_added(self, file_path: str, index: int):
        """Handle photo added to model."""
        self.grid.set_data(self.photo_model.photos)
        if index >= 0:
            self.grid._ensure_visible(index)
        self._update_status_bar_count()

    def _on_photo_removed(self, file_path: str, former_index: int):
        """Handle photo removed from model."""
        # Determine new index to show
        new_index = min(former_index, len(self.photo_model.photos) - 1)
        self.grid.set_data(self.photo_model.photos)
        if new_index >= 0:
            self.photo_model.select_photo(new_index)
            self.grid._ensure_visible(new_index)
        self._update_status_bar_count()

    def _update_status_bar_count(self):
        """Update status bar photo count."""
        total = len(self.photo_model.all_photos)
        filtered = len(self.photo_model.photos)
        if total == filtered:
            self.status_bar.set_photo_count(total)
        else:
            self.status_bar.set_photo_count(total, filtered)

    # --- Sort order ---

    def _set_sort_order(self, order: SortOrder):
        """Set the sort order via menu."""
        self.photo_model.set_sort_order(order)

    # --- Refresh folder ---

    def _on_refresh_folder(self):
        """Refresh the current folder from disk."""
        if not self.root_folder:
            return

        added, removed = self.photo_model.refresh_from_disk(self.root_folder)
        logger.info(f"Refresh: {len(added)} added, {len(removed)} removed")

        # Update filter panel folders if changed
        self.filter_panel.set_folders(self.photo_model.source_folders)

    # --- Context menu ---

    def _show_context_menu(self, global_index: int, pos):
        """Show context menu for photo(s)."""
        from .external_apps import open_in_external_app, reveal_in_file_manager

        selected = self.photo_model.get_selected_photos()
        if not selected:
            return

        menu = QMenu(self)

        # Reveal in Finder
        reveal_action = menu.addAction("Reveal in Finder")
        reveal_action.triggered.connect(lambda: reveal_in_file_manager(selected))

        # View in Application (only if configured)
        if Config.EXTERNAL_VIEWER:
            view_app_action = menu.addAction(f"View in {Config.EXTERNAL_VIEWER}")
            view_app_action.triggered.connect(
                lambda: open_in_external_app(
                    Config.EXTERNAL_VIEWER, [p.path for p in selected]
                )
            )

        # Edit in Application (only if configured)
        if Config.EXTERNAL_EDITOR:
            edit_app_action = menu.addAction(f"Edit in {Config.EXTERNAL_EDITOR}")
            edit_app_action.triggered.connect(
                lambda: self._edit_in_external_app(selected)
            )

        menu.addSeparator()

        # Regenerate Thumbnail action
        if len(selected) == 1:
            regen_action = menu.addAction("Regenerate Thumbnail")
        else:
            regen_action = menu.addAction(
                f"Regenerate Thumbnails ({len(selected)} photos)"
            )
        regen_action.triggered.connect(
            lambda: self._regenerate_selected_thumbnails(selected)
        )

        menu.addSeparator()

        # Duplicate action
        if len(selected) == 1:
            duplicate_action = menu.addAction("Duplicate")
        else:
            duplicate_action = menu.addAction(f"Duplicate ({len(selected)} photos)")
        duplicate_action.triggered.connect(lambda: self._duplicate_photos(selected))

        menu.addSeparator()

        # Move to Trash action
        if len(selected) == 1:
            trash_action = menu.addAction("Move to Trash")
        else:
            trash_action = menu.addAction(f"Move to Trash ({len(selected)} photos)")
        trash_action.triggered.connect(lambda: self._move_to_trash(selected))

        menu.exec(pos)

    def _duplicate_photos(self, photos: list[ImageItem]):
        """Duplicate selected photos."""
        for photo in photos:
            new_path = self._get_duplicate_path(photo.path)
            try:
                shutil.copy2(photo.path, new_path)

                # Create ImageItem for new photo
                new_item = ImageItem(
                    path=new_path,
                    name=os.path.basename(new_path),
                    created=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    source_folder=photo.source_folder,
                )

                # Add to model (triggers thumbnail/EXIF loading)
                self.photo_model.add_photo(new_item)
                logger.info(f"Duplicated {photo.path} to {new_path}")

            except OSError as e:
                logger.error(f"Failed to duplicate {photo.path}: {e}")

    def _get_duplicate_path(self, original_path: str) -> str:
        """Generate a path for a duplicate file."""
        directory = os.path.dirname(original_path)
        name, ext = os.path.splitext(os.path.basename(original_path))

        # Try " copy", then " copy2", " copy3", etc.
        suffix = " copy"
        counter = 1

        while True:
            if counter == 1:
                new_name = f"{name}{suffix}{ext}"
            else:
                new_name = f"{name}{suffix}{counter}{ext}"

            new_path = os.path.join(directory, new_name)
            if not os.path.exists(new_path):
                return new_path
            counter += 1

    def _move_to_trash(self, photos: list[ImageItem]):
        """Move selected photos to trash."""
        paths_to_remove = []

        for photo in photos:
            try:
                send2trash(photo.path)
                paths_to_remove.append(photo.path)
                logger.info(f"Moved to trash: {photo.path}")
            except Exception as e:
                logger.error(f"Failed to trash {photo.path}: {e}")

        # Remove from model (handles cleanup)
        for path in paths_to_remove:
            self.photo_model.remove_photo(path)

    def _regenerate_selected_thumbnails(self, photos: list[ImageItem]):
        """Regenerate thumbnails for selected photos."""
        for photo in photos:
            photo.state = 0
            photo.pixmap = None
            self.thumb_manager.clear_and_requeue_image(photo.path)

        # Refresh the grid to show placeholders until new thumbs arrive
        self.grid.on_scroll(self.grid.scrollbar.value())

    def _edit_in_external_app(self, photos: list[ImageItem]):
        """Duplicate selected photos and open duplicates in external editor."""
        from .external_apps import open_in_external_app

        duplicated_paths = []
        for photo in photos:
            new_path = self._get_duplicate_path(photo.path)
            try:
                shutil.copy2(photo.path, new_path)
                new_item = ImageItem(
                    path=new_path,
                    name=os.path.basename(new_path),
                    created=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    source_folder=photo.source_folder,
                )
                self.photo_model.add_photo(new_item)
                duplicated_paths.append(new_path)
                logger.info(f"Duplicated {photo.path} to {new_path} for editing")
            except OSError as e:
                logger.error(f"Failed to duplicate {photo.path}: {e}")

        if duplicated_paths:
            open_in_external_app(Config.EXTERNAL_EDITOR, duplicated_paths)

    def _on_clear_all_data(self):
        """Clear all cached data (thumbnails + DB) and reload the folder."""
        if not self.root_folder:
            return

        reply = QMessageBox.warning(
            self,
            "Clear All Data",
            "This will delete all cached thumbnails and metadata databases, "
            "then reload the current folder from scratch.\n\n"
            "This cannot be undone. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        logger.info("Clearing all data and reloading folder")

        # Delete all metadata from registered databases
        self.db_manager.delete_all_metadata()

        # Close all DB connections (files will be recreated on reload)
        self.db_manager.close_all()

        # Clear all thumbnail caches
        self.thumb_manager.clear_all_registered_caches()

        # Reload the folder from scratch
        self._load_folder(self.root_folder)

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
