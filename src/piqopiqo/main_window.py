"""Main window for the application."""

from __future__ import annotations

from datetime import datetime
from functools import partial
import logging
import os
import time

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import platform
from .background.media_man import MediaManager
from .cache_paths import set_cache_base_dir
from .components.status_bar import LoadingStatusBar
from .dialogs.error_list_dialog import ErrorListDialog
from .folder_scan import scan_folder
from .folder_watcher import FolderWatcher
from .fullscreen import FullscreenOverlay
from .grid.photo_grid import PhotoGrid
from .metadata.db_fields import DBFields
from .metadata.metadata_db import MetadataDBManager
from .metadata.save_workers import MetadataSaveWorker, drain_qthread_pool
from .model import (
    FilterCriteria,
    ImageItem,
    LabelUndoEntry,
    OnFullscreenExitMultipleSelected,
)
from .orientation import rotate_orientation_left, rotate_orientation_right
from .panels import EditPanel, ExifPanel, FilterPanel
from .photo_model import PhotoListModel, SortOrder
from .settings_panel import SettingsDialog
from .settings_state import (
    APP_NAME,
    RuntimeSettingKey,
    StateKey,
    UserSettingKey,
    get_effective_exif_panel_field_keys,
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
        self._filter_apply_scheduled = False
        self._pending_filter_criteria: FilterCriteria | None = None
        self._pending_filter_snapshot: dict | None = None

        self._items_by_path: dict[str, ImageItem] = {}
        self._last_visible_paths: list[str] = []
        self._model_refresh_scheduled = False
        self._pending_scheduled_sync_fields: set[str] = set()
        self._pending_model_sync_after_fullscreen = False
        self._pending_model_sync_fields: set[str] = set()
        self._fullscreen_started_with_multi_selection = False
        self._folder_watcher: FolderWatcher | None = None
        self._watcher_suppressed: dict[str, float] = {}
        self._active_apply_gpx_worker = None
        self._active_flickr_upload_manager = None
        self._shutdown_started = False

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
        self.filter_panel.interaction_finished.connect(
            self._schedule_grid_focus_restore
        )
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
            self.edit_panel.interaction_finished.connect(
                self._schedule_grid_focus_restore
            )
            self.edit_panel.metadata_saved.connect(self._on_edit_panel_metadata_saved)
            self._right_splitter.addWidget(self.edit_panel)

            self.exif_panel = ExifPanel()
            self.exif_panel.interaction_finished.connect(
                self._schedule_grid_focus_restore
            )
            self._right_splitter.addWidget(self.exif_panel)

            # Split evenly between edit and exif panels
            self._right_splitter.setSizes([200, 200])

            self._main_splitter.addWidget(self._right_splitter)
        else:
            self.edit_panel = None
            self.exif_panel = ExifPanel()
            self.exif_panel.interaction_finished.connect(
                self._schedule_grid_focus_restore
            )
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
        self._apply_saved_sort_order_for_load()
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
        self._grid_label_shortcut_objects: list[QShortcut] = []
        self._fullscreen_label_shortcut_objects: list[QShortcut] = []
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
        """Set up keyboard shortcuts from user settings."""
        self._clear_shortcut_bucket(self._shortcut_objects)
        self._clear_shortcut_bucket(self._grid_label_shortcut_objects)
        self._clear_shortcut_bucket(self._fullscreen_label_shortcut_objects)

        shortcuts = get_user_setting(UserSettingKey.SHORTCUTS)

        self._install_label_shortcuts(
            self.grid,
            self._grid_label_shortcut_objects,
            self._apply_label_to_grid_selection,
        )
        if self._fullscreen_overlay is not None:
            self._install_label_shortcuts(
                self._fullscreen_overlay,
                self._fullscreen_label_shortcut_objects,
                self._apply_label_to_fullscreen_current,
            )

        # Select All shortcut
        if Shortcut.SELECT_ALL in shortcuts:
            sc = QShortcut(
                parse_shortcut(shortcuts[Shortcut.SELECT_ALL]),
                self,
            )
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self._select_all_photos)
            self._shortcut_objects.append(sc)

    def _clear_shortcut_bucket(self, bucket: list[QShortcut]) -> None:
        for sc in bucket:
            try:
                sc.setParent(None)
                sc.deleteLater()
            except RuntimeError:
                # Parent widget may already be deleted (e.g. fullscreen overlay).
                pass
        bucket.clear()

    def _iter_label_shortcut_bindings(self) -> list[tuple[str, str | None]]:
        shortcuts = get_user_setting(UserSettingKey.SHORTCUTS)
        status_labels = get_user_setting(UserSettingKey.STATUS_LABELS)
        bindings: list[tuple[str, str | None]] = []

        for i in range(1, 10):
            shortcut_enum = Shortcut(f"LABEL_{i}")
            if shortcut_enum not in shortcuts:
                continue

            label_name = None
            for status_label in status_labels:
                if status_label.index == i:
                    label_name = status_label.name
                    break
            if label_name is None:
                continue

            bindings.append((shortcuts[shortcut_enum], label_name))

        if Shortcut.LABEL_NONE in shortcuts:
            bindings.append((shortcuts[Shortcut.LABEL_NONE], None))

        return bindings

    def _install_label_shortcuts(
        self,
        parent: QWidget,
        bucket: list[QShortcut],
        handler,
    ) -> None:
        for shortcut_str, label_name in self._iter_label_shortcut_bindings():
            sc = QShortcut(parse_shortcut(shortcut_str), parent)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(partial(handler, label_name))
            bucket.append(sc)

    def _select_all_photos(self):
        """Select all visible photos (after filtering)."""
        photos = self.photo_model.photos
        if not photos:
            return

        for photo in photos:
            photo.is_selected = True

        # Update grid's selection anchor to the last selected item
        self.grid._set_selection_anchor(len(photos) - 1)

        # Emit selection changed and refresh grid
        selected_indices = set(range(len(photos)))
        self.grid.selection_changed.emit(selected_indices)
        self.grid.on_scroll(self.grid.scrollbar.value())

    def _apply_label_to_grid_selection(self, label_name: str | None):
        """Apply a label to the current grid selection."""
        selected_items = self._get_selected_items()
        self._apply_label_to_items(
            selected_items,
            label_name,
            record_undo=True,
            sync_source="apply_label_shortcut_grid",
        )

    def _apply_label_to_fullscreen_current(self, label_name: str | None):
        """Apply a label to only the currently visible fullscreen image."""
        if self._fullscreen_overlay is None:
            return

        current_path = self._fullscreen_overlay.get_current_path()
        if current_path is None:
            return

        item = self._items_by_path.get(current_path)
        if item is None:
            return

        self._apply_label_to_items(
            [item],
            label_name,
            record_undo=False,
            sync_source="apply_label_shortcut_fullscreen",
        )

    def _apply_label(self, label_name: str | None):
        """Backward-compatible grid label shortcut handler."""
        self._apply_label_to_grid_selection(label_name)

    def _apply_label_to_items(
        self,
        selected_items: list[ImageItem],
        label_name: str | None,
        *,
        record_undo: bool,
        sync_source: str,
    ) -> None:
        """Apply a label to the given items and sync model/grid/fullscreen state."""
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

        if record_undo:
            # Create undo entry if selection changed since last edit
            if self._selection_changed_since_edit:
                self._label_undo_entry = LabelUndoEntry(
                    items=list(selected_items),
                    previous_labels=previous_labels,
                    new_labels={item.path: label_name for item in selected_items},
                )
                self._selection_changed_since_edit = False
            else:
                if self._label_undo_entry is not None:
                    self._label_undo_entry.new_labels = {
                        item.path: label_name for item in selected_items
                    }

            self._label_undo_is_redo = False
            self._undo_label_action.setText("Undo label")
            if self._fullscreen_overlay is None:
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

        self.sync_model_after_metadata_update(
            {DBFields.LABEL},
            source=sync_source,
            allow_fullscreen_filter=True,
        )

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
        if self._fullscreen_overlay is not None:
            return
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

        self.sync_model_after_metadata_update(
            {DBFields.LABEL},
            source="undo_redo_label",
            allow_fullscreen_filter=True,
        )

    def _on_edit_finished(self):
        """Edit panel completion hook (focus restore handled by interaction signals)."""

    def _schedule_grid_focus_restore(self) -> None:
        QTimer.singleShot(0, self._restore_grid_focus_after_panel_interaction)

    def _restore_grid_focus_after_panel_interaction(self) -> None:
        if self._fullscreen_overlay is not None:
            return
        if not self.isVisible():
            return
        self.grid.setFocus()

    def _on_edit_panel_metadata_saved(self, field_name: str):
        self.sync_model_after_metadata_update(
            {field_name},
            source="edit_panel",
        )

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
        if needs_resort:
            self._pending_scheduled_sync_fields.update(
                {
                    DBFields.TIME_TAKEN,
                    DBFields.TITLE,
                    DBFields.KEYWORDS,
                    DBFields.LABEL,
                }
            )
            if not self._model_refresh_scheduled:
                self._model_refresh_scheduled = True
                QTimer.singleShot(50, self._flush_scheduled_model_sync)

    def _flush_scheduled_model_sync(self):
        self._model_refresh_scheduled = False
        changed_fields = set(self._pending_scheduled_sync_fields)
        self._pending_scheduled_sync_fields.clear()
        if not changed_fields:
            return
        self.sync_model_after_metadata_update(
            changed_fields,
            source="editable_ready",
        )

    def sync_model_after_metadata_update(
        self,
        changed_fields: set[str],
        source: str,
        allow_fullscreen_filter: bool = False,
    ) -> None:
        fields = {str(field) for field in changed_fields if field}
        if not fields:
            return

        label_only = fields == {DBFields.LABEL}
        can_filter_in_fullscreen = (
            allow_fullscreen_filter
            and label_only
            and bool(get_user_setting(UserSettingKey.FILTER_IN_FULLSCREEN))
        )

        if self._fullscreen_overlay is not None and not can_filter_in_fullscreen:
            self._pending_model_sync_after_fullscreen = True
            self._pending_model_sync_fields.update(fields)
            logger.debug(
                "Deferring model sync during fullscreen (%s): %s",
                source,
                sorted(fields),
            )
            return

        self._execute_metadata_model_sync(
            fields,
            source=source,
            rebind_fullscreen_loop=can_filter_in_fullscreen,
        )

    def _execute_metadata_model_sync(
        self,
        changed_fields: set[str],
        *,
        source: str,
        rebind_fullscreen_loop: bool,
    ) -> None:
        old_loop_paths: list[str] = []
        old_current_path: str | None = None
        if rebind_fullscreen_loop and self._fullscreen_overlay is not None:
            old_loop_paths = self._fullscreen_overlay.get_visible_paths()
            old_current_path = self._fullscreen_overlay.get_current_path()

        logger.debug(
            "Refreshing model after metadata update from %s: %s",
            source,
            sorted(changed_fields),
        )
        self.photo_model.refresh_after_metadata_update()

        if rebind_fullscreen_loop:
            self._rebind_fullscreen_loop_after_model_sync(
                old_loop_paths,
                old_current_path,
            )

    def _pick_next_path_in_loop(
        self,
        loop_paths: list[str],
        valid_paths: set[str],
        current_path: str | None,
    ) -> str | None:
        if not loop_paths:
            return None
        if current_path not in loop_paths:
            for path in loop_paths:
                if path in valid_paths:
                    return path
            return None

        start = loop_paths.index(current_path)
        for offset in range(1, len(loop_paths) + 1):
            path = loop_paths[(start + offset) % len(loop_paths)]
            if path in valid_paths:
                return path
        return None

    def _rebind_fullscreen_loop_after_model_sync(
        self,
        old_loop_paths: list[str],
        old_current_path: str | None,
    ) -> None:
        overlay = self._fullscreen_overlay
        if overlay is None:
            return

        valid_paths = {item.path for item in self.images_data}
        surviving_paths = [path for path in old_loop_paths if path in valid_paths]
        if not surviving_paths:
            overlay.close()
            return

        preferred_path = old_current_path
        if preferred_path not in valid_paths:
            preferred_path = self._pick_next_path_in_loop(
                old_loop_paths,
                set(surviving_paths),
                old_current_path,
            )

        overlay.all_items = self.images_data
        if not overlay.rebind_to_paths(surviving_paths, preferred_path=preferred_path):
            overlay.close()

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
        return self.db_manager.ensure_items_metadata_ready(items)

    def _capture_grid_viewport_snapshot(self) -> dict:
        return {
            "photo_list_paths": [item.path for item in self.images_data],
            "visible_paths": self.grid.get_viewport_visible_paths(),
            "selected_visible_paths": self.grid.get_viewport_selected_paths(),
        }

    def _ensure_grid_path_visible(self, path: str | None) -> bool:
        if not path:
            return False
        index = self.grid.get_index_for_path(path)
        if index is None:
            return False
        self.grid._ensure_visible(index)
        return True

    def _pick_filter_fallback_target_path(
        self,
        previous_visible_paths: list[str],
        old_photo_list_paths: list[str],
        new_photo_list_paths: list[str],
    ) -> str | None:
        """Pick a fallback target near the previous viewport when filter removes it."""
        if not previous_visible_paths or not new_photo_list_paths:
            return None

        old_index_by_path = {path: i for i, path in enumerate(old_photo_list_paths)}
        previous_indices = [
            old_index_by_path[path]
            for path in previous_visible_paths
            if path in old_index_by_path
        ]
        if not previous_indices:
            return None

        best_path = None
        best_distance = None
        best_old_index = None
        for path in new_photo_list_paths:
            old_index = old_index_by_path.get(path)
            if old_index is None:
                continue
            distance = min(abs(old_index - prev_idx) for prev_idx in previous_indices)
            if (
                best_distance is None
                or distance < best_distance
                or (distance == best_distance and old_index < best_old_index)
            ):
                best_path = path
                best_distance = distance
                best_old_index = old_index
        return best_path

    def _restore_grid_viewport_after_sort_change(self, snapshot: dict) -> None:
        target_path = None
        for path in snapshot["selected_visible_paths"]:
            target_path = path
            break
        if target_path is None:
            for path in snapshot["visible_paths"]:
                target_path = path
                break
        self._ensure_grid_path_visible(target_path)

    def _restore_grid_viewport_after_filter_change(self, snapshot: dict) -> None:
        new_photo_list_paths = [item.path for item in self.images_data]
        new_path_set = set(new_photo_list_paths)

        target_path = next(
            (
                path
                for path in snapshot["selected_visible_paths"]
                if path in new_path_set
            ),
            None,
        )
        if target_path is None:
            target_path = next(
                (path for path in snapshot["visible_paths"] if path in new_path_set),
                None,
            )
        if target_path is None:
            target_path = self._pick_filter_fallback_target_path(
                snapshot["visible_paths"],
                snapshot["photo_list_paths"],
                new_photo_list_paths,
            )
        self._ensure_grid_path_visible(target_path)

    def select_paths_in_grid(
        self,
        paths: list[str],
        *,
        anchor_path: str | None = None,
        reveal_path: str | None = None,
    ) -> None:
        if not self.images_data:
            self.grid.select_paths([], anchor_path=None)
            return

        current_paths = {item.path for item in self.images_data}
        visible_paths = [path for path in paths if path in current_paths]
        self.grid.select_paths(visible_paths, anchor_path=anchor_path)
        target_reveal = reveal_path or anchor_path
        if target_reveal is None and visible_paths:
            target_reveal = visible_paths[0]
        self._ensure_grid_path_visible(target_reveal)

    def _on_filter_changed(self, criteria: FilterCriteria):
        """Handle filter change.

        Args:
            criteria: Filter criteria to apply.
        """
        snapshot = self._capture_grid_viewport_snapshot()
        self._current_filter = criteria
        self._pending_filter_criteria = criteria
        self._pending_filter_snapshot = snapshot
        if self._filter_apply_scheduled:
            return
        self._filter_apply_scheduled = True
        QTimer.singleShot(0, self._apply_pending_filter_change)

    def _apply_pending_filter_change(self) -> None:
        self._filter_apply_scheduled = False
        criteria = self._pending_filter_criteria
        snapshot = self._pending_filter_snapshot
        self._pending_filter_criteria = None
        self._pending_filter_snapshot = None
        if criteria is None or snapshot is None:
            return
        started = time.perf_counter()
        total_before = len(self.photo_model.all_photos)

        self.photo_model.set_filter(criteria)
        after_filter = time.perf_counter()

        self._restore_grid_viewport_after_filter_change(snapshot)
        after_restore = time.perf_counter()

        logger.debug(
            "Deferred filter apply completed: "
            "folder=%r labels=%s include_no_label=%s search=%r "
            "result=%d/%d model=%.1fms restore=%.1fms total=%.1fms",
            criteria.folder,
            sorted(criteria.labels),
            criteria.include_no_label,
            criteria.search_text,
            len(self.photo_model.photos),
            total_before,
            (after_filter - started) * 1000.0,
            (after_restore - after_filter) * 1000.0,
            (after_restore - started) * 1000.0,
        )

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

        settings_label = "Preferences..."
        settings_action = QAction(settings_label, self)
        settings_action.triggered.connect(self.on_settings)
        # On macOS, Qt relocates this from File to the standard app menu.
        settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        settings_action.setShortcut(QKeySequence.Preferences)
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

        edit_menu.addSeparator()

        regenerate_exif_action = QAction("Reload EXIF", self)
        regenerate_exif_action.triggered.connect(self.on_reload_exif)
        edit_menu.addAction(regenerate_exif_action)

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

        regenerate_action = QAction("Regenerate Thumbnails", self)
        regenerate_action.triggered.connect(self.on_regenerate_thumbnails)
        view_menu.addAction(regenerate_action)

        # Tools menu
        tools_menu = menubar.addMenu("Tools")

        copy_sd_action = QAction("Copy from SD...", self)
        copy_sd_action.triggered.connect(self._on_copy_from_sd)
        tools_menu.addAction(copy_sd_action)

        tools_menu.addSeparator()

        apply_gpx_action = QAction("Apply GPX...", self)
        apply_gpx_action.triggered.connect(self._on_apply_gpx)
        tools_menu.addAction(apply_gpx_action)

        tools_menu.addSeparator()

        upload_flickr_action = QAction("Upload to Flickr...", self)
        upload_flickr_action.triggered.connect(self._on_upload_to_flickr)
        tools_menu.addAction(upload_flickr_action)

        tools_menu.addSeparator()

        save_exif_action = QAction("Save EXIF...", self)
        save_exif_action.triggered.connect(self._on_save_exif)
        tools_menu.addAction(save_exif_action)

        help_menu = menubar.addMenu("Help")
        about_action = QAction(f"About {APP_NAME}", self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self.on_about)
        help_menu.addAction(about_action)

    def on_about(self):
        pass

    def on_settings(self):
        self.open_settings()

    def open_settings(self, tab_title: str | None = None) -> None:
        dialog = SettingsDialog(self, initial_tab_title=tab_title)
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

        if UserSettingKey.CUSTOM_EXIF_FIELDS in changed_keys:
            self.media_manager.refresh_exif_field_keys(
                get_effective_exif_panel_field_keys()
            )
            self.exif_panel.refresh_fields()
            for item in self._items_by_path.values():
                item.exif_data = None
            self._reconcile_selection_and_panels()

        if UserSettingKey.STATUS_LABELS in changed_keys:
            self.filter_panel.reload_status_labels()
            self.grid.on_scroll(self.grid.scrollbar.value())
            if self._fullscreen_overlay is not None:
                self._fullscreen_overlay._update_color_swatch()
                self._fullscreen_overlay.update()

        if (
            UserSettingKey.SHOW_DESCRIPTION_FIELD in changed_keys
            and self.edit_panel is not None
        ):
            self.edit_panel.set_description_field_visible(
                bool(get_user_setting(UserSettingKey.SHOW_DESCRIPTION_FIELD))
            )

        if (
            UserSettingKey.SHORTCUTS in changed_keys
            or UserSettingKey.STATUS_LABELS in changed_keys
        ):
            self._setup_shortcuts()

        if UserSettingKey.CACHE_BASE_DIR in changed_keys:
            try:
                set_cache_base_dir(get_user_setting(UserSettingKey.CACHE_BASE_DIR))
            except OSError as exc:
                logger.error("Failed to apply cache base dir setting: %s", exc)

    def _on_copy_from_sd(self):
        from .tools.copy_sd import launch_copy_sd

        launch_copy_sd(self)

    def _on_apply_gpx(self):
        from .tools.gpx2exif.actions import launch_apply_gpx

        launch_apply_gpx(self)

    def _on_upload_to_flickr(self):
        manager = self._active_flickr_upload_manager
        if manager is not None and manager.is_running():
            QMessageBox.information(
                self,
                "Upload to Flickr",
                "A Flickr upload operation is already running.",
            )
            return

        from .tools.flickr_upload import launch_flickr_upload

        launch_flickr_upload(self)

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
        self._apply_saved_sort_order_for_load()
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

    def on_reload_exif(self):
        """Reload EXIF (editable + panel fields) for selected or all filtered."""
        selected = self.photo_model.get_selected_photos()
        items = selected if selected else list(self.images_data)
        if not items:
            return

        self.media_manager.reload_exif([p.path for p in items])

    def _on_save_exif(self):
        from .tools.save_exif import launch_save_exif

        launch_save_exif(self)

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

        selected_items = [
            self.images_data[i]
            for i in selected_indices
            if 0 <= i < len(self.images_data)
        ]

        # Load db_metadata for selected items if not already loaded
        for item in selected_items:
            if item.db_metadata is None:
                db = self.db_manager.get_db_for_image(item.path)
                item.db_metadata = db.get_metadata(item.path)

        self._update_panels_for_selection(selected_items)

    def _update_panels_for_selection(self, items: list[ImageItem]) -> None:
        if self.edit_panel:
            self.edit_panel.update_for_selection(items)

        self.media_manager.ensure_panel_fields_loaded_from_db(
            [item.path for item in items]
        )
        self.exif_panel.update_exif(items)

    def _reconcile_selection_and_panels(self) -> None:
        selected_items = self.photo_model.get_selected_photos()
        self._selection_changed_since_edit = True
        self._update_panels_for_selection(selected_items)

    def request_thumb_handler(self, index):
        if 0 <= index < len(self.images_data):
            file_path = self.images_data[index].path
            self.media_manager.request_thumbnail(file_path)

    def _refresh_undo_label_action_enabled_for_context(self) -> None:
        if not hasattr(self, "_undo_label_action"):
            return
        self._undo_label_action.setEnabled(
            self._fullscreen_overlay is None and self._label_undo_entry is not None
        )

    def _capture_fullscreen_exit_snapshot(self, overlay: FullscreenOverlay) -> dict:
        return {
            "current_path": overlay.get_current_path(),
            "loop_paths": overlay.get_visible_paths(),
            "all_paths": overlay.get_all_paths(),
            "started_with_multi_selection": (
                self._fullscreen_started_with_multi_selection
            ),
        }

    def _clear_grid_selection(self) -> None:
        self.grid.select_paths([], anchor_path=None)

    def _restore_grid_after_fullscreen_exit(self, snapshot: dict | None) -> None:
        if snapshot is None:
            return

        current_photo_list_paths = [item.path for item in self.images_data]
        current_path_set = set(current_photo_list_paths)
        if not current_photo_list_paths:
            self._clear_grid_selection()
            return

        current_path = snapshot.get("current_path")
        loop_paths = [
            path
            for path in snapshot.get("loop_paths", [])
            if isinstance(path, str) and path
        ]
        all_paths = [
            path
            for path in snapshot.get("all_paths", [])
            if isinstance(path, str) and path
        ]
        started_with_multi = bool(snapshot.get("started_with_multi_selection"))

        if not started_with_multi:
            target_path = (
                current_path
                if current_path in current_path_set
                else self._pick_next_path_in_loop(
                    all_paths,
                    current_path_set,
                    current_path,
                )
            )
            if target_path is None:
                self._clear_grid_selection()
                return
            self.select_paths_in_grid(
                [target_path],
                anchor_path=target_path,
                reveal_path=target_path,
            )
            return

        surviving_loop_paths = [path for path in loop_paths if path in current_path_set]

        if current_path in current_path_set:
            target_path = current_path
        else:
            target_path = self._pick_next_path_in_loop(
                loop_paths,
                set(surviving_loop_paths),
                current_path,
            )

        if target_path is None:
            target_path = self._pick_next_path_in_loop(
                all_paths,
                current_path_set,
                current_path,
            )
            if target_path is None:
                self._clear_grid_selection()
                return
            self.select_paths_in_grid(
                [target_path],
                anchor_path=target_path,
                reveal_path=target_path,
            )
            return

        if (
            get_user_setting(UserSettingKey.ON_FULLSCREEN_EXIT_SELECTION_MODE)
            == OnFullscreenExitMultipleSelected.KEEP_SELECTION
        ):
            selection_paths = surviving_loop_paths
        else:
            selection_paths = [target_path]

        self.select_paths_in_grid(
            selection_paths,
            anchor_path=target_path,
            reveal_path=target_path,
        )

    def _handle_fullscreen_overlay(self, selected_indices: list):
        """Display the selected image in a fullscreen overlay."""
        if not selected_indices:
            return

        # Close any existing overlay first
        if self._fullscreen_overlay is not None:
            self._fullscreen_overlay.close()
            self._fullscreen_overlay = None
            self._fullscreen_started_with_multi_selection = False

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

        self._fullscreen_started_with_multi_selection = len(selected_indices) > 1
        if self._fullscreen_started_with_multi_selection:
            visible_indices = selected_indices
        else:
            visible_indices = list(range(len(self.images_data)))

        self._fullscreen_overlay = FullscreenOverlay(
            self.images_data, visible_indices, start_index
        )
        overlay_ref = self._fullscreen_overlay
        self._setup_shortcuts()
        self._refresh_undo_label_action_enabled_for_context()

        overlay_ref.index_changed.connect(self._on_fullscreen_index_changed)

        # Handle cleanup and selection logic on close
        def on_fullscreen_close():
            if self._fullscreen_overlay is not overlay_ref:
                return

            exit_snapshot = self._capture_fullscreen_exit_snapshot(overlay_ref)

            self._fullscreen_overlay = None
            self._fullscreen_started_with_multi_selection = False
            self._setup_shortcuts()
            self._refresh_undo_label_action_enabled_for_context()

            if self._pending_model_sync_after_fullscreen:
                pending_fields = set(self._pending_model_sync_fields)
                self._pending_model_sync_after_fullscreen = False
                self._pending_model_sync_fields.clear()
                if pending_fields:
                    self._execute_metadata_model_sync(
                        pending_fields,
                        source="fullscreen_exit_deferred",
                        rebind_fullscreen_loop=False,
                    )

            self._restore_grid_after_fullscreen_exit(exit_snapshot)
            self.grid.setFocus()

        overlay_ref.destroyed.connect(on_fullscreen_close)
        overlay_ref.show_on_screen(current_screen)

    def _on_fullscreen_index_changed(self, new_index: int):
        """Update grid selection when navigating in fullscreen mode."""
        if self._fullscreen_overlay and self._fullscreen_started_with_multi_selection:
            # In multi-selection mode, just update the last selected index
            self.grid._set_selection_anchor(new_index)
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
        self._update_status_bar_count()
        self._reconcile_selection_and_panels()

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
        self._reconcile_selection_and_panels()

    def _on_photo_removed(self, file_path: str, _former_index: int):
        """Handle photo removed from model."""
        self._items_by_path.pop(file_path, None)
        self.media_manager.remove_files([file_path])
        self.filter_panel.set_folders(self.photo_model.source_folders)

        self.grid.set_data(self.photo_model.photos)
        self._update_status_bar_count()
        self._reconcile_selection_and_panels()

    def _update_status_bar_count(self):
        """Update status bar photo count."""
        total = len(self.photo_model.all_photos)
        filtered = len(self.photo_model.photos)
        if total == filtered:
            self.status_bar.set_photo_count(total)
        else:
            self.status_bar.set_photo_count(total, filtered)

    # --- Sort order ---

    def _read_saved_sort_order(self) -> SortOrder:
        raw = get_state().get(StateKey.SORT_ORDER)
        if isinstance(raw, str):
            try:
                return SortOrder[raw]
            except KeyError:
                logger.warning(
                    "Invalid persisted sort order %r; fallback to FILE_NAME",
                    raw,
                )
        return SortOrder.FILE_NAME

    def _set_sort_menu_checked(self, order: SortOrder) -> None:
        action = self._sort_actions.get(order)
        if action is not None and not action.isChecked():
            action.setChecked(True)

    def _apply_saved_sort_order_for_load(self) -> None:
        order = self._read_saved_sort_order()
        self.photo_model.set_sort_order(order, emit_signals=False)
        self._set_sort_menu_checked(order)

    def _set_sort_order(self, order: SortOrder):
        """Set the sort order via menu."""
        if self.photo_model.sort_order == order:
            return
        snapshot = self._capture_grid_viewport_snapshot()
        self.photo_model.set_sort_order(order)
        self._restore_grid_viewport_after_sort_change(snapshot)
        self._set_sort_menu_checked(order)
        get_state().set(StateKey.SORT_ORDER, order.name)

    # --- Context menu ---

    def _show_context_menu(self, global_index: int, pos):
        from .grid.context_menu import show_context_menu

        show_context_menu(self, global_index, pos)

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

        super().closeEvent(event)

    def shutdown_for_quit(self) -> None:
        """Run app teardown after the window closes, before process exit."""
        if self._shutdown_started:
            return
        self._shutdown_started = True

        timeout_s = float(get_runtime_setting(RuntimeSettingKey.SHUTDOWN_TIMEOUT_S))
        timeout_ms = int(max(0.0, timeout_s) * 1000)

        label_pool_completed = drain_qthread_pool(
            self._label_save_pool,
            timeout_ms,
            clear_queued=True,
        )
        if not label_pool_completed:
            logger.warning(
                "Timed out waiting for label metadata saves to finish on shutdown"
            )

        if self.edit_panel is not None:
            self.edit_panel.shutdown_background_saves(
                timeout_ms,
                clear_queued=True,
            )

        self._stop_folder_watcher()
        if self._active_flickr_upload_manager is not None:
            self._active_flickr_upload_manager.stop(timeout_s=timeout_s)
            self._active_flickr_upload_manager = None
        if hasattr(self, "media_manager"):
            self.media_manager.stop(timeout_s=timeout_s)
        if hasattr(self, "db_manager"):
            self.db_manager.close_all()
