"""Photo grid widget for displaying thumbnails."""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QFont, QFontMetrics, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QScrollBar,
    QTextEdit,
    QWidget,
)

from piqopiqo.cache_paths import get_thumb_dir_for_folder
from piqopiqo.color_management import load_pixmap_with_color_management
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.orientation import apply_orientation_to_pixmap
from piqopiqo.shortcuts import (
    Shortcut,
    build_label_shortcut_bindings,
    match_shortcut_sequence,
    parse_shortcut,
)
from piqopiqo.ssf.settings_state import (
    RuntimeSettingKey,
    UserSettingKey,
    get_runtime_setting,
    get_user_setting,
)

from .photo_cell import PhotoCell

logger = logging.getLogger(__name__)


class PhotoGrid(QWidget):
    """Widget displaying a grid of photo thumbnails."""

    request_thumb = Signal(int)
    selection_changed = Signal(set)
    request_fullscreen = Signal(list)
    context_menu_requested = Signal(int, object)  # index, QPoint (global pos)
    visible_paths_changed = Signal(list)  # list[str] in display order
    label_shortcut_requested = Signal(object)  # str | None

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("photo_grid")

        self.setFocusPolicy(Qt.StrongFocus)

        self.n_cols = int(get_user_setting(UserSettingKey.NUM_COLUMNS))
        self.n_rows = 1
        self.items_data = []
        self._last_selected_index = -1
        self._last_selected_path: str | None = None
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
        self._loaded_embedded_indices: set[int] = set()
        self._hq_display_enabled = True
        self._fast_first_paint_active = False
        self._suppress_scroll_navigation_activity = False

        self._hq_idle_timer = QTimer(self)
        self._hq_idle_timer.setSingleShot(True)
        self._hq_idle_timer.timeout.connect(self._on_hq_idle_timeout)

        self._wheel_last_ts: float | None = None
        self._wheel_streak_dir = 0
        self._wheel_streak_count = 0

        self._grid_view_shortcut_scope: QWidget | None = None
        self._label_shortcut_objects: list[QShortcut] = []
        self._shared_grid_view_shortcut_objects: list[QShortcut] = []
        self._shared_shortcuts_focus_connected = False

    def set_grid_view_shortcut_scope(self, widget: QWidget) -> None:
        self._grid_view_shortcut_scope = widget
        if not self._shared_shortcuts_focus_connected:
            app = QApplication.instance()
            if app is not None:
                app.focusChanged.connect(self._on_application_focus_changed)
                self._shared_shortcuts_focus_connected = True
        self.refresh_shortcuts()

    def refresh_shortcuts(self) -> None:
        self._clear_shortcut_bucket(self._label_shortcut_objects)
        self._clear_shortcut_bucket(self._shared_grid_view_shortcut_objects)

        shortcuts = get_user_setting(UserSettingKey.SHORTCUTS)
        status_labels = get_user_setting(UserSettingKey.STATUS_LABELS)

        # Grid label shortcuts are local to the grid widget only.
        for shortcut_str, label_name in build_label_shortcut_bindings(
            shortcuts, status_labels
        ):
            sc = QShortcut(parse_shortcut(shortcut_str), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(
                lambda label_name=label_name: self.label_shortcut_requested.emit(
                    label_name
                )
            )
            self._label_shortcut_objects.append(sc)

        scope = self._grid_view_shortcut_scope
        if scope is None:
            return

        # Shared grid-view scope shortcuts should work across grid + side panels.
        select_all_shortcut = (
            shortcuts.get(Shortcut.SELECT_ALL)
            or shortcuts.get(Shortcut.SELECT_ALL.value)
            or shortcuts.get(Shortcut.SELECT_ALL.name)
        )
        if select_all_shortcut:
            sc_select_all = QShortcut(parse_shortcut(select_all_shortcut), scope)
            sc_select_all.setContext(Qt.WidgetWithChildrenShortcut)
            sc_select_all.activated.connect(self._activate_select_all_shortcut)
            self._shared_grid_view_shortcut_objects.append(sc_select_all)

        sc_fullscreen = QShortcut(QKeySequence("Space"), scope)
        sc_fullscreen.setContext(Qt.WidgetWithChildrenShortcut)
        sc_fullscreen.activated.connect(self._activate_fullscreen_shortcut)
        self._shared_grid_view_shortcut_objects.append(sc_fullscreen)
        self._update_shared_grid_view_shortcut_enabled_state()

    def _clear_shortcut_bucket(self, bucket: list[QShortcut]) -> None:
        for shortcut in bucket:
            try:
                shortcut.setParent(None)
                shortcut.deleteLater()
            except RuntimeError:
                pass
        bucket.clear()

    def _activate_select_all_shortcut(self) -> None:
        if not self._shared_grid_view_shortcuts_allowed():
            return
        self.select_all_visible()

    def _activate_fullscreen_shortcut(self) -> None:
        if not self._shared_grid_view_shortcuts_allowed():
            return
        self._request_fullscreen_from_current_selection()

    def _request_fullscreen_from_current_selection(self) -> None:
        selected_indices = [
            i
            for i, item in enumerate(self.items_data)
            if getattr(item, "is_selected", False)
        ]
        if not selected_indices:
            return
        self.request_fullscreen.emit(selected_indices)

    def _on_application_focus_changed(self, _old, _new) -> None:
        self._update_shared_grid_view_shortcut_enabled_state()

    def _update_shared_grid_view_shortcut_enabled_state(self) -> None:
        enabled = self._shared_grid_view_shortcuts_allowed()
        for shortcut in self._shared_grid_view_shortcut_objects:
            shortcut.setEnabled(enabled)

    def _shared_grid_view_shortcuts_allowed(self) -> bool:
        scope = self._grid_view_shortcut_scope
        if scope is None:
            return False
        app = QApplication.instance()
        if app is None:
            return False
        focus_widget = app.focusWidget()
        if focus_widget is None:
            return False
        if not self._widget_is_within_scope(focus_widget, scope):
            return False
        return not self._is_text_input_widget(focus_widget)

    def _widget_is_within_scope(self, widget: QWidget, scope: QWidget) -> bool:
        current: QWidget | None = widget
        while current is not None:
            if current is scope:
                return True
            current = current.parentWidget()
        return False

    def _is_text_input_widget(self, widget: QWidget) -> bool:
        if isinstance(
            widget,
            (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox),
        ):
            return True
        return isinstance(widget, QComboBox) and widget.isEditable()

    def _lookup_configured_shortcut(self, shortcut_key: Shortcut) -> str | None:
        shortcuts = get_user_setting(UserSettingKey.SHORTCUTS)
        for candidate in (shortcut_key, shortcut_key.value, shortcut_key.name):
            value = shortcuts.get(candidate)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def select_all_visible(self) -> None:
        """Select all currently visible items in the grid."""
        if not self.items_data:
            return

        for item in self.items_data:
            item.is_selected = True

        self._set_selection_anchor(len(self.items_data) - 1)
        self.selection_changed.emit(set(range(len(self.items_data))))
        self.refresh_visible_selection_only()

    def set_data(self, items, *, fast_first_paint: bool = False):
        perf_enabled = logger.isEnabledFor(logging.DEBUG)
        if perf_enabled:
            started = time.perf_counter()

        previous_anchor_path = self._last_selected_path
        # Inject index for click handling (preserve selection state)
        for i, item in enumerate(items):
            item._global_index = i
        self.items_data = items
        self._loaded_hq_indices = {
            i for i, item in enumerate(items) if getattr(item, "hq_pixmap", None)
        }
        self._loaded_embedded_indices = {
            i for i, item in enumerate(items) if getattr(item, "embedded_pixmap", None)
        }

        # Update last selected index based on current selection
        selected = [i for i, item in enumerate(items) if item.is_selected]
        if selected and previous_anchor_path is not None:
            anchor_idx = self.get_index_for_path(previous_anchor_path)
            if anchor_idx is not None and self.items_data[anchor_idx].is_selected:
                self._set_selection_anchor(anchor_idx)
            else:
                self._set_selection_anchor(selected[-1])
        elif selected:
            self._set_selection_anchor(selected[-1])
        else:
            self._set_selection_anchor(-1)

        if fast_first_paint:
            self._begin_fast_first_paint()

        rendered_via_scroll = self._recalculate_scrollbar()
        if not rendered_via_scroll:
            self._render_current_view()

        if perf_enabled:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            logger.debug(
                "Grid set_data completed: items=%d fast_first=%s rendered_via_scroll=%s total=%.1fms",
                len(items),
                fast_first_paint,
                rendered_via_scroll,
                elapsed_ms,
            )

    def get_index_for_path(self, path: str) -> int | None:
        for i, item in enumerate(self.items_data):
            if item.path == path:
                return i
        return None

    def get_viewport_visible_indices(self) -> list[int]:
        if not self.items_data or self.n_cols <= 0 or self.n_rows <= 0:
            return []
        start_idx = int(self.scrollbar.value()) * self.n_cols
        end_idx = min(len(self.items_data), start_idx + (self.n_rows * self.n_cols))
        return list(range(start_idx, end_idx))

    def get_viewport_visible_paths(self) -> list[str]:
        return [self.items_data[i].path for i in self.get_viewport_visible_indices()]

    def get_viewport_selected_paths(self) -> list[str]:
        result: list[str] = []
        for i in self.get_viewport_visible_indices():
            item = self.items_data[i]
            if item.is_selected:
                result.append(item.path)
        return result

    def refresh_visible_selection_only(self) -> None:
        """Refresh only visible cell selection highlights."""
        if not self.cells or not self.items_data:
            return

        start_idx = int(self.scrollbar.value()) * self.n_cols
        for i, cell in enumerate(self.cells):
            data_index = start_idx + i
            if 0 <= data_index < len(self.items_data):
                cell.set_selected_state(bool(self.items_data[data_index].is_selected))
            else:
                cell.set_selected_state(False)

    def select_paths(
        self,
        paths: list[str],
        *,
        anchor_path: str | None = None,
    ) -> set[int]:
        path_set = set(paths)
        selected_indices: set[int] = set()
        for i, item in enumerate(self.items_data):
            item.is_selected = item.path in path_set
            if item.is_selected:
                selected_indices.add(i)

        anchor_index = None
        if anchor_path is not None:
            idx = self.get_index_for_path(anchor_path)
            if idx is not None and idx in selected_indices:
                anchor_index = idx

        if anchor_index is None:
            for path in reversed(paths):
                idx = self.get_index_for_path(path)
                if idx is not None and idx in selected_indices:
                    anchor_index = idx
                    break

        if anchor_index is None:
            if selected_indices:
                anchor_index = max(selected_indices)
            else:
                anchor_index = -1

        self._set_selection_anchor(anchor_index)
        self.selection_changed.emit(selected_indices)
        self._render_current_view()
        return selected_indices

    def _set_selection_anchor(self, index: int) -> None:
        if 0 <= index < len(self.items_data):
            self._last_selected_index = index
            self._last_selected_path = self.items_data[index].path
        else:
            self._last_selected_index = -1
            self._last_selected_path = None

    def _choose_anchor_from_current_selection(self) -> int:
        if not self.items_data:
            return -1

        if self._last_selected_path is not None:
            idx = self.get_index_for_path(self._last_selected_path)
            if idx is not None and self.items_data[idx].is_selected:
                return idx

        if 0 <= self._last_selected_index < len(self.items_data):
            if self.items_data[self._last_selected_index].is_selected:
                return self._last_selected_index

        selected = [i for i, item in enumerate(self.items_data) if item.is_selected]
        return selected[-1] if selected else -1

    def set_num_columns(self, num_columns: int) -> None:
        cols = max(1, int(num_columns))
        if cols == self.n_cols:
            return
        self._rebuild_grid(self.n_rows, cols)

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
        rendered_via_scroll = self._recalculate_scrollbar()
        if not rendered_via_scroll:
            self._render_current_view()

    def _calculate_metadata_height(self) -> int:
        """Calculate the height needed for metadata display."""
        font = QFont()
        font.setPointSize(int(get_runtime_setting(RuntimeSettingKey.FONT_SIZE)))
        fm = QFontMetrics(font)
        line_height = fm.lineSpacing()

        # Count lines: 1 for filename + 1 per configured field (excluding label)
        num_lines = 1  # filename
        for field in get_runtime_setting(RuntimeSettingKey.GRID_ITEM_FIELDS):
            if field != DBFields.LABEL:  # Label is swatch, not text line
                num_lines += 1

        top_padding = int(
            get_runtime_setting(RuntimeSettingKey.GRID_ITEM_TEXT_FIELDS_TOP_PADDING)
        )
        return num_lines * line_height + top_padding

    def resizeEvent(self, event):
        # Width available for the grid (Total width - Scrollbar width)
        sb_width = self.scrollbar.width() if self.scrollbar.isVisible() else 0
        panel_w = event.size().width() - sb_width
        panel_h = event.size().height()

        cols = max(1, int(self.n_cols))
        pad = int(get_runtime_setting(RuntimeSettingKey.PADDING))

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
            rendered_via_scroll = self._recalculate_scrollbar()
            # Just refresh content in case data range changed due to scroll limit
            # changes.
            if not rendered_via_scroll:
                self._render_current_view()

        super().resizeEvent(event)

    def _recalculate_scrollbar(self) -> bool:
        """Recalculate scrollbar limits.

        Returns:
            True when setRange clamped the current value and triggered a render via
            valueChanged/on_scroll.
        """
        total_items = len(self.items_data)
        if self.n_cols == 0:
            return False
        total_data_rows = math.ceil(total_items / self.n_cols)

        max_scroll = max(0, total_data_rows - self.n_rows)
        previous_value = int(self.scrollbar.value())

        self._suppress_scroll_navigation_activity = True
        try:
            self.scrollbar.setRange(0, max_scroll)
            self.scrollbar.setPageStep(self.n_rows)
        finally:
            self._suppress_scroll_navigation_activity = False

        # Visibility logic
        if total_data_rows <= self.n_rows:
            self.scrollbar.hide()
        else:
            self.scrollbar.show()

        return int(self.scrollbar.value()) != previous_value

    def on_scroll(self, value):
        if not self._suppress_scroll_navigation_activity:
            self._mark_navigation_activity()
        elif not self._is_lowres_only_mode() and not self._fast_first_paint_active:
            # Programmatic scroll changes (filter/sort restore, range clamping)
            # should not trigger temporary HQ->embedded demotion.
            self._hq_display_enabled = True
        self._render(int(value), allow_hq=self._allow_hq_now())

    def _is_lowres_only_mode(self) -> bool:
        return bool(get_runtime_setting(RuntimeSettingKey.GRID_LOWRES_ONLY))

    def _is_hq_delay_enabled(self) -> bool:
        if self._is_lowres_only_mode():
            return False
        return bool(get_runtime_setting(RuntimeSettingKey.GRID_HQ_THUMB_DELAY_ENABLED))

    def _allow_hq_now(self) -> bool:
        if self._is_lowres_only_mode():
            return False
        if self._fast_first_paint_active:
            return False
        return (not self._is_hq_delay_enabled()) or self._hq_display_enabled

    def _begin_fast_first_paint(self) -> None:
        """Render the next update quickly with embedded thumbs, then upgrade to HQ."""
        if self._is_lowres_only_mode():
            self._fast_first_paint_active = False
            self._hq_display_enabled = False
            return

        delay_ms = int(get_runtime_setting(RuntimeSettingKey.GRID_HQ_THUMB_LOAD_DELAY_MS))
        if delay_ms <= 0:
            self._fast_first_paint_active = False
            self._hq_display_enabled = True
            return

        self._fast_first_paint_active = True
        self._hq_display_enabled = False
        self._hq_idle_timer.start(delay_ms)

    def _restart_hq_idle_timer(self) -> None:
        delay_ms = int(
            get_runtime_setting(RuntimeSettingKey.GRID_HQ_THUMB_LOAD_DELAY_MS)
        )
        if delay_ms <= 0:
            self._hq_display_enabled = True
            return
        self._hq_idle_timer.start(delay_ms)

    def _mark_navigation_activity(self) -> None:
        self._fast_first_paint_active = False
        if not self._is_hq_delay_enabled():
            self._hq_display_enabled = True
            return
        self._hq_display_enabled = False
        self._restart_hq_idle_timer()

    def _on_hq_idle_timeout(self) -> None:
        self._fast_first_paint_active = False
        self._hq_display_enabled = True
        self._render(int(self.scrollbar.value()), allow_hq=True)

    def _render_current_view(self) -> None:
        self._render(int(self.scrollbar.value()), allow_hq=self._allow_hq_now())

    def _render(self, start_row: int, *, allow_hq: bool) -> None:
        perf_enabled = logger.isEnabledFor(logging.DEBUG)
        if perf_enabled:
            started = time.perf_counter()

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
        if perf_enabled:
            after_sync = time.perf_counter()

        if allow_hq:
            self._ensure_hq_pixmaps_loaded_in_range(buffer_start_idx, start_data_index)
            self._ensure_hq_pixmaps_loaded_in_range(visible_end_idx, buffer_end_idx)
        if perf_enabled:
            after_preload = time.perf_counter()

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
        if perf_enabled:
            after_paint = time.perf_counter()

        # During fast-first filter repaint, keep existing HQ pixmaps in memory so
        # viewport restore does not cause a temporary HQ->embedded->HQ flash.
        if not (self._fast_first_paint_active and not allow_hq):
            self._evict_hq_pixmaps_outside(buffer_start_idx, buffer_end_idx)
        emb_start, emb_end = self._embedded_buffer_index_range(start_row)
        self._evict_embedded_pixmaps_outside(emb_start, emb_end)
        if perf_enabled:
            after_evict = time.perf_counter()

        if buffered_paths != self._last_visible_paths:
            self._last_visible_paths = buffered_paths
            self.visible_paths_changed.emit(buffered_paths)
        if perf_enabled:
            after_visible_emit = time.perf_counter()
            logger.debug(
                "Grid render timings: row=%d allow_hq=%s visible=%d buffer=%d "
                "sync=%.1fms preload=%.1fms paint=%.1fms evict=%.1fms "
                "visible_emit=%.1fms total=%.1fms",
                start_row,
                allow_hq,
                max(0, visible_end_idx - start_data_index),
                max(0, buffer_end_idx - buffer_start_idx),
                (after_sync - started) * 1000.0,
                (after_preload - after_sync) * 1000.0,
                (after_paint - after_preload) * 1000.0,
                (after_evict - after_paint) * 1000.0,
                (after_visible_emit - after_evict) * 1000.0,
                (after_visible_emit - started) * 1000.0,
            )

    def _buffer_index_range(self, start_row: int) -> tuple[int, int]:
        """Return [start, end) data-index range to keep HQ pixmaps for."""
        buffer_rows = int(get_runtime_setting(RuntimeSettingKey.GRID_THUMB_BUFFER_ROWS))
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
        if not bool(getattr(item, "_cache_state_dirty", True)):
            return

        embedded_path, hq_path = self._cache_paths_for_item(item)
        base_name = os.path.splitext(os.path.basename(item.path))[0]
        thumb_dir = get_thumb_dir_for_folder(item.source_folder)
        legacy_embedded = Path(thumb_dir) / f"{base_name}_embedded.jpg"
        legacy_hq = Path(thumb_dir) / f"{base_name}_hq.jpg"

        has_hq = (not self._is_lowres_only_mode()) and (
            hq_path.exists() or legacy_hq.exists()
        )
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
        item._cache_state_dirty = False

    def _load_thumbnail_cache_pixmap(
        self,
        path: Path,
        *,
        runtime_key: RuntimeSettingKey,
    ) -> QPixmap:
        if not bool(get_runtime_setting(runtime_key)):
            return QPixmap(str(path))

        return load_pixmap_with_color_management(
            str(path),
            force_srgb=bool(get_user_setting(UserSettingKey.FORCE_SRGB)),
            screen_profile_mode=get_user_setting(UserSettingKey.SCREEN_COLOR_PROFILE),
            allow_profile_extract_fallback=False,
            prefer_pillow_extract=False,
        )

    def _ensure_embedded_pixmap_loaded(self, item) -> None:
        if item is None or getattr(item, "embedded_pixmap", None) is not None:
            return
        embedded_path, _ = self._cache_paths_for_item(item)
        if embedded_path.exists():
            item.embedded_pixmap = self._load_thumbnail_cache_pixmap(
                embedded_path,
                runtime_key=RuntimeSettingKey.COLOR_MANAGE_EMBEDDED_THUMBNAILS,
            )
        else:
            base_name = os.path.splitext(os.path.basename(item.path))[0]
            thumb_dir = get_thumb_dir_for_folder(item.source_folder)
            legacy_path = Path(thumb_dir) / f"{base_name}_embedded.jpg"
            if legacy_path.exists():
                item.embedded_pixmap = self._load_thumbnail_cache_pixmap(
                    legacy_path,
                    runtime_key=RuntimeSettingKey.COLOR_MANAGE_EMBEDDED_THUMBNAILS,
                )

        if (
            getattr(item, "embedded_pixmap", None) is not None
            and getattr(item, "_global_index", -1) >= 0
        ):
            self._loaded_embedded_indices.add(int(item._global_index))

    def _ensure_hq_pixmap_loaded(self, item) -> None:
        if item is None or getattr(item, "hq_pixmap", None) is not None:
            return
        _, hq_path = self._cache_paths_for_item(item)
        if hq_path.exists():
            item.hq_pixmap = self._load_thumbnail_cache_pixmap(
                hq_path,
                runtime_key=RuntimeSettingKey.COLOR_MANAGE_HQ_THUMBNAILS,
            )
        else:
            base_name = os.path.splitext(os.path.basename(item.path))[0]
            thumb_dir = get_thumb_dir_for_folder(item.source_folder)
            legacy_path = Path(thumb_dir) / f"{base_name}_hq.jpg"
            if legacy_path.exists():
                item.hq_pixmap = self._load_thumbnail_cache_pixmap(
                    legacy_path,
                    runtime_key=RuntimeSettingKey.COLOR_MANAGE_HQ_THUMBNAILS,
                )

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
        """Ensure the best available pixmap is loaded and set as item.pixmap.

        Applies EXIF orientation to the display pixmap so that paintEvent can
        draw it directly without per-paint allocation.
        """
        if item is None:
            return

        state = int(getattr(item, "state", 0))

        if state >= 1:
            self._ensure_embedded_pixmap_loaded(item)
        if allow_hq and state >= 2:
            self._ensure_hq_pixmap_loaded(item)

        # Delay mode only blocks new HQ loads. If HQ is already in memory, keep
        # showing it until evicted outside the buffered range.
        if (not self._is_lowres_only_mode()) and getattr(
            item, "hq_pixmap", None
        ) is not None:
            source = item.hq_pixmap
        else:
            source = item.embedded_pixmap

        # Only rebuild display pixmap if source or orientation changed.
        db_meta = item.db_metadata or {}
        orientation = db_meta.get(DBFields.ORIENTATION)
        if (
            source is not None
            and getattr(item, "_pixmap_source", None) is source
            and getattr(item, "_pixmap_orientation", None) == orientation
            and item.pixmap is not None
        ):
            return

        item._pixmap_source = source
        item._pixmap_orientation = orientation
        if source is not None:
            item.pixmap = apply_orientation_to_pixmap(source, orientation)
        else:
            item.pixmap = None

    def _embedded_buffer_index_range(self, start_row: int) -> tuple[int, int]:
        """Return [start, end) data-index range to keep embedded pixmaps for."""
        buffer_rows = int(
            get_runtime_setting(RuntimeSettingKey.GRID_EMBEDDED_BUFFER_ROWS)
        )
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

    def _evict_hq_pixmaps_outside(self, start_idx: int, end_idx: int) -> None:
        """Free HQ pixmaps outside [start_idx, end_idx)."""
        if not self._loaded_hq_indices:
            return

        to_drop = [i for i in self._loaded_hq_indices if not (start_idx <= i < end_idx)]
        for idx in to_drop:
            if 0 <= idx < len(self.items_data):
                item = self.items_data[idx]
                if getattr(item, "hq_pixmap", None) is not None:
                    # Invalidate display pixmap so it gets rebuilt from embedded
                    if getattr(item, "_pixmap_source", None) is item.hq_pixmap:
                        item.pixmap = None
                        item._pixmap_source = None
                    item.hq_pixmap = None
            self._loaded_hq_indices.discard(idx)

    def _evict_embedded_pixmaps_outside(self, start_idx: int, end_idx: int) -> None:
        """Free embedded pixmaps outside [start_idx, end_idx)."""
        if not self._loaded_embedded_indices:
            return

        to_drop = [
            i for i in self._loaded_embedded_indices if not (start_idx <= i < end_idx)
        ]
        for idx in to_drop:
            if 0 <= idx < len(self.items_data):
                item = self.items_data[idx]
                if getattr(item, "embedded_pixmap", None) is not None:
                    if getattr(item, "_pixmap_source", None) is item.embedded_pixmap:
                        item.pixmap = None
                        item._pixmap_source = None
                    item.embedded_pixmap = None
            self._loaded_embedded_indices.discard(idx)

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

    def invalidate_all_pixmap_caches(self) -> None:
        """Clear all loaded source/display pixmaps so they reload with new settings."""
        self._loaded_embedded_indices.clear()
        self._loaded_hq_indices.clear()
        for item in self.items_data:
            item.embedded_pixmap = None
            item.hq_pixmap = None
            item.pixmap = None
            if hasattr(item, "_pixmap_source"):
                item._pixmap_source = None
            if hasattr(item, "_pixmap_orientation"):
                item._pixmap_orientation = None

    def on_cell_clicked(self, global_index, is_shift, is_ctrl):
        # Empty cell clicked - clear selection
        if global_index == -1:
            for item in self.items_data:
                item.is_selected = False
            self._set_selection_anchor(-1)
            self.selection_changed.emit(set())
            self._render_current_view()
            return

        if is_ctrl:
            item = self.items_data[global_index]
            item.is_selected = not item.is_selected
            if item.is_selected:
                self._set_selection_anchor(global_index)
            elif self._last_selected_path == item.path:
                self._set_selection_anchor(self._choose_anchor_from_current_selection())
        elif is_shift:
            anchor_index = self._choose_anchor_from_current_selection()
            if anchor_index != -1:
                start = min(anchor_index, global_index)
                end = max(anchor_index, global_index)
                for i in range(start, end + 1):
                    self.items_data[i].is_selected = True
            self._set_selection_anchor(global_index)
        else:
            for item in self.items_data:
                item.is_selected = False
            self.items_data[global_index].is_selected = True
            self._set_selection_anchor(global_index)

        selected_indices = {
            i for i, item in enumerate(self.items_data) if item.is_selected
        }
        if not selected_indices:
            self._set_selection_anchor(-1)
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
            self._set_selection_anchor(global_index)

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

        # Handle navigation
        if len(selected_indices) > 1:
            # Multi-selection: anchor-based actions
            anchor_index = self._choose_anchor_from_current_selection()
            if anchor_index == -1:
                anchor_index = selected_indices[-1]

            collapse_shortcut = self._lookup_configured_shortcut(
                Shortcut.COLLAPSE_TO_LAST_SELECTED
            )
            if collapse_shortcut and match_shortcut_sequence(event, collapse_shortcut):
                self.on_cell_clicked(anchor_index, False, False)
                event.accept()
                return

            # Multi-selection: collapse and move
            if key == Qt.Key_Left:
                new_index = anchor_index - 1
            elif key == Qt.Key_Right:
                new_index = anchor_index + 1
            elif key == Qt.Key_Up:
                new_index = anchor_index - self.n_cols
            elif key == Qt.Key_Down:
                new_index = anchor_index + self.n_cols
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

    def _set_scrollbar_value(self, value: int, *, navigation_activity: bool = True) -> None:
        if navigation_activity:
            self.scrollbar.setValue(value)
            return
        self._suppress_scroll_navigation_activity = True
        try:
            self.scrollbar.setValue(value)
        finally:
            self._suppress_scroll_navigation_activity = False

    def _ensure_visible(self, index, *, navigation_activity: bool = True):
        """Scrolls the grid if the index is out of view."""
        # Calculate the row this item belongs to
        target_row = index // self.n_cols

        current_top_row = self.scrollbar.value()
        # The last fully visible row index
        current_bottom_row = current_top_row + self.n_rows - 1

        if target_row < current_top_row:
            # Item is above view -> Scroll Up to make it the top row
            self._set_scrollbar_value(
                target_row, navigation_activity=navigation_activity
            )
        elif target_row > current_bottom_row:
            # Item is below view -> Scroll Down to make it the bottom row
            # Logic: New Top = Target Row - (Visible Rows - 1)
            new_top = target_row - self.n_rows + 1
            self._set_scrollbar_value(new_top, navigation_activity=navigation_activity)
