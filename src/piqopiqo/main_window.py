"""Main window for the application."""

from __future__ import annotations

from datetime import datetime
import logging
import os
import time

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import __version__ as piqopiqo_version
from . import platform
from .background.media_man import MediaManager
from .cache_paths import get_folder_cache_id, set_cache_base_dir
from .color_management import refresh_main_screen_color_space_cache
from .components.status_bar import LoadingStatusBar
from .components.column_number_selector import ColumnNumberSelector
from .dialogs.error_list_dialog import ErrorListDialog
from .dialogs.workspace_properties_dialog import (
    WorkspaceFolderSummary,
    WorkspacePropertiesDialog,
)
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
from .ssf.settings_state import (
    APP_NAME,
    RuntimeSettingKey,
    StateKey,
    UserSettingKey,
    get_effective_exif_panel_field_keys,
    get_runtime_setting,
    get_state,
    get_user_setting,
    set_user_setting,
)

logger = logging.getLogger(__name__)

LARGE_SELECTION_PANEL_DEFER_THRESHOLD = 200
SELECTION_PANEL_DEBOUNCE_MS = 120


class _WorkspaceCleanupWorkerSignals(QObject):
    finished = Signal(object)  # error string or None


class _WorkspaceCleanupWorker(QRunnable):
    def __init__(
        self,
        source_folders: list[str],
        *,
        clear_thumb_cache: bool,
        clear_metadata: bool,
    ) -> None:
        super().__init__()
        self._source_folders = list(source_folders)
        self._clear_thumb_cache = bool(clear_thumb_cache)
        self._clear_metadata = bool(clear_metadata)
        self.signals = _WorkspaceCleanupWorkerSignals()

    def run(self) -> None:
        error_message = None
        try:
            from .cache_paths import (
                clear_metadata_cache_for_folders,
                clear_thumb_cache_for_folders,
            )

            if self._clear_metadata:
                clear_metadata_cache_for_folders(self._source_folders)
            if self._clear_thumb_cache:
                clear_thumb_cache_for_folders(self._source_folders)
        except Exception as exc:
            logger.exception("Workspace cleanup failed")
            error_message = str(exc)

        self.signals.finished.emit(error_message)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, images, source_folders, root_folder):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        refresh_main_screen_color_space_cache()

        self._fullscreen_overlay = None
        self.root_folder = root_folder
        self.source_folders = source_folders
        self._current_filter: FilterCriteria | None = None  # Current filter criteria
        self._filter_apply_scheduled = False
        self._pending_filter_criteria: FilterCriteria | None = None
        self._pending_filter_snapshot: dict | None = None
        self._next_model_change_fast_first_paint = False
        self._last_model_change_grid_ms: float | None = None

        self._items_by_path: dict[str, ImageItem] = {}
        self._last_visible_paths: list[str] = []
        self._model_refresh_scheduled = False
        self._pending_scheduled_sync_fields: set[str] = set()
        self._pending_model_sync_after_fullscreen = False
        self._pending_model_sync_fields: set[str] = set()
        self._pending_metadata_reselection_context: dict | None = None
        self._fullscreen_started_with_multi_selection = False
        self._folder_watcher: FolderWatcher | None = None
        self._watcher_suppressed: dict[str, float] = {}
        self._active_apply_gpx_worker = None
        self._active_flickr_upload_manager = None
        self._active_flickr_metadata_precheck_worker = None
        self._shutdown_started = False
        self._selected_paths_cache: set[str] = set()
        self._selected_count_cache = 0
        self._selection_panel_refresh_serial = 0
        self._selection_panel_refresh_scheduled_serial: int | None = None
        self._selection_panel_refresh_in_progress = False
        self._selection_panel_refresh_timer = QTimer(self)
        self._selection_panel_refresh_timer.setSingleShot(True)
        self._selection_panel_refresh_timer.timeout.connect(
            self._flush_deferred_selection_panel_refresh
        )
        self._fullscreen_menu_managed_actions: list[QAction] = []
        self._fullscreen_menu_allowed_actions: set[QAction] = set()
        self._fullscreen_menu_action_restore_state: dict[QAction, bool] = {}
        self._fullscreen_menu_policy_active = False
        self._right_sidebar_collapsed = False
        self._right_sidebar_restore_size: int | None = None
        self._workspace_cleanup_running = False
        self._workspace_cleanup_context: dict | None = None
        self._workspace_cleanup_worker: _WorkspaceCleanupWorker | None = None

        # Create metadata database manager
        self.db_manager = MetadataDBManager()
        self._workspace_cleanup_pool = QThreadPool(self)
        self._workspace_cleanup_pool.setMaxThreadCount(1)

        self._create_menu_bar()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self._grid_view_shortcut_scope = central_widget
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
        self.grid.set_grid_view_shortcut_scope(self._grid_view_shortcut_scope)
        self._main_splitter.addWidget(self.grid)

        # Right side: panels + fixed-height column selector footer.
        self._right_sidebar_container = QWidget()
        self._right_sidebar_container.setMinimumWidth(0)
        right_sidebar_layout = QVBoxLayout(self._right_sidebar_container)
        right_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        right_sidebar_layout.setSpacing(0)

        # Right side panels: vertical splitter with edit panel and EXIF panel
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
            right_panels_widget = self._right_splitter
        else:
            self.edit_panel = None
            self.exif_panel = ExifPanel()
            self.exif_panel.interaction_finished.connect(
                self._schedule_grid_focus_restore
            )
            right_panels_widget = self.exif_panel

        right_sidebar_layout.addWidget(right_panels_widget, 1)

        self.column_selector_row = QWidget(self._right_sidebar_container)
        self.column_selector_row.setObjectName("column_selector_row")
        self.column_selector_row.setFixedHeight(30)
        self.column_selector_row.setMinimumWidth(0)
        selector_row_layout = QHBoxLayout(self.column_selector_row)
        selector_row_layout.setContentsMargins(
            max(0, int(get_runtime_setting(RuntimeSettingKey.STATUS_BAR_SIDE_PADDING))),
            4,
            0,
            4,
        )
        selector_row_layout.setSpacing(0)
        self.column_selector = ColumnNumberSelector(self.column_selector_row)
        self.column_selector.decrement_requested.connect(
            self._on_column_selector_decrement
        )
        self.column_selector.increment_requested.connect(
            self._on_column_selector_increment
        )
        selector_row_layout.addWidget(
            self.column_selector,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        selector_row_layout.addStretch(1)
        right_sidebar_layout.addWidget(self.column_selector_row, 0)

        self._main_splitter.addWidget(self._right_sidebar_container)
        self._main_splitter.setCollapsible(1, True)
        self._main_splitter.splitterMoved.connect(self._on_main_splitter_moved)

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
        self.status_bar.error_btn.clicked.connect(self._show_error_dialog)
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
        self.grid.label_shortcut_requested.connect(self._apply_label_to_grid_selection)
        self.grid.filter_label_shortcut_requested.connect(
            self._on_filter_label_shortcut_requested
        )
        self.grid.folder_filter_cycle_requested.connect(
            self._on_folder_filter_cycle_shortcut_requested
        )
        self.grid.folder_filter_all_requested.connect(
            self._on_folder_filter_all_shortcut_requested
        )
        self.grid.clear_filter_shortcut_requested.connect(
            self._on_clear_filter_shortcut_requested
        )
        self.grid.focus_filter_search_shortcut_requested.connect(
            self._on_focus_filter_search_shortcut_requested
        )
        self.grid.toggle_sidebar_shortcut_requested.connect(
            self._toggle_right_sidebar_collapsed
        )

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

        self._apply_grid_num_columns(
            get_user_setting(UserSettingKey.NUM_COLUMNS),
            persist=False,
        )
        self.grid.set_data(self.photo_model.photos)

        # Update status bar
        self._update_status_bar_count()

        # Start background loading (EXIF + thumbs)
        self.media_manager.reset_for_folder(
            [p.path for p in self.photo_model.all_photos],
            self.photo_model.source_folders,
        )
        if self._last_visible_paths:
            self.media_manager.update_visible(self._last_visible_paths)

        self._background_db_save_pool = QThreadPool()

        # Set up keyboard shortcuts
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
        """Refresh view-owned shortcuts from user settings."""
        self.grid.refresh_shortcuts()
        if self._fullscreen_overlay is not None:
            self._fullscreen_overlay.refresh_shortcuts()

    def _apply_label_to_grid_selection(self, label_name: str | None):
        """Apply a label to the current grid selection."""
        selected_items = self._get_selected_items()
        self._apply_label_to_items(
            selected_items,
            label_name,
            record_undo=True,
            sync_source="apply_label_shortcut_grid",
        )

    def _on_filter_label_shortcut_requested(self, label_name: str | None) -> None:
        if self._fullscreen_overlay is not None:
            return
        self.filter_panel.toggle_label_filter(label_name)

    def _on_folder_filter_cycle_shortcut_requested(self, step: int) -> None:
        if self._fullscreen_overlay is not None:
            return
        self.filter_panel.cycle_folder_filter(step)

    def _on_folder_filter_all_shortcut_requested(self) -> None:
        if self._fullscreen_overlay is not None:
            return
        self.filter_panel.set_all_folders()

    def _on_clear_filter_shortcut_requested(self) -> None:
        if self._fullscreen_overlay is not None:
            return
        self.filter_panel.clear_filter()

    def _on_focus_filter_search_shortcut_requested(self) -> None:
        if self._fullscreen_overlay is not None:
            return
        self.filter_panel.focus_search_field(select_all=True)

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
            self._background_db_save_pool.start(worker)

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
            self._background_db_save_pool.start(worker)

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
                self._background_db_save_pool.start(worker)

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

    def _set_selected_cache_from_items(self, items: list[ImageItem]) -> None:
        self._selected_paths_cache = {item.path for item in items}
        self._selected_count_cache = len(items)

    def _set_selected_cache_from_indices(self, selected_indices) -> int:
        selected_paths: set[str] = set()
        for index in selected_indices:
            if 0 <= index < len(self.images_data):
                selected_paths.add(self.images_data[index].path)
        self._selected_paths_cache = selected_paths
        self._selected_count_cache = len(selected_paths)
        return self._selected_count_cache

    def _cancel_deferred_selection_panel_refresh(self) -> None:
        self._selection_panel_refresh_scheduled_serial = None
        if self._selection_panel_refresh_timer.isActive():
            self._selection_panel_refresh_timer.stop()

    def _show_selection_panels_pending(self, count: int) -> None:
        if self.edit_panel:
            self.edit_panel.show_selection_pending(count)
        self.exif_panel.show_selection_pending(count)

    def _clear_selection_panels_pending(self) -> None:
        if self.edit_panel:
            self.edit_panel.clear_selection_pending()
        self.exif_panel.clear_selection_pending()

    def _schedule_deferred_selection_panel_refresh(self) -> None:
        self._selection_panel_refresh_serial += 1
        self._selection_panel_refresh_scheduled_serial = (
            self._selection_panel_refresh_serial
        )
        self._selection_panel_refresh_timer.start(SELECTION_PANEL_DEBOUNCE_MS)

    def _flush_deferred_selection_panel_refresh(self) -> None:
        if self._selection_panel_refresh_scheduled_serial is None:
            return
        self._selection_panel_refresh_scheduled_serial = None
        selected_items = self.photo_model.get_selected_photos()
        self._set_selected_cache_from_items(selected_items)
        self._update_panels_for_selection(selected_items)

    def _should_defer_selection_panel_refresh(
        self,
        selected_count: int | None = None,
        *,
        include_active_timer: bool = True,
    ) -> bool:
        count = (
            self._selected_count_cache
            if selected_count is None
            else int(selected_count)
        )
        if count > LARGE_SELECTION_PANEL_DEFER_THRESHOLD:
            return True
        return include_active_timer and self._selection_panel_refresh_timer.isActive()

    def _apply_or_defer_panel_refresh(
        self,
        *,
        selected_items: list[ImageItem] | None = None,
        selected_count: int | None = None,
        coalesce_with_active_timer: bool = False,
    ) -> None:
        count = len(selected_items) if selected_items is not None else selected_count
        if count is None:
            count = self._selected_count_cache

        if count <= 0:
            self._cancel_deferred_selection_panel_refresh()
            self._update_panels_for_selection([])
            return

        if self._should_defer_selection_panel_refresh(
            count,
            include_active_timer=coalesce_with_active_timer,
        ):
            self._show_selection_panels_pending(int(count))
            self._schedule_deferred_selection_panel_refresh()
            return

        self._cancel_deferred_selection_panel_refresh()
        if selected_items is None:
            selected_items = self._get_selected_items()
        self._update_panels_for_selection(selected_items)

    def _on_editable_ready(self, file_path: str, metadata: dict):
        item = self._items_by_path.get(file_path)
        if item is None:
            return

        item.db_metadata = metadata
        self.grid.refresh_item(item._global_index)

        if self.edit_panel and file_path in self._selected_paths_cache:
            if self._should_defer_selection_panel_refresh():
                self._show_selection_panels_pending(self._selected_count_cache)
                self._schedule_deferred_selection_panel_refresh()
            else:
                selected_items = self._get_selected_items()
                if selected_items:
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

        self._pending_metadata_reselection_context = (
            self._capture_metadata_reselection_context()
        )

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

    def _capture_metadata_reselection_context(self) -> dict | None:
        old_photo_list_paths = [item.path for item in self.images_data]
        if not old_photo_list_paths:
            return None

        selected_paths = [item.path for item in self.images_data if item.is_selected]
        if not selected_paths:
            return None

        anchor_index = self.grid._choose_anchor_from_current_selection()
        base_path = None
        if 0 <= anchor_index < len(old_photo_list_paths):
            candidate = old_photo_list_paths[anchor_index]
            if candidate in selected_paths:
                base_path = candidate
        if base_path is None:
            base_path = selected_paths[-1]

        return {
            "old_photo_list_paths": old_photo_list_paths,
            "selected_paths": selected_paths,
            "base_path": base_path,
        }

    @staticmethod
    def _pick_metadata_reselection_path(
        old_photo_list_paths: list[str],
        new_photo_list_paths: list[str],
        base_path: str | None,
    ) -> str | None:
        if not old_photo_list_paths or not new_photo_list_paths:
            return None
        if base_path not in old_photo_list_paths:
            return None

        valid_paths = set(new_photo_list_paths)
        base_index = old_photo_list_paths.index(base_path)

        for i in range(base_index + 1, len(old_photo_list_paths)):
            path = old_photo_list_paths[i]
            if path in valid_paths:
                return path

        for i in range(base_index - 1, -1, -1):
            path = old_photo_list_paths[i]
            if path in valid_paths:
                return path

        return None

    def _apply_pending_metadata_reselection(self, context: dict) -> None:
        selected_before = context.get("selected_paths")
        if not isinstance(selected_before, list) or not selected_before:
            return

        current_selected_paths = [
            item.path for item in self.images_data if item.is_selected
        ]
        if current_selected_paths:
            return

        old_photo_list_paths = context.get("old_photo_list_paths")
        base_path = context.get("base_path")
        if not isinstance(old_photo_list_paths, list):
            return
        if not isinstance(base_path, str) or not base_path:
            return

        replacement_path = self._pick_metadata_reselection_path(
            old_photo_list_paths,
            [item.path for item in self.images_data],
            base_path,
        )
        if replacement_path is None:
            return

        self.grid.select_paths([replacement_path], anchor_path=replacement_path)
        self._ensure_grid_path_visible(replacement_path)

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

        if file_path not in self._selected_paths_cache:
            return
        if self._selection_panel_refresh_in_progress:
            return

        if self._should_defer_selection_panel_refresh():
            self._show_selection_panels_pending(self._selected_count_cache)
            self._schedule_deferred_selection_panel_refresh()
            return

        selected_items = self._get_selected_items()
        if selected_items:
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
        if not self._selected_paths_cache:
            return []

        selected_items = [
            item
            for item in self.images_data
            if item.is_selected and item.path in self._selected_paths_cache
        ]
        if len(selected_items) == self._selected_count_cache:
            return selected_items

        rebuilt = [item for item in self.images_data if item.is_selected]
        self._set_selected_cache_from_items(rebuilt)
        return rebuilt

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
        self.grid._ensure_visible(index, navigation_activity=False)
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
        normalized = self.photo_model.normalize_filter_criteria(criteria)
        if normalized == self._current_filter:
            return

        snapshot = self._capture_grid_viewport_snapshot()
        self._current_filter = normalized
        self._pending_filter_criteria = normalized
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
        if snapshot is None:
            return
        started = time.perf_counter()
        total_before = len(self.photo_model.all_photos)

        self._next_model_change_fast_first_paint = True
        changed = self.photo_model.set_filter(criteria)
        after_filter = time.perf_counter()
        if not changed:
            self._next_model_change_fast_first_paint = False

        if changed:
            self._restore_grid_viewport_after_filter_change(snapshot)
        after_restore = time.perf_counter()

        criteria_folder = criteria.folder if criteria is not None else None
        criteria_labels = sorted(criteria.labels) if criteria is not None else []
        criteria_no_label = criteria.include_no_label if criteria is not None else False
        criteria_search = criteria.search_text if criteria is not None else ""
        grid_ms = self._last_model_change_grid_ms if changed else 0.0

        logger.debug(
            "Deferred filter apply completed: "
            "folder=%r labels=%s include_no_label=%s search=%r "
            "result=%d/%d changed=%s model=%.1fms grid=%.1fms restore=%.1fms total=%.1fms",
            criteria_folder,
            criteria_labels,
            criteria_no_label,
            criteria_search,
            len(self.photo_model.photos),
            total_before,
            changed,
            (after_filter - started) * 1000.0,
            grid_ms,
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

        workspace_property_action = QAction("Property...", self)
        workspace_property_action.triggered.connect(self._on_open_workspace_properties)
        file_menu.addAction(workspace_property_action)

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
        self._quit_action = quit_action

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

        clear_gpx_action = QAction("Clear GPS...", self)
        clear_gpx_action.triggered.connect(self._on_clear_gps)
        tools_menu.addAction(clear_gpx_action)

        tools_menu.addSeparator()

        manual_lens_action = QAction("Set Lens Info ...", self)
        manual_lens_action.triggered.connect(self._on_set_lens_info)
        tools_menu.addAction(manual_lens_action)

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
        self._initialize_fullscreen_menu_action_policy()

    def _initialize_fullscreen_menu_action_policy(self) -> None:
        self._fullscreen_menu_managed_actions = self._collect_menu_actions_for_policy()
        self._fullscreen_menu_allowed_actions = {self._quit_action}
        self._fullscreen_menu_action_restore_state.clear()
        self._fullscreen_menu_policy_active = False

    def _collect_menu_actions_for_policy(self) -> list[QAction]:
        managed_actions: list[QAction] = []
        seen_action_ids: set[int] = set()

        def _add_action(action: QAction) -> None:
            action_id = id(action)
            if action_id in seen_action_ids:
                return
            seen_action_ids.add(action_id)
            managed_actions.append(action)

            submenu = action.menu()
            if submenu is None:
                return
            for submenu_action in submenu.actions():
                _add_action(submenu_action)

        for top_level_action in self.menuBar().actions():
            _add_action(top_level_action)

        return managed_actions

    def _set_fullscreen_menu_action_policy(self, enabled: bool) -> None:
        if enabled:
            if self._fullscreen_menu_policy_active:
                return
            self._fullscreen_menu_action_restore_state.clear()
            for action in self._fullscreen_menu_managed_actions:
                if action in self._fullscreen_menu_allowed_actions:
                    continue
                self._fullscreen_menu_action_restore_state[action] = action.isEnabled()
                action.setEnabled(False)
            self._fullscreen_menu_policy_active = True
            return

        if not self._fullscreen_menu_policy_active:
            return
        for action, was_enabled in self._fullscreen_menu_action_restore_state.items():
            try:
                action.setEnabled(was_enabled)
            except RuntimeError:
                continue
        self._fullscreen_menu_action_restore_state.clear()
        self._fullscreen_menu_policy_active = False

    def on_about(self):
        github_url = "https://github.com/gvellut/piqopiqo"
        today = datetime.now().strftime("%Y-%m-%d")
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME}</b><br>"
            f"Version: {piqopiqo_version}<br>"
            f"Date: {today}<br><br>"
            f'<a href="{github_url}">{github_url}</a>',
        )

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

    def _get_grid_num_column_bounds(self) -> tuple[int, int]:
        min_cols = max(
            1,
            int(get_runtime_setting(RuntimeSettingKey.GRID_NUM_COLUMNS_MIN)),
        )
        max_cols = max(
            1,
            int(get_runtime_setting(RuntimeSettingKey.GRID_NUM_COLUMNS_MAX)),
        )
        if max_cols < min_cols:
            max_cols = min_cols
        return min_cols, max_cols

    def _clamp_grid_num_columns(self, value: object) -> int:
        min_cols, max_cols = self._get_grid_num_column_bounds()
        try:
            requested = int(value)
        except (TypeError, ValueError):
            requested = min_cols
        return max(min_cols, min(requested, max_cols))

    def _apply_grid_num_columns(self, value: object, *, persist: bool) -> None:
        min_cols, max_cols = self._get_grid_num_column_bounds()
        columns = self._clamp_grid_num_columns(value)
        self.grid.set_num_columns(columns)
        self.column_selector.set_value(columns, min_cols, max_cols)
        if persist:
            set_user_setting(UserSettingKey.NUM_COLUMNS, columns)

    def _on_column_selector_decrement(self) -> None:
        self._apply_grid_num_columns(self.grid.n_cols - 1, persist=True)

    def _on_column_selector_increment(self) -> None:
        self._apply_grid_num_columns(self.grid.n_cols + 1, persist=True)

    def _on_main_splitter_moved(self, _pos: int, _index: int) -> None:
        if self._main_splitter.count() < 2:
            return
        sizes = self._main_splitter.sizes()
        if len(sizes) < 2:
            return
        right_size = int(sizes[1])
        if right_size > 0:
            self._right_sidebar_restore_size = right_size
            self._right_sidebar_collapsed = False

    def _toggle_right_sidebar_collapsed(self) -> None:
        if self._main_splitter.count() < 2:
            return

        sizes = self._main_splitter.sizes()
        if len(sizes) < 2:
            return

        grid_size = max(0, int(sizes[0]))
        right_size = max(0, int(sizes[1]))
        total = grid_size + right_size
        if total <= 0:
            return

        if right_size > 0:
            self._right_sidebar_restore_size = right_size

        if right_size > 0 and not self._right_sidebar_collapsed:
            self._right_sidebar_collapsed = True
            self._main_splitter.setSizes([total, 0])
            return

        restore_size = self._right_sidebar_restore_size
        if restore_size is None:
            restore_size = max(120, int(total * 0.2))
        restore_size = max(1, min(int(restore_size), total))

        self._right_sidebar_collapsed = False
        self._main_splitter.setSizes([max(0, total - restore_size), restore_size])

    def _apply_settings_changes(self, changed_keys: set[UserSettingKey]) -> None:
        if not changed_keys:
            return

        if UserSettingKey.NUM_COLUMNS in changed_keys:
            self._apply_grid_num_columns(
                get_user_setting(UserSettingKey.NUM_COLUMNS),
                persist=False,
            )

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
            UserSettingKey.PROTECT_NON_TEXT_METADATA in changed_keys
            and self.edit_panel is not None
        ):
            self.edit_panel.set_non_text_metadata_protection(
                bool(get_user_setting(UserSettingKey.PROTECT_NON_TEXT_METADATA))
            )

        if (
            UserSettingKey.FORCE_SRGB in changed_keys
            or UserSettingKey.SCREEN_COLOR_PROFILE in changed_keys
        ):
            refresh_main_screen_color_space_cache()
            self.grid.invalidate_all_pixmap_caches()
            self.grid.on_scroll(self.grid.scrollbar.value())
            if self._fullscreen_overlay is not None:
                self._fullscreen_overlay._load_pixmap_at_current_index()
                self._fullscreen_overlay.update()

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

    def _on_clear_gps(self):
        from .tools.gpx2exif.actions import launch_clear_gps

        launch_clear_gps(self)

    def _on_set_lens_info(self):
        from .tools.manual_lens import launch_manual_lens

        launch_manual_lens(self)

    def _on_upload_to_flickr(self):
        manager = self._active_flickr_upload_manager
        if manager is not None and manager.is_running():
            QMessageBox.information(
                self,
                "Upload to Flickr",
                "A Flickr upload operation is already running.",
            )
            return
        if self._active_flickr_metadata_precheck_worker is not None:
            QMessageBox.information(
                self,
                "Upload to Flickr",
                "A Flickr upload metadata check is already running.",
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
            self._clear_filters_before_folder_load()
            self._load_folder(folder)

    def _to_relative_folder_label(self, folder_path: str) -> str:
        if not self.root_folder:
            return folder_path
        try:
            relative = os.path.relpath(folder_path, self.root_folder)
        except ValueError:
            return folder_path
        if relative in ("", "."):
            return "."
        return relative

    def _build_workspace_folder_summaries(self) -> list[WorkspaceFolderSummary]:
        photo_count_by_folder: dict[str, int] = {}
        for item in self.photo_model.all_photos:
            folder = item.source_folder
            photo_count_by_folder[folder] = photo_count_by_folder.get(folder, 0) + 1

        summaries: list[WorkspaceFolderSummary] = []
        for folder_path in self.photo_model.source_folders:
            summaries.append(
                WorkspaceFolderSummary(
                    folder_path=folder_path,
                    relative_path=self._to_relative_folder_label(folder_path),
                    cache_folder_name=get_folder_cache_id(folder_path),
                    photo_count=int(photo_count_by_folder.get(folder_path, 0)),
                )
            )
        return summaries

    def _on_open_workspace_properties(self) -> None:
        if not self.root_folder:
            QMessageBox.information(
                self,
                "Workspace Property",
                "No folder is currently loaded.",
            )
            return

        dialog = WorkspacePropertiesDialog(
            root_folder=self.root_folder,
            total_photo_count=len(self.photo_model.all_photos),
            folder_summaries=self._build_workspace_folder_summaries(),
            parent=self,
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if not dialog.clear_thumb_cache_requested and not dialog.clear_metadata_requested:
            return

        self._start_workspace_cleanup(
            clear_thumb_cache=dialog.clear_thumb_cache_requested,
            clear_metadata=dialog.clear_metadata_requested,
        )

    def _start_workspace_cleanup(
        self,
        *,
        clear_thumb_cache: bool,
        clear_metadata: bool,
    ) -> None:
        if not clear_thumb_cache and not clear_metadata:
            return
        if self._workspace_cleanup_running:
            QMessageBox.information(
                self,
                "Workspace Property",
                "A workspace cleanup is already running.",
            )
            return

        source_folders = list(self.photo_model.source_folders)
        file_paths = [item.path for item in self.photo_model.all_photos]
        self._workspace_cleanup_context = {
            "source_folders": source_folders,
            "file_paths": file_paths,
        }
        self._workspace_cleanup_running = True

        # Ensure DB files can be cleaned and stale media results are ignored.
        self.db_manager.close_all()
        self.media_manager.reset_for_folder([], [])
        self.status_bar.reset()

        worker = _WorkspaceCleanupWorker(
            source_folders,
            clear_thumb_cache=clear_thumb_cache,
            clear_metadata=clear_metadata,
        )
        worker.signals.finished.connect(self._on_workspace_cleanup_finished)
        self._workspace_cleanup_worker = worker
        self._workspace_cleanup_pool.start(worker)

    def _invalidate_workspace_items_for_reload(self) -> None:
        for item in self.photo_model.all_photos:
            item.state = 0
            item._cache_state_dirty = True
            item.embedded_pixmap = None
            item.hq_pixmap = None
            item.pixmap = None
            item.exif_data = None
            item.db_metadata = None

    def _on_workspace_cleanup_finished(self, error_message: object) -> None:
        context = self._workspace_cleanup_context or {}
        source_folders = list(context.get("source_folders") or [])
        file_paths = list(context.get("file_paths") or [])

        self._workspace_cleanup_running = False
        self._workspace_cleanup_context = None
        self._workspace_cleanup_worker = None

        self._invalidate_workspace_items_for_reload()
        self.media_manager.reset_for_folder(file_paths, source_folders)
        if self._last_visible_paths:
            self.media_manager.update_visible(self._last_visible_paths)
        self.grid.on_scroll(self.grid.scrollbar.value())
        self._reconcile_selection_and_panels()

        if isinstance(error_message, str) and error_message:
            QMessageBox.warning(
                self,
                "Workspace Property",
                "Cleanup completed with an error:\n\n"
                f"{error_message}",
            )

    def _clear_filters_before_folder_load(self) -> None:
        """Clear active filters before loading a new folder via Open Folder."""
        self.filter_panel.clear_filter()
        if self._filter_apply_scheduled:
            # Ensure the filter reset is applied before the new folder scan starts.
            self._apply_pending_filter_change()

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
        self._update_status_bar_count()

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
            item._cache_state_dirty = True
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
            item._cache_state_dirty = True
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
        item._cache_state_dirty = False
        has_hq_pixmap = getattr(item, "hq_pixmap", None) is not None

        if thumb_type == "embedded":
            item.embedded_pixmap = None
            # Keep current HQ display to avoid HQ->embedded flicker while delayed-HQ
            # mode is active during filter/sort viewport restore or navigation.
            if has_hq_pixmap:
                return
        else:
            if has_hq_pixmap:
                return
            item.hq_pixmap = None
        item.pixmap = None
        self.grid.refresh_item(item._global_index)

    def on_selection_changed(self, selected_indices):
        # Mark selection as changed for undo tracking
        self._selection_changed_since_edit = True

        selected_count = self._set_selected_cache_from_indices(selected_indices)
        self._update_status_bar_count()
        if selected_count > LARGE_SELECTION_PANEL_DEFER_THRESHOLD:
            self._apply_or_defer_panel_refresh(selected_count=selected_count)
            return

        selected_items = [
            self.images_data[i]
            for i in sorted(selected_indices)
            if 0 <= i < len(self.images_data)
        ]
        self._set_selected_cache_from_items(selected_items)
        self._apply_or_defer_panel_refresh(selected_items=selected_items)

    def _update_panels_for_selection(self, items: list[ImageItem]) -> None:
        self._clear_selection_panels_pending()

        # Load db_metadata for selected items if not already loaded.
        for item in items:
            if item.db_metadata is None:
                db = self.db_manager.get_db_for_image(item.path)
                item.db_metadata = db.get_metadata(item.path)

        self._selection_panel_refresh_in_progress = True
        try:
            if self.edit_panel:
                self.edit_panel.update_for_selection(items)

            self.media_manager.ensure_panel_fields_loaded_from_db(
                [item.path for item in items]
            )
            self.exif_panel.update_exif(items)
        finally:
            self._selection_panel_refresh_in_progress = False

    def _reconcile_selection_and_panels(self) -> None:
        selected_items = self.photo_model.get_selected_photos()
        self._selection_changed_since_edit = True
        self._set_selected_cache_from_items(selected_items)
        self._update_status_bar_count()
        self._apply_or_defer_panel_refresh(selected_items=selected_items)

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
        overlay_ref.label_shortcut_requested.connect(
            self._apply_label_to_fullscreen_current
        )
        self._setup_shortcuts()
        self._set_fullscreen_menu_action_policy(True)
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
            self._set_fullscreen_menu_action_policy(False)
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
        started = time.perf_counter()
        self.grid.set_data(
            self.photo_model.photos,
            fast_first_paint=self._next_model_change_fast_first_paint,
        )
        reselection_context = self._pending_metadata_reselection_context
        self._pending_metadata_reselection_context = None
        if reselection_context is not None:
            self._apply_pending_metadata_reselection(reselection_context)
        self._next_model_change_fast_first_paint = False
        after_grid = time.perf_counter()

        self._update_status_bar_count()
        after_status = time.perf_counter()

        self._reconcile_selection_and_panels()
        after_panels = time.perf_counter()

        self._last_model_change_grid_ms = (after_grid - started) * 1000.0
        logger.debug(
            "Model changed refresh timings: grid=%.1fms status=%.1fms panels=%.1fms total=%.1fms",
            (after_grid - started) * 1000.0,
            (after_status - after_grid) * 1000.0,
            (after_panels - after_status) * 1000.0,
            (after_panels - started) * 1000.0,
        )

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
        self._reconcile_selection_and_panels()

    def _on_photo_removed(self, file_path: str, _former_index: int):
        """Handle photo removed from model."""
        self._items_by_path.pop(file_path, None)
        self.media_manager.remove_files([file_path])
        self.filter_panel.set_folders(self.photo_model.source_folders)

        self.grid.set_data(self.photo_model.photos)
        self._reconcile_selection_and_panels()

    def _update_status_bar_count(self):
        """Update status bar photo count."""
        total = len(self.photo_model.all_photos)
        filtered = len(self.photo_model.photos)
        selected = len(self.photo_model.get_selected_photos())
        if total == filtered:
            self.status_bar.set_photo_count(total, selected=selected)
        else:
            self.status_bar.set_photo_count(total, filtered, selected=selected)

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
            self._background_db_save_pool,
            timeout_ms,
            clear_queued=True,
        )
        if not label_pool_completed:
            logger.warning(
                "Timed out waiting for label metadata saves to finish on shutdown"
            )

        cleanup_pool_completed = drain_qthread_pool(
            self._workspace_cleanup_pool,
            timeout_ms,
            clear_queued=True,
        )
        if not cleanup_pool_completed:
            logger.warning("Timed out waiting for workspace cleanup to finish on shutdown")

        if self.edit_panel is not None:
            self.edit_panel.shutdown_background_saves(
                timeout_ms,
                clear_queued=True,
            )

        self._stop_folder_watcher()
        if self._active_flickr_metadata_precheck_worker is not None:
            self._active_flickr_metadata_precheck_worker.request_cancel()
            self._active_flickr_metadata_precheck_worker = None
        if self._active_flickr_upload_manager is not None:
            self._active_flickr_upload_manager.stop(timeout_s=timeout_s)
            self._active_flickr_upload_manager = None
        if hasattr(self, "media_manager"):
            self.media_manager.stop(timeout_s=timeout_s)
        if hasattr(self, "db_manager"):
            self.db_manager.close_all()
