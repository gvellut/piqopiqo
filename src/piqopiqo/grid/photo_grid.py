"""Photo grid widget for displaying thumbnails."""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QScrollBar,
    QWidget,
)

from piqopiqo.cache_paths import get_thumb_dir_for_folder
from piqopiqo.config import Config
from piqopiqo.metadata.db_fields import DBFields

from .photo_cell import PhotoCell

logger = logging.getLogger(__name__)


class PhotoGrid(QWidget):
    """Widget displaying a grid of photo thumbnails."""

    request_thumb = Signal(int)
    selection_changed = Signal(set)
    request_fullscreen = Signal(list)
    context_menu_requested = Signal(int, object)  # index, QPoint (global pos)
    visible_paths_changed = Signal(list)  # list[str] in display order

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
        self._last_visible_paths: list[str] = []
        self._loaded_hq_indices: set[int] = set()
        self._hq_display_enabled = True

        self._hq_idle_timer = QTimer(self)
        self._hq_idle_timer.setSingleShot(True)
        self._hq_idle_timer.timeout.connect(self._on_hq_idle_timeout)

        self._wheel_last_ts: float | None = None
        self._wheel_streak_dir = 0
        self._wheel_streak_count = 0

    def set_data(self, items):
        # Inject index for click handling (preserve selection state)
        for i, item in enumerate(items):
            item._global_index = i
        self.items_data = items
        self._loaded_hq_indices = {
            i for i, item in enumerate(items) if getattr(item, "hq_pixmap", None)
        }

        # Update last selected index based on current selection
        selected = [i for i, item in enumerate(items) if item.is_selected]
        self._last_selected_index = selected[-1] if selected else -1

        self._recalculate_scrollbar()
        self._render_current_view()

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
                cell.right_clicked.connect(self._on_cell_right_clicked)
                self.grid_layout.addWidget(cell, r, c)
                self.cells.append(cell)

        # Force data refresh
        self._recalculate_scrollbar()
        self._render_current_view()

    def _calculate_metadata_height(self) -> int:
        """Calculate the height needed for metadata display."""
        font = QFont()
        font.setPointSize(Config.FONT_SIZE)
        fm = QFontMetrics(font)
        line_height = fm.lineSpacing()

        # Count lines: 1 for filename + 1 per configured field (excluding label)
        num_lines = 1  # filename
        for field in Config.GRID_ITEM_FIELDS:
            if field != DBFields.LABEL:  # Label is swatch, not text line
                num_lines += 1

        return num_lines * line_height + Config.GRID_ITEM_TEXT_FIELDS_TOP_PADDING

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
            self._render_current_view()

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
        self._mark_navigation_activity()
        self._render(int(value), allow_hq=self._allow_hq_now())

    def _is_hq_delay_enabled(self) -> bool:
        return bool(getattr(Config, "GRID_HQ_THUMB_DELAY_ENABLED", False))

    def _allow_hq_now(self) -> bool:
        return (not self._is_hq_delay_enabled()) or self._hq_display_enabled

    def _restart_hq_idle_timer(self) -> None:
        delay_ms = int(getattr(Config, "GRID_HQ_THUMB_LOAD_DELAY_MS", 200))
        if delay_ms <= 0:
            self._hq_display_enabled = True
            return
        self._hq_idle_timer.start(delay_ms)

    def _mark_navigation_activity(self) -> None:
        if not self._is_hq_delay_enabled():
            self._hq_display_enabled = True
            return
        self._hq_display_enabled = False
        self._restart_hq_idle_timer()

    def _on_hq_idle_timeout(self) -> None:
        self._hq_display_enabled = True
        self._render(int(self.scrollbar.value()), allow_hq=True)

    def _render_current_view(self) -> None:
        self._render(int(self.scrollbar.value()), allow_hq=self._allow_hq_now())

    def _render(self, start_row: int, *, allow_hq: bool) -> None:
        start_data_index = start_row * self.n_cols
        buffer_start_idx, buffer_end_idx = self._buffer_index_range(start_row)
        visible_end_idx = min(
            len(self.items_data), start_data_index + (self.n_rows * self.n_cols)
        )

        buffered_paths: list[str] = []
        for idx in range(buffer_start_idx, buffer_end_idx):
            item = self.items_data[idx]
            self._sync_item_state_from_cache(item)
            buffered_paths.append(item.path)

        if allow_hq:
            self._ensure_hq_pixmaps_loaded_in_range(buffer_start_idx, start_data_index)
            self._ensure_hq_pixmaps_loaded_in_range(visible_end_idx, buffer_end_idx)

        for i, cell in enumerate(self.cells):
            data_index = start_data_index + i

            # Pass layout info just in case
            cell.set_layout_info(self.layout_info)

            if data_index < len(self.items_data):
                item = self.items_data[data_index]
                self._ensure_display_pixmap_loaded(item, allow_hq=allow_hq)
                cell.set_content(item, item.is_selected)
                cell.show()

                if item.state == 0:
                    self.request_thumb.emit(data_index)
            else:
                cell.set_content(None, False)
                # Ensure complete cells are displayed even if empty
                cell.show()

        self._evict_hq_pixmaps_outside(buffer_start_idx, buffer_end_idx)

        if buffered_paths != self._last_visible_paths:
            self._last_visible_paths = buffered_paths
            self.visible_paths_changed.emit(buffered_paths)

    def _buffer_index_range(self, start_row: int) -> tuple[int, int]:
        """Return [start, end) data-index range to keep HQ pixmaps for."""
        buffer_rows = int(getattr(Config, "GRID_THUMB_BUFFER_ROWS", 2))
        if self.n_cols <= 0:
            return (0, 0)

        total_items = len(self.items_data)
        total_rows = math.ceil(total_items / self.n_cols) if total_items else 0
        visible_start_row = max(0, int(start_row))
        visible_end_row = min(total_rows, visible_start_row + self.n_rows)

        keep_start_row = max(0, visible_start_row - buffer_rows)
        keep_end_row = min(total_rows, visible_end_row + buffer_rows)

        start_idx = keep_start_row * self.n_cols
        end_idx = min(total_items, keep_end_row * self.n_cols)
        return (start_idx, end_idx)

    def _cache_paths_for_item(self, item) -> tuple[Path, Path]:
        base_name = os.path.splitext(os.path.basename(item.path))[0]
        thumb_dir = get_thumb_dir_for_folder(item.source_folder)
        embedded_path = Path(thumb_dir) / "embedded" / f"{base_name}.jpg"
        hq_path = Path(thumb_dir) / "hq" / f"{base_name}.jpg"
        return embedded_path, hq_path

    def _sync_item_state_from_cache(self, item) -> None:
        """Best-effort sync of item.state from disk caches (for restarts)."""
        if item is None:
            return

        embedded_path, hq_path = self._cache_paths_for_item(item)
        base_name = os.path.splitext(os.path.basename(item.path))[0]
        thumb_dir = get_thumb_dir_for_folder(item.source_folder)
        legacy_embedded = Path(thumb_dir) / f"{base_name}_embedded.jpg"
        legacy_hq = Path(thumb_dir) / f"{base_name}_hq.jpg"

        has_hq = hq_path.exists() or legacy_hq.exists()
        has_embedded = embedded_path.exists() or legacy_embedded.exists()

        if has_hq:
            item.state = max(int(getattr(item, "state", 0)), 2)
        elif has_embedded:
            item.state = max(int(getattr(item, "state", 0)), 1)
        else:
            if int(getattr(item, "state", 0)) != 0:
                item.state = 0
            item.embedded_pixmap = None
            item.hq_pixmap = None
            item.pixmap = None

    def _ensure_embedded_pixmap_loaded(self, item) -> None:
        if item is None or getattr(item, "embedded_pixmap", None) is not None:
            return
        embedded_path, _ = self._cache_paths_for_item(item)
        if embedded_path.exists():
            item.embedded_pixmap = QPixmap(str(embedded_path))
            return

        base_name = os.path.splitext(os.path.basename(item.path))[0]
        thumb_dir = get_thumb_dir_for_folder(item.source_folder)
        legacy_path = Path(thumb_dir) / f"{base_name}_embedded.jpg"
        if legacy_path.exists():
            item.embedded_pixmap = QPixmap(str(legacy_path))

    def _ensure_hq_pixmap_loaded(self, item) -> None:
        if item is None or getattr(item, "hq_pixmap", None) is not None:
            return
        _, hq_path = self._cache_paths_for_item(item)
        if hq_path.exists():
            item.hq_pixmap = QPixmap(str(hq_path))
        else:
            base_name = os.path.splitext(os.path.basename(item.path))[0]
            thumb_dir = get_thumb_dir_for_folder(item.source_folder)
            legacy_path = Path(thumb_dir) / f"{base_name}_hq.jpg"
            if legacy_path.exists():
                item.hq_pixmap = QPixmap(str(legacy_path))

        if (
            getattr(item, "hq_pixmap", None) is not None
            and getattr(item, "_global_index", -1) >= 0
        ):
            self._loaded_hq_indices.add(int(item._global_index))

    def _ensure_hq_pixmaps_loaded_in_range(self, start_idx: int, end_idx: int) -> None:
        """Load HQ pixmaps for buffered rows around the visible range."""
        if start_idx >= end_idx:
            return

        start = max(0, start_idx)
        end = min(len(self.items_data), end_idx)
        for idx in range(start, end):
            item = self.items_data[idx]
            if int(getattr(item, "state", 0)) >= 2:
                self._ensure_hq_pixmap_loaded(item)

    def _ensure_display_pixmap_loaded(self, item, *, allow_hq: bool) -> None:
        """Ensure the best available pixmap is loaded and set as item.pixmap."""
        if item is None:
            return

        state = int(getattr(item, "state", 0))

        if state >= 1:
            self._ensure_embedded_pixmap_loaded(item)
        if allow_hq and state >= 2:
            self._ensure_hq_pixmap_loaded(item)

        # Prefer HQ when enabled. In delay mode while navigating, keep embedded.
        if allow_hq and getattr(item, "hq_pixmap", None) is not None:
            item.pixmap = item.hq_pixmap
        else:
            item.pixmap = item.embedded_pixmap or item.hq_pixmap

    def _evict_hq_pixmaps_outside(self, start_idx: int, end_idx: int) -> None:
        """Free HQ pixmaps outside [start_idx, end_idx) while keeping embedded."""
        if not self._loaded_hq_indices:
            return

        to_drop = [i for i in self._loaded_hq_indices if not (start_idx <= i < end_idx)]
        for idx in to_drop:
            if 0 <= idx < len(self.items_data):
                item = self.items_data[idx]
                if getattr(item, "hq_pixmap", None) is not None:
                    if getattr(item, "pixmap", None) is item.hq_pixmap:
                        item.pixmap = item.embedded_pixmap
                    item.hq_pixmap = None
            self._loaded_hq_indices.discard(idx)

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
                self._sync_item_state_from_cache(item)
                self._ensure_display_pixmap_loaded(item, allow_hq=self._allow_hq_now())
                cell.set_content(item, item.is_selected)

    def on_cell_clicked(self, global_index, is_shift, is_ctrl):
        # Empty cell clicked - clear selection
        if global_index == -1:
            for item in self.items_data:
                item.is_selected = False
            self._last_selected_index = -1
            self.selection_changed.emit(set())
            self._render_current_view()
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

        self._render_current_view()

    def _on_cell_right_clicked(self, global_index: int):
        """Handle right-click on a cell.

        Selection behavior:
        - If clicked photo is not selected: deselect all, select only clicked
        - If clicked photo is already selected: keep current selection
        """
        if global_index == -1 or global_index >= len(self.items_data):
            return

        # Selection behavior: if clicked photo is not selected, select only it
        if not self.items_data[global_index].is_selected:
            # Deselect all, select this one
            for item in self.items_data:
                item.is_selected = False
            self.items_data[global_index].is_selected = True
            self._last_selected_index = global_index

            selected_indices = {global_index}
            self.selection_changed.emit(selected_indices)
            self._render_current_view()

        # Emit context menu request with global cursor position
        self.context_menu_requested.emit(global_index, QCursor.pos())

    def wheelEvent(self, event):
        if not self.scrollbar.isVisible():
            return

        pixel_delta = event.pixelDelta().y()
        delta = pixel_delta if pixel_delta else event.angleDelta().y()
        if delta == 0:
            return

        current = self.scrollbar.value()
        direction = -1 if delta > 0 else 1

        # Base wheel "steps" from magnitude (keep >=1 for small deltas).
        if pixel_delta:
            base_steps = max(1, int(abs(pixel_delta) / 40))
        else:
            base_steps = max(1, int(round(abs(delta) / 120)))

        now = time.monotonic()
        dt_ms = (
            (now - self._wheel_last_ts) * 1000.0
            if self._wheel_last_ts is not None
            else None
        )

        if dt_ms is not None and dt_ms < 150 and direction == self._wheel_streak_dir:
            self._wheel_streak_count += 1
        else:
            self._wheel_streak_dir = direction
            self._wheel_streak_count = 1
        self._wheel_last_ts = now

        accel = 1 + (self._wheel_streak_count - 1) // 3
        accel = min(accel, 8)

        steps = base_steps * accel
        self.scrollbar.setValue(current + (direction * steps))
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
            self._mark_navigation_activity()
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
            self._mark_navigation_activity()
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
