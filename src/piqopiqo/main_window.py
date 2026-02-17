"""Main window for the application."""

from __future__ import annotations

from datetime import datetime
from functools import partial
import logging
import os
import shutil
import sys
import time

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
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
from .background.media_man import MediaManager
from .cache_paths import set_cache_base_dir
from .folder_scan import scan_folder
from .folder_watcher import FolderWatcher
from .fullscreen import FullscreenOverlay
from .grid import PhotoGrid
from .metadata.db_fields import DBFields
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
from .settings_panel import SettingsDialog
from .settings_state import (
    APP_NAME,
    RuntimeSettingKey,
    StateKey,
    UserSettingKey,
    get_runtime_setting,
    get_state,
    get_user_setting,
)
from .shortcuts import Shortcut, parse_shortcut

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, images, source_folders, root_folder):
        super().__init__()
        self.setWindowTitle(APP_NAME)

        self._fullscreen_overlay = None
        self.root_folder = root_folder
        self.source_folders = source_folders
        self._current_filter: FilterCriteria | None = None  # Current filter criteria

        self._items_by_path: dict[str, ImageItem] = {}
        self._last_visible_paths: list[str] = []
        self._model_refresh_scheduled = False
        self._folder_watcher: FolderWatcher | None = None
        self._watcher_suppressed: dict[str, float] = {}

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
        self._main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self._main_splitter)

        self.grid = PhotoGrid()
        self._main_splitter.addWidget(self.grid)

        # Right side: vertical splitter with edit panel and EXIF panel
        self._right_splitter = None
        if get_runtime_setting(RuntimeSettingKey.SHOW_EDIT_PANEL):
            self._right_splitter = QSplitter(Qt.Vertical)

            self.edit_panel = EditPanel(self.db_manager)
            self.edit_panel.edit_finished.connect(self._on_edit_finished)
            self._right_splitter.addWidget(self.edit_panel)

            self.exif_panel = ExifPanel()
            self._right_splitter.addWidget(self.exif_panel)

            # Split evenly between edit and exif panels
            self._right_splitter.setSizes([200, 200])

            self._main_splitter.addWidget(self._right_splitter)
        else:
            self.edit_panel = None
            self.exif_panel = ExifPanel()
            self._main_splitter.addWidget(self.exif_panel)

        self._main_splitter.setSizes([int(self.width() * 0.8), int(self.width() * 0.2)])

        # Restore splitter state from saved settings
        state = get_state()
        splitter_state = state.get(StateKey.MAIN_SPLITTER)
        if splitter_state:
            self._main_splitter.restoreState(splitter_state)
        if self._right_splitter:
            right_state = state.get(StateKey.RIGHT_SPLITTER)
            if right_state:
                self._right_splitter.restoreState(right_state)

        # Status bar (standard QMainWindow status bar)
        self.status_bar = LoadingStatusBar()
        self.status_bar.show_errors_requested.connect(self._show_error_dialog)
        self.setStatusBar(self.status_bar)

        # Unified background manager (multiprocessing)
        self.media_manager = MediaManager(self.db_manager, parent=self)
        self.media_manager.thumb_ready.connect(self.on_thumb_ready)
        self.media_manager.thumb_progress_updated.connect(self._on_thumb_progress)
        self.media_manager.editable_ready.connect(self._on_editable_ready)
        self.media_manager.exif_progress_updated.connect(self._on_exif_progress)
        self.media_manager.panel_fields_ready.connect(self._on_panel_fields_ready)
        self.media_manager.all_completed.connect(self._on_loading_complete)

        self.grid.request_thumb.connect(self.request_thumb_handler)
        self.grid.visible_paths_changed.connect(self._on_visible_paths_changed)
        self.grid.request_fullscreen.connect(self._handle_fullscreen_overlay)
        self.grid.selection_changed.connect(self.on_selection_changed)
        self.grid.context_menu_requested.connect(self._show_context_menu)

        # Create photo list model
        self.photo_model = PhotoListModel(
            self.db_manager,
            parent=self,
        )
        photos = [ImageItem(**data) for data in images]
        self.photo_model.set_photos(photos, source_folders)
        self._items_by_path = {item.path: item for item in self.photo_model.all_photos}

        # Connect model signals
        self.photo_model.photos_changed.connect(self._on_model_changed)
        self.photo_model.photo_added.connect(self._on_photo_added)
        self.photo_model.photo_removed.connect(self._on_photo_removed)

        # Set up filter panel with folders
        self.filter_panel.set_folders(source_folders)

        self.grid.set_data(self.photo_model.photos)

        # Update status bar
        self.status_bar.set_photo_count(len(self.photo_model.all_photos))

        # Start background loading (EXIF + thumbs)
        self.media_manager.reset_for_folder(
            [p.path for p in self.photo_model.all_photos],
            self.photo_model.source_folders,
        )
        if self._last_visible_paths:
            self.media_manager.update_visible(self._last_visible_paths)

        # Set up keyboard shortcuts
        self._label_save_pool = QThreadPool()
        self._shortcut_objects: list[QShortcut] = []
        self._setup_shortcuts()

        # Undo state for label changes
        self._label_undo_entry: LabelUndoEntry | None = None
        self._label_undo_is_redo: bool = False  # False = Undo mode, True = Redo mode
        # Start as True so first edit creates a new undo entry
        self._selection_changed_since_edit: bool = True

        self._start_folder_watcher()

    @property
    def images_data(self) -> list[ImageItem]:
        """Filtered photo list (from model)."""
        return self.photo_model.photos

    @property
    def _all_images_data(self) -> list[ImageItem]:
        """All photos (from model)."""
        return self.photo_model.all_photos

    def _setup_shortcuts(self):
        """Set up application-wide keyboard shortcuts from user settings."""
        for sc in self._shortcut_objects:
            sc.setParent(None)
            sc.deleteLater()
        self._shortcut_objects = []

        shortcuts = get_user_setting(UserSettingKey.SHORTCUTS)
        status_labels = get_user_setting(UserSettingKey.STATUS_LABELS)

        # Label shortcuts (1-9 and backtick) - application-wide
        for i in range(1, 10):
            shortcut_enum = Shortcut(f"LABEL_{i}")
            if shortcut_enum in shortcuts:
                # Find label with matching index
                label_name = None
                for sl in status_labels:
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
                self._shortcut_objects.append(sc)

        # No-label shortcut (backtick)
        if Shortcut.LABEL_NONE in shortcuts:
            sc = QShortcut(
                parse_shortcut(shortcuts[Shortcut.LABEL_NONE]),
                self,
            )
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(partial(self._apply_label, None))
            self._shortcut_objects.append(sc)

        # Select All shortcut
        if Shortcut.SELECT_ALL in shortcuts:
            sc = QShortcut(
                parse_shortcut(shortcuts[Shortcut.SELECT_ALL]),
                self,
            )
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self._select_all_photos)
            self._shortcut_objects.append(sc)

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

        if not self._ensure_db_metadata_ready(selected_items):
            QApplication.beep()
            self.status_bar.showMessage("Reading...", 2000)
            return

        # Capture previous labels before making changes
        previous_labels: dict[str, str | None] = {}
        for item in selected_items:
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

        if not self._ensure_db_metadata_ready(selected_items):
            QApplication.beep()
            self.status_bar.showMessage("Reading...", 2000)
            return

        for item in selected_items:
            # Get current orientation and rotate
            current_orientation = item.db_metadata.get(DBFields.ORIENTATION)
            new_orientation = rotate_func(current_orientation)
            item.db_metadata[DBFields.ORIENTATION] = new_orientation

            # Invalidate cached oriented display pixmap so it gets rebuilt
            item.pixmap = None
            item._pixmap_source = None

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

                if item.db_metadata is None:
                    db = self.db_manager.get_db_for_image(item.path)
                    meta = db.get_metadata(item.path)
                    if meta is None:
                        continue
                    item.db_metadata = meta.copy()

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

    def _on_thumb_progress(self, completed: int, total: int):
        """Handle thumbnail progress update."""
        self.status_bar.set_thumb_progress(completed, total)

    def _on_exif_progress(self, completed: int, total: int):
        """Handle EXIF loading progress update."""
        self.status_bar.set_exif_progress(completed, total)

    def _on_loading_complete(self):
        """Handle completion of loading (thumbnails or EXIF)."""
        self.status_bar.set_has_errors(self.media_manager.has_errors())

    def _on_visible_paths_changed(self, visible_paths: list[str]):
        self._last_visible_paths = list(visible_paths)
        self.media_manager.update_visible(self._last_visible_paths)

    def _on_editable_ready(self, file_path: str, metadata: dict):
        item = self._items_by_path.get(file_path)
        if item is None:
            return

        item.db_metadata = metadata
        self.grid.refresh_item(item._global_index)

        selected_items = self._get_selected_items()
        if self.edit_panel and item in selected_items:
            self.edit_panel.update_for_selection(selected_items)

        needs_resort = self.photo_model.sort_order == SortOrder.TIME_TAKEN
        if self._current_filter is not None:
            needs_resort = needs_resort or bool(
                self._current_filter.search_text
                or self._current_filter.labels
                or self._current_filter.include_no_label
            )
        if needs_resort and not self._model_refresh_scheduled:
            self._model_refresh_scheduled = True
            QTimer.singleShot(50, self._refresh_model_after_metadata)

    def _refresh_model_after_metadata(self):
        self._model_refresh_scheduled = False
        self.photo_model.refresh_after_metadata_update()

    def _on_panel_fields_ready(self, file_path: str, fields: dict):
        item = self._items_by_path.get(file_path)
        if item is None:
            return

        item.exif_data = fields

        selected_items = self._get_selected_items()
        if item in selected_items:
            self.exif_panel.update_exif(selected_items)

    def _show_error_dialog(self):
        """Show dialog with loading errors."""
        dialog = ErrorListDialog(
            self.media_manager.get_thumb_errors(),
            self.media_manager.get_exif_errors(),
            self,
        )
        dialog.exec()

    def _get_selected_items(self) -> list[ImageItem]:
        """Get list of currently selected items."""
        return [item for item in self.images_data if item.is_selected]

    def _ensure_db_metadata_ready(self, items: list[ImageItem]) -> bool:
        """Ensure editable DB metadata exists for all items.

        Returns False if any item is still missing metadata (EXIF not read yet).
        """
        for item in items:
            if item.db_metadata is not None:
                continue
            db = self.db_manager.get_db_for_image(item.path)
            meta = db.get_metadata(item.path)
            if meta is None:
                return False
            item.db_metadata = meta.copy()
        return True

    def _on_filter_changed(self, criteria: FilterCriteria):
        """Handle filter change.

        Args:
            criteria: Filter criteria to apply.
        """
        self._current_filter = criteria
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

        clear_data_action = QAction("Clear All Data", self)
        clear_data_action.triggered.connect(self._on_clear_all_data)
        file_menu.addAction(clear_data_action)

        file_menu.addSeparator()

        settings_label = "Settings..." if sys.platform == "darwin" else "Preferences..."
        settings_action = QAction(settings_label, self)
        settings_action.triggered.connect(self.on_settings)
        if sys.platform == "darwin":
            # On macOS, Qt relocates this from File to the standard app menu.
            settings_action.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)
            settings_action.setShortcut(QKeySequence.Preferences)
        else:
            settings_action.setMenuRole(QAction.MenuRole.NoRole)
        file_menu.addAction(settings_action)

        quit_action = QAction(f"Quit {APP_NAME}", self)
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

        regenerate_exif_action = QAction("Regenerate EXIF", self)
        regenerate_exif_action.triggered.connect(self.on_regenerate_exif)
        tools_menu.addAction(regenerate_exif_action)

        help_menu = menubar.addMenu("Help")
        about_action = QAction(f"About {APP_NAME}", self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self.on_about)
        help_menu.addAction(about_action)

    def on_about(self):
        pass

    def on_settings(self):
        dialog = SettingsDialog(self)
        dialog.setting_saved.connect(self._on_setting_saved)
        dialog.exec()
        self._apply_settings_changes(dialog.changed_keys)

    def _on_setting_saved(self, key: object) -> None:
        resolved_key = (
            key if isinstance(key, UserSettingKey) else UserSettingKey(str(key))
        )
        self._apply_settings_changes({resolved_key})

    def _apply_settings_changes(self, changed_keys: set[UserSettingKey]) -> None:
        if not changed_keys:
            return

        if UserSettingKey.NUM_COLUMNS in changed_keys:
            self.grid.set_num_columns(int(get_user_setting(UserSettingKey.NUM_COLUMNS)))

        if UserSettingKey.STATUS_LABELS in changed_keys:
            self.filter_panel.reload_status_labels()
            self.grid.on_scroll(self.grid.scrollbar.value())
            if self._fullscreen_overlay is not None:
                self._fullscreen_overlay._update_color_swatch()
                self._fullscreen_overlay.update()

        if UserSettingKey.SHORTCUTS in changed_keys:
            self._setup_shortcuts()

        if UserSettingKey.CACHE_BASE_DIR in changed_keys:
            try:
                set_cache_base_dir(get_user_setting(UserSettingKey.CACHE_BASE_DIR))
            except OSError as exc:
                logger.error("Failed to apply cache base dir setting: %s", exc)

    def _on_copy_from_sd(self):
        from .copy_sd import launch_copy_sd

        launch_copy_sd(self)

    def on_open(self):
        """Open a folder using a file dialog."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Open Folder",
            self.root_folder or "",
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.ReadOnly,
        )
        if folder:
            self._load_folder(folder)

    def _load_folder(self, folder: str):
        """Load images from a folder and update the UI."""
        logger.info(f"Loading folder: {folder}")
        self._stop_folder_watcher()

        # Scan the folder
        images, source_folders = scan_folder(folder)
        logger.info(f"Found {len(images)} images in {len(source_folders)} folder(s)")

        # Save as last folder
        get_state().set(StateKey.LAST_FOLDER, folder)

        # Update state
        self.root_folder = folder
        self.source_folders = source_folders

        # Close old database connections and create new manager
        self.db_manager.close_all()

        # Reset progress tracking
        self.status_bar.reset()

        # Update photo model (replaces old _all_images_data and images_data)
        photos = [ImageItem(**data) for data in images]
        self.photo_model.set_photos(photos, source_folders)
        self._items_by_path = {item.path: item for item in self.photo_model.all_photos}

        # Update filter panel
        self.filter_panel.set_folders(source_folders)

        self.grid.set_data(self.photo_model.photos)

        # Update status bar
        self.status_bar.set_photo_count(len(self.photo_model.all_photos))

        # Start background loading (EXIF + thumbs)
        self.media_manager.reset_for_folder(
            [p.path for p in self.photo_model.all_photos],
            self.photo_model.source_folders,
        )
        if self._last_visible_paths:
            self.media_manager.update_visible(self._last_visible_paths)

        # Clear panels
        self.exif_panel.update_exif([])
        if self.edit_panel:
            self.edit_panel.update_for_selection([])

        self._start_folder_watcher()

    # --- Folder watching ---

    def _start_folder_watcher(self) -> None:
        if not self.root_folder:
            return

        self._stop_folder_watcher()

        watcher = FolderWatcher(self.root_folder, parent=self)
        watcher.changes_detected.connect(self._on_folder_changes)
        watcher.start()
        self._folder_watcher = watcher

    def _stop_folder_watcher(self) -> None:
        watcher = self._folder_watcher
        self._folder_watcher = None
        if watcher is None:
            return

        try:
            watcher.changes_detected.disconnect(self._on_folder_changes)
        except RuntimeError:
            pass

        watcher.stop(timeout_s=1.0)

    def _suppress_watcher_paths(
        self, paths: list[str], duration_s: float = 2.0
    ) -> None:
        expiry = time.monotonic() + max(0.0, float(duration_s))
        for path in paths:
            self._watcher_suppressed[path] = expiry

    def _on_folder_changes(self, changes: list[tuple[str, str]]) -> None:
        if not changes:
            return

        now = time.monotonic()
        self._watcher_suppressed = {
            path: until
            for path, until in self._watcher_suppressed.items()
            if until > now
        }

        added: set[str] = set()
        deleted: set[str] = set()
        modified: set[str] = set()

        for kind, path in changes:
            kind_lower = str(kind).lower()
            if path in self._watcher_suppressed:
                continue
            if "added" in kind_lower:
                added.add(path)
            elif "deleted" in kind_lower or "removed" in kind_lower:
                deleted.add(path)
            elif "modified" in kind_lower:
                modified.add(path)

        # Deletions first to handle renames (delete+add)
        for path in sorted(deleted):
            self.photo_model.remove_photo(path)

        for path in sorted(added):
            if not os.path.isfile(path):
                continue

            source_folder = os.path.dirname(path)
            try:
                created = datetime.fromtimestamp(os.path.getctime(path)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except OSError:
                created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            item = ImageItem(
                path=path,
                name=os.path.basename(path),
                created=created,
                source_folder=source_folder,
                state=0,
            )
            self.photo_model.add_photo(item)

        effective_modified = modified - added - deleted
        for path in sorted(effective_modified):
            item = self._items_by_path.get(path)
            if item is None:
                continue

            item.state = 0
            item.embedded_pixmap = None
            item.hq_pixmap = None
            item.pixmap = None
            self.media_manager.regenerate_thumbnails([path])
            self.grid.refresh_item(item._global_index)

    def on_regenerate_thumbnails(self):
        """Regenerate all thumbnails for currently loaded folders."""
        if not self.photo_model.all_photos:
            logger.warning("No folders loaded, nothing to regenerate")
            return

        items = list(self.photo_model.all_photos)
        logger.info(f"Regenerating thumbnails for {len(items)} photo(s)")
        self.media_manager.regenerate_thumbnails([p.path for p in items])

        # Reset all image states to trigger re-generation
        for item in items:
            item.state = 0
            item.embedded_pixmap = None
            item.hq_pixmap = None
            item.pixmap = None

        # Refresh the grid to trigger thumbnail requests
        self.grid.on_scroll(self.grid.scrollbar.value())

    def on_regenerate_exif(self):
        """Regenerate EXIF (editable + panel fields) for selected or all filtered."""
        selected = self.photo_model.get_selected_photos()
        items = selected if selected else list(self.images_data)
        if not items:
            return

        self.media_manager.regenerate_exif([p.path for p in items])

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

        dialog = SaveExifDialog(items, self.media_manager, self)
        dialog.exec()

    def on_thumb_ready(self, file_path, thumb_type, cache_path):
        item = self._items_by_path.get(file_path)
        if item is None:
            return
        if (
            get_runtime_setting(RuntimeSettingKey.GRID_LOWRES_ONLY)
            and thumb_type != "embedded"
        ):
            return

        state = 1 if thumb_type == "embedded" else 2

        item.state = max(int(getattr(item, "state", 0)), state)
        if thumb_type == "embedded":
            item.embedded_pixmap = None
        else:
            item.hq_pixmap = None
        item.pixmap = None
        self.grid.refresh_item(item._global_index)

    def on_selection_changed(self, selected_indices):
        # Mark selection as changed for undo tracking
        self._selection_changed_since_edit = True

        selected_items = [self.images_data[i] for i in selected_indices]

        # Load db_metadata for selected items if not already loaded
        for item in selected_items:
            if item.db_metadata is None:
                db = self.db_manager.get_db_for_image(item.path)
                item.db_metadata = db.get_metadata(item.path)

        # Update edit panel immediately (uses DB data)
        if self.edit_panel:
            self.edit_panel.update_for_selection(selected_items)

        # Load EXIF panel fields from DB or schedule extraction
        self.media_manager.ensure_panel_fields_loaded_from_db(
            [item.path for item in selected_items]
        )
        self.exif_panel.update_exif(selected_items)

    def request_thumb_handler(self, index):
        if 0 <= index < len(self.images_data):
            file_path = self.images_data[index].path
            self.media_manager.request_thumbnail(file_path)

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
                and get_user_setting(UserSettingKey.ON_FULLSCREEN_EXIT)
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
        item = next(
            (p for p in self.photo_model.all_photos if p.path == file_path),
            None,
        )
        if item is not None:
            self._items_by_path[file_path] = item
            self.media_manager.add_files([file_path])

        self.filter_panel.set_folders(self.photo_model.source_folders)
        self.grid.set_data(self.photo_model.photos)
        if index >= 0:
            self.grid._ensure_visible(index)
        self._update_status_bar_count()

    def _on_photo_removed(self, file_path: str, former_index: int):
        """Handle photo removed from model."""
        self._items_by_path.pop(file_path, None)
        self.media_manager.remove_files([file_path])
        self.filter_panel.set_folders(self.photo_model.source_folders)

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
        external_viewer = get_user_setting(UserSettingKey.EXTERNAL_VIEWER)
        if external_viewer:
            view_app_action = menu.addAction(
                f"View in {self._display_external_app_name(external_viewer)}"
            )
            view_app_action.triggered.connect(
                lambda: open_in_external_app(
                    external_viewer, [p.path for p in selected]
                )
            )

        # Edit in Application (only if configured)
        external_editor = get_user_setting(UserSettingKey.EXTERNAL_EDITOR)
        if external_editor:
            edit_app_action = menu.addAction(
                f"Edit in {self._display_external_app_name(external_editor)}"
            )
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

        # Regenerate EXIF action
        if len(selected) == 1:
            regen_exif_action = menu.addAction("Regenerate EXIF")
        else:
            regen_exif_action = menu.addAction(
                f"Regenerate EXIF ({len(selected)} photos)"
            )
        regen_exif_action.triggered.connect(
            lambda: self.media_manager.regenerate_exif([p.path for p in selected])
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
                self._suppress_watcher_paths([new_path])

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
                self._suppress_watcher_paths([photo.path])
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
        paths = [p.path for p in photos]
        for photo in photos:
            photo.state = 0
            photo.embedded_pixmap = None
            photo.hq_pixmap = None
            photo.pixmap = None
        self.media_manager.regenerate_thumbnails(paths)

        # Refresh the grid to show placeholders until new thumbs arrive
        self.grid.on_scroll(self.grid.scrollbar.value())

    @staticmethod
    def _display_external_app_name(app_path: str) -> str:
        base = os.path.basename(app_path.rstrip(os.sep))
        if base.lower().endswith(".app"):
            return base[:-4]
        return base or app_path

    def _edit_in_external_app(self, photos: list[ImageItem]):
        """Duplicate selected photos and open duplicates in external editor."""
        from .external_apps import open_in_external_app

        duplicated_paths = []
        for photo in photos:
            new_path = self._get_duplicate_path(photo.path)
            try:
                shutil.copy2(photo.path, new_path)
                self._suppress_watcher_paths([new_path])
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
            open_in_external_app(
                get_user_setting(UserSettingKey.EXTERNAL_EDITOR),
                duplicated_paths,
            )

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
        from .cache_paths import clear_thumb_cache_for_folders

        clear_thumb_cache_for_folders(self.photo_model.source_folders)

        # Reload the folder from scratch
        self._load_folder(self.root_folder)

    def closeEvent(self, event):
        # Save window and splitter state
        state = get_state()
        state.set(StateKey.WINDOW_GEOMETRY, self.saveGeometry())
        state.set(StateKey.WINDOW_STATE, self.saveState())
        state.set(StateKey.MAIN_SPLITTER, self._main_splitter.saveState())
        if self._right_splitter:
            state.set(StateKey.RIGHT_SPLITTER, self._right_splitter.saveState())

        # Stop background workers first to avoid noisy teardown.
        self._stop_folder_watcher()
        if hasattr(self, "media_manager"):
            self.media_manager.stop(
                timeout_s=float(
                    get_runtime_setting(RuntimeSettingKey.SHUTDOWN_TIMEOUT_S)
                )
            )
        if hasattr(self, "db_manager"):
            self.db_manager.close_all()
        super().closeEvent(event)
