"""Photo grid widget for displaying thumbnails."""

from __future__ import annotations

import logging
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QScrollBar,
    QWidget,
)

from piqopiqo.config import Config, Shortcut
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.shortcuts import match_shortcut_sequence

from .photo_cell import PhotoCell

logger = logging.getLogger(__name__)


class PhotoGrid(QWidget):
    """Widget displaying a grid of photo thumbnails."""

    request_thumb = Signal(int)
    selection_changed = Signal(set)
    request_fullscreen = Signal(list)
    context_menu_requested = Signal(int, object)  # index, QPoint (global pos)

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
                cell.right_clicked.connect(self._on_cell_right_clicked)
                self.grid_layout.addWidget(cell, r, c)
                self.cells.append(cell)

        # Force data refresh
        self._recalculate_scrollbar()
        self.on_scroll(self.scrollbar.value())

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
            self.on_scroll(self.scrollbar.value())

        # Emit context menu request with global cursor position
        self.context_menu_requested.emit(global_index, QCursor.pos())

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

        # Handle Select All shortcut
        select_all_shortcut = Config.SHORTCUTS.get(Shortcut.SELECT_ALL)
        if select_all_shortcut and match_shortcut_sequence(event, select_all_shortcut):
            self._select_all()
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

    def _select_all(self):
        """Select all visible items (after filtering)."""
        if not self.items_data:
            return

        for item in self.items_data:
            item.is_selected = True

        if self.items_data:
            self._last_selected_index = len(self.items_data) - 1

        selected_indices = set(range(len(self.items_data)))
        self.selection_changed.emit(selected_indices)
        self.on_scroll(self.scrollbar.value())
