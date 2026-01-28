from __future__ import annotations

from datetime import datetime
from functools import partial
import logging
import math
import threading

from PySide6.QtCore import QRect, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMainWindow,
    QScrollBar,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import platform
from .config import Config, Shortcut
from .db_fields import EDITABLE_FIELDS, DBFields
from .edit_panel import EditPanel
from .exif_loader import ExifLoaderManager
from .exif_man import ExifManager, ExifPanel
from .filter_panel import FolderFilterPanel
from .fullscreen_overlay import FullscreenOverlay
from .metadata_db import MetadataDBManager
from .model import ImageItem, OnFullscreenExitMultipleSelected
from .status_bar import ErrorListDialog, LoadingStatusBar
from .support import save_last_folder
from .thumb_man import ThumbnailManager, scan_folder

logger = logging.getLogger(__name__)


def parse_shortcut(shortcut_str: str) -> QKeySequence:
    """Parse a shortcut string like 'ctrl+r', 'cmd+alt+t', '=' into a QKeySequence.

    Supports modifiers: ctrl, alt, cmd/meta, shift.
    Separator: +
    The last token is the key.
    """
    parts = [p.strip().lower() for p in shortcut_str.split("+")]
    qt_parts = []
    for part in parts[:-1]:
        # Map modifier names to Qt-understood strings
        if part in ("cmd", "meta"):
            qt_parts.append("Meta")
        elif part == "ctrl":
            qt_parts.append("Ctrl")
        elif part == "alt":
            qt_parts.append("Alt")
        elif part == "shift":
            qt_parts.append("Shift")

    key_part = parts[-1]
    qt_parts.append(key_part.upper() if len(key_part) > 1 else key_part)

    return QKeySequence("+".join(qt_parts))


class _LabelSaveWorker(QRunnable):
    """Background worker to save label metadata."""

    def __init__(self, db, file_path: str, data: dict):
        super().__init__()
        self.db = db
        self.file_path = file_path
        self.data = data

    def run(self):
        try:
            self.db.save_metadata(self.file_path, self.data)
        except Exception as e:
            logger.error(f"Failed to save label for {self.file_path}: {e}")


def _get_label_color(label: str) -> str | None:
    """Get color hex for a label name from STATUS_LABELS."""
    for sl in Config.STATUS_LABELS:
        if sl.name == label:
            return sl.color
    return None


class PhotoCell(QFrame):
    clicked = Signal(int, bool, bool)

    def __init__(self, index_in_grid: int):
        super().__init__()
        self.index_in_grid = index_in_grid
        self.current_data = None
        self.is_selected = False
        self.layout_info = {}

        # Mimic the behavior of the delegate: accept focus, handle mouse
        self.setFocusPolicy(Qt.ClickFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # We handle drawing manually, but setting a stylesheet for the base is optional
        self.setStyleSheet("background-color: black;")

    def set_content(self, data: dict | None, is_selected: bool):
        self.current_data = data
        self.is_selected = is_selected
        self.update()

    def set_layout_info(self, info: dict):
        self.layout_info = info
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if self.current_data and event.button() == Qt.LeftButton:
            modifiers = event.modifiers()
            self.clicked.emit(
                self.current_data._global_index,
                bool(modifiers & Qt.ShiftModifier),
                bool(modifiers & Qt.ControlModifier),
            )
        super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent):
        if not self.layout_info:
            return

        painter = QPainter(self)
        rect = self.rect()

        # Selection Highlight
        if self.is_selected:
            # Get default highlight color
            highlight_color = (
                self.palette().color(QPalette.Highlight)
                if hasattr(self.palette(), "color")
                else QColor("#0078d7")
            )
            painter.fillRect(rect, highlight_color)

        if self.current_data is None:
            return

        # Unpack Data
        name = self.current_data.name
        state = self.current_data.state
        pixmap = self.current_data.pixmap
        db_meta = self.current_data.db_metadata or {}

        # Unpack Layout Info (computed in parent resizeEvent)
        pad = self.layout_info.get("pad", 5)
        meta_h = self.layout_info.get("meta_h", 20)

        # Image Rect
        img_rect = rect.adjusted(pad, pad, -pad, -(pad + meta_h))

        if state == 0:
            painter.fillRect(img_rect, QColor("black"))
        else:
            if pixmap:
                # Center pixmap
                pixmap_rect = pixmap.rect()
                pixmap_rect.moveCenter(img_rect.center())

                # Scale to fit if too big
                if (
                    pixmap_rect.width() > img_rect.width()
                    or pixmap_rect.height() > img_rect.height()
                ):
                    scaled = pixmap.scaled(
                        img_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                    pixmap_rect = scaled.rect()
                    pixmap_rect.moveCenter(img_rect.center())
                    painter.drawPixmap(pixmap_rect, scaled)
                else:
                    painter.drawPixmap(pixmap_rect, pixmap)

        # Draw label swatch (top-right corner of image area)
        if Config.GRID_ITEM_SHOW_LABEL_SWATCH:
            label = db_meta.get(DBFields.LABEL)
            if label:
                color = self._get_label_color(label)
                if color:
                    swatch_size = 16
                    swatch_margin = 4
                    swatch_rect = QRect(
                        img_rect.right() - swatch_size - swatch_margin,
                        img_rect.top() + swatch_margin,
                        swatch_size,
                        swatch_size,
                    )
                    painter.fillRect(swatch_rect, QColor(color))
                    painter.setPen(QPen(Qt.black, 1))
                    painter.drawRect(swatch_rect)

        # Text area
        text_rect = QRect(
            rect.left() + pad,
            rect.bottom() - meta_h - pad,
            rect.width() - (2 * pad),
            meta_h,
        )

        painter.setPen(QPen(Qt.white))
        font_metrics = painter.fontMetrics()
        line_height = font_metrics.lineSpacing()

        # Filename (first line)
        elided_name = font_metrics.elidedText(name, Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignTop | Qt.AlignHCenter, elided_name)

        # DB fields (subsequent lines)
        y_offset = line_height
        for field_name in Config.GRID_ITEM_FIELDS:
            if field_name == DBFields.LABEL:
                continue  # Label shown as swatch, not text

            value = db_meta.get(field_name, "")
            if value:
                # Format datetime objects as ISO string
                if field_name == DBFields.TIME_TAKEN and isinstance(value, datetime):
                    display_value = value.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    display_value = str(value)
                field_rect = QRect(
                    text_rect.left(),
                    text_rect.top() + y_offset,
                    text_rect.width(),
                    line_height,
                )
                elided_value = font_metrics.elidedText(
                    display_value, Qt.ElideRight, text_rect.width()
                )
                painter.drawText(
                    field_rect, Qt.AlignTop | Qt.AlignHCenter, elided_value
                )
            y_offset += line_height

        # Draw red border around item
        painter.setPen(QPen(QColor("red"), 2))
        painter.drawRect(rect.adjusted(1, 1, -1, -1))

    def _get_label_color(self, label: str) -> str | None:
        """Get color hex for a label name."""
        return _get_label_color(label)


class PagedPhotoGrid(QWidget):
    request_thumb = Signal(int)
    selection_changed = Signal(set)
    request_fullscreen = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("photo_grid")

        self.setFocusPolicy(Qt.StrongFocus)

        self.n_cols = Config.NUM_COLUMNS
        self.n_rows = 1
        self.items_data = []
        self._last_selected_index = -1
        self.layout_info = {}

        # Main Layout: Grid Container + Scrollbar
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Container for the grid
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(0)

        # Artificial Scrollbar
        self.scrollbar = QScrollBar(Qt.Vertical)
        self.scrollbar.setObjectName("photo_grid_scrollbar")
        self.scrollbar.setSingleStep(1)
        self.scrollbar.valueChanged.connect(self.on_scroll)

        self.main_layout.addWidget(self.grid_container, stretch=1)
        self.main_layout.addWidget(self.scrollbar, stretch=0)

        self.cells: list[PhotoCell] = []

    def set_data(self, items):
        # Inject index for click handling
        for i, item in enumerate(items):
            item._global_index = i
            item.is_selected = False
        self.items_data = items
        self._last_selected_index = -1
        self._recalculate_scrollbar()
        self.on_scroll(0)

    def _rebuild_grid(self, rows, cols):
        """Recreate the grid widgets only if dimensions changed."""
        logger.debug(f"Rebuilding grid: {rows}x{cols}")

        # Clear existing cells
        for cell in self.cells:
            self.grid_layout.removeWidget(cell)
            cell.deleteLater()
        self.cells.clear()

        self.n_rows = rows
        self.n_cols = cols

        # Create new cells
        for r in range(rows):
            for c in range(cols):
                cell = PhotoCell(len(self.cells))
                cell.clicked.connect(self.on_cell_clicked)
                self.grid_layout.addWidget(cell, r, c)
                self.cells.append(cell)

        # Force data refresh
        self._recalculate_scrollbar()
        self.on_scroll(self.scrollbar.value())

    def _calculate_metadata_height(self) -> int:
        """Calculate the height needed for metadata display."""
        from PySide6.QtGui import QFont, QFontMetrics

        font = QFont()
        font.setPointSize(Config.FONT_SIZE)
        fm = QFontMetrics(font)
        line_height = fm.lineSpacing()

        # Count lines: 1 for filename + 1 per configured field (excluding label)
        num_lines = 1  # filename
        for field in Config.GRID_ITEM_FIELDS:
            if field != DBFields.LABEL:  # Label is swatch, not text line
                num_lines += 1

        return num_lines * line_height + 4  # +4 for padding

    def resizeEvent(self, event):
        # Width available for the grid (Total width - Scrollbar width)
        sb_width = self.scrollbar.width() if self.scrollbar.isVisible() else 0
        panel_w = event.size().width() - sb_width
        panel_h = event.size().height()

        cfg = Config
        cols = cfg.NUM_COLUMNS
        pad = cfg.PADDING

        # Horizontal Calculation
        total_h_pad = (cols + 1) * pad
        avail_w = panel_w - total_h_pad
        # Avoid division by zero
        if cols == 0:
            cols = 1
        img_box_side = avail_w / cols

        # Vertical Calculation - dynamic based on configured fields
        meta_h = self._calculate_metadata_height()
        row_base_h = pad + img_box_side + meta_h + pad

        # Vertical Stretching (Fit to View)
        if row_base_h < 1:
            row_base_h = 1

        visible_rows = int(panel_h / row_base_h)
        if visible_rows < 1:
            visible_rows = 1

        used_h = visible_rows * row_base_h
        remaining = panel_h - used_h

        if visible_rows > 0:
            extra_per_row = remaining / visible_rows
        else:
            extra_per_row = 0

        # Store calculated layout info for Cells
        self.layout_info = {
            "img_rect_w": img_box_side,
            "img_rect_h": img_box_side + extra_per_row,
            "meta_h": meta_h,
            "pad": pad,
        }

        # Apply layout info to existing cells immediately (for smoother resize)
        for cell in self.cells:
            cell.set_layout_info(self.layout_info)

        # Check if we need to restructure the grid widgets
        if visible_rows != self.n_rows:
            self._rebuild_grid(visible_rows, cols)
        else:
            self._recalculate_scrollbar()
            # Just refresh content in case data range changed due to scroll limit
            # changes
            self.on_scroll(self.scrollbar.value())

        super().resizeEvent(event)

    def _recalculate_scrollbar(self):
        total_items = len(self.items_data)
        if self.n_cols == 0:
            return
        total_data_rows = math.ceil(total_items / self.n_cols)

        max_scroll = max(0, total_data_rows - self.n_rows)

        self.scrollbar.setRange(0, max_scroll)
        self.scrollbar.setPageStep(self.n_rows)

        # Visibility logic
        if total_data_rows <= self.n_rows:
            self.scrollbar.hide()
        else:
            self.scrollbar.show()

    def on_scroll(self, value):
        start_row = value
        start_data_index = start_row * self.n_cols

        for i, cell in enumerate(self.cells):
            data_index = start_data_index + i

            # Pass layout info just in case
            cell.set_layout_info(self.layout_info)

            if data_index < len(self.items_data):
                item = self.items_data[data_index]
                cell.set_content(item, item.is_selected)
                cell.show()

                if item.state == 0:
                    self.request_thumb.emit(data_index)
            else:
                cell.set_content(None, False)
                # Ensure complete cells are displayed even if empty
                cell.show()

    def refresh_item(self, global_index):
        # Efficiently update only if visible
        start_row = self.scrollbar.value()
        start_idx = start_row * self.n_cols
        end_idx = start_idx + (self.n_rows * self.n_cols)

        if start_idx <= global_index < end_idx:
            cell_pool_index = global_index - start_idx
            if 0 <= cell_pool_index < len(self.cells):
                cell = self.cells[cell_pool_index]
                item = self.items_data[global_index]
                cell.set_content(item, item.is_selected)

    def on_cell_clicked(self, global_index, is_shift, is_ctrl):
        if global_index == -1:
            return

        if is_ctrl:
            self.items_data[global_index].is_selected = not self.items_data[
                global_index
            ].is_selected
        elif is_shift:
            if self._last_selected_index != -1:
                start = min(self._last_selected_index, global_index)
                end = max(self._last_selected_index, global_index)
                for i in range(start, end + 1):
                    self.items_data[i].is_selected = True
        else:
            for item in self.items_data:
                item.is_selected = False
            self.items_data[global_index].is_selected = True

        self._last_selected_index = global_index

        selected_indices = {
            i for i, item in enumerate(self.items_data) if item.is_selected
        }
        self.selection_changed.emit(selected_indices)

        self.on_scroll(self.scrollbar.value())

    def wheelEvent(self, event):
        if not self.scrollbar.isVisible():
            return
        delta = event.angleDelta().y()
        current = self.scrollbar.value()
        if delta > 0:
            self.scrollbar.setValue(current - self.scrollbar.singleStep())
        else:
            self.scrollbar.setValue(current + self.scrollbar.singleStep())
        event.accept()

    def keyPressEvent(self, event):
        key = event.key()
        total_items = len(self.items_data)

        if total_items == 0:
            super().keyPressEvent(event)
            return

        selected_indices = [
            i for i, item in enumerate(self.items_data) if item.is_selected
        ]

        if not selected_indices:
            super().keyPressEvent(event)
            return

        # Handle fullscreen request first, as it applies to both single and multi-select
        if key == Qt.Key_Space:
            self.request_fullscreen.emit(selected_indices)
            return

        # Handle navigation
        if len(selected_indices) > 1:
            # Multi-selection: collapse and move
            if key == Qt.Key_Left:
                new_index = min(selected_indices) - 1
            elif key == Qt.Key_Right:
                new_index = max(selected_indices) + 1
            elif key == Qt.Key_Up:
                new_index = min(selected_indices) - self.n_cols
            elif key == Qt.Key_Down:
                new_index = max(selected_indices) + self.n_cols
            else:
                super().keyPressEvent(event)
                return

            new_index = max(0, min(new_index, len(self.items_data) - 1))
            self.on_cell_clicked(new_index, False, False)
            self._ensure_visible(new_index)
            return

        # Single selection navigation
        new_index = selected_indices[0]
        original_index = new_index

        if key == Qt.Key_Left:
            if new_index > 0:
                new_index -= 1
        elif key == Qt.Key_Right:
            if new_index < total_items - 1:
                new_index += 1
        elif key == Qt.Key_Up:
            if new_index - self.n_cols >= 0:
                new_index -= self.n_cols
        elif key == Qt.Key_Down:
            if new_index + self.n_cols < total_items:
                new_index += self.n_cols
        else:
            super().keyPressEvent(event)
            return

        if new_index != original_index:
            self.on_cell_clicked(new_index, False, False)
            self._ensure_visible(new_index)

    def _ensure_visible(self, index):
        """Scrolls the grid if the index is out of view."""
        # Calculate the row this item belongs to
        target_row = index // self.n_cols

        current_top_row = self.scrollbar.value()
        # The last fully visible row index
        current_bottom_row = current_top_row + self.n_rows - 1

        if target_row < current_top_row:
            # Item is above view -> Scroll Up to make it the top row
            self.scrollbar.setValue(target_row)
        elif target_row > current_bottom_row:
            # Item is below view -> Scroll Down to make it the bottom row
            # Logic: New Top = Target Row - (Visible Rows - 1)
            new_top = target_row - self.n_rows + 1
            self.scrollbar.setValue(new_top)


# TODO put MainWindow and PhotoGrid apart
class MainWindow(QMainWindow):
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
        self.filter_panel = FolderFilterPanel()
        self.filter_panel.filter_changed.connect(self._on_filter_changed)
        main_layout.addWidget(self.filter_panel)

        # Main horizontal splitter: grid | right panel(s)
        main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(main_splitter)

        self.grid = PagedPhotoGrid()
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
            shortcut_enum = Shortcut(f"label_{i}")
            if shortcut_enum in shortcuts:
                sc = QShortcut(
                    parse_shortcut(shortcuts[shortcut_enum]),
                    self,
                )
                sc.setContext(Qt.ApplicationShortcut)
                # Find label with matching index
                label_name = None
                for sl in Config.STATUS_LABELS:
                    if sl.index == i:
                        label_name = sl.name
                        break
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
            worker = _LabelSaveWorker(db, item.path, item.db_metadata.copy())
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

        logger.info("--- Qt Info ---")
        logger.info(f"Screen Name:    {current_screen.name()}")
        logger.info(f"Logical Size:   {log_geo.width()} x {log_geo.height()}")
        logger.info(f"DPR:            {dpr}")
        logger.info(f"Render Buffer:  {buffer_w} x {buffer_h}")

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
