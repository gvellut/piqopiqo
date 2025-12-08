import atexit
from datetime import datetime
import logging
import math
import os
import sys

# TODO refactor : add variable to indicate loading
if sys.platform == "darwin":
    import AppKit

from PySide6.QtCore import QPointF, QRect, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QPixmap,
    QScreen,
    QTransform,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.config import Config
from piqopiqo.model import ImageItem, OnFullscreenExitMultipleSelected
from piqopiqo.thumb_man import ThumbnailManager

logger = logging.getLogger(__name__)


class FullscreenOverlay(QWidget):
    """A fullscreen overlay widget for displaying an image at full resolution."""

    # Signal to notify when the current index changes
    index_changed = Signal(int)

    def __init__(self, all_items: list, visible_indices: list, start_index: int):
        super().__init__()
        self.all_items = all_items
        self.visible_indices = visible_indices
        self.current_visible_idx = self.visible_indices.index(start_index)
        self._prev_presentation_opts = None

        self._transform = QTransform()
        self._zoom_level = 1.0
        self._panning = False
        self._pan_start_pos = QPointF()

        self._wheel_acc = 0

        self._setup_info_panel()

        # Load the initial image
        self._load_current_image()

        # Window setup
        # CHANGE 1: Use Qt.Window instead of Qt.Tool to ensure it acts as a standalone
        # top-level window that can accept focus reliably on macOS.
        self.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )

        self.setAttribute(Qt.WA_DeleteOnClose)

        bg_color = Config.FULLSCREEN_BACKGROUND_COLOR
        self.setStyleSheet(f"background-color: {bg_color};")
        self._background_color = QColor(bg_color)

        # ADDED: Register safety cleanup
        atexit.register(self.restore_macos_ui)

    def _setup_info_panel(self):
        """Creates and configures the information panel."""
        self.info_panel = QFrame(self)
        self.info_panel.setObjectName("infoPanel")
        self.info_panel.setFrameShape(QFrame.StyledPanel)
        self.info_panel.setFrameShadow(QFrame.Raised)
        self.info_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Layout for the panel
        panel_layout = QHBoxLayout(self.info_panel)
        panel_layout.setContentsMargins(10, 5, 10, 5)
        panel_layout.setSpacing(10)

        # Filename Label
        self.filename_label = QLabel(self)
        panel_layout.addWidget(self.filename_label)

        # Date Label
        self.date_label = QLabel(self)
        panel_layout.addWidget(self.date_label)

        # Color Swatch
        self.color_swatch = QWidget(self)
        self.color_swatch.setFixedSize(20, 20)
        self.color_swatch.setStyleSheet("background-color: red;")
        panel_layout.addWidget(self.color_swatch)

        self.info_panel.setLayout(panel_layout)

        # Set panel stylesheet
        bg_color = QColor(Config.INFO_PANEL_BACKGROUND_COLOR)
        alpha = int(255 * (Config.INFO_PANEL_BACKGROUND_TRANSPARENCY / 100.0))
        bg_color.setAlpha(alpha)

        text_color = Config.INFO_PANEL_TEXT_COLOR
        bg_color = (
            f"rgba({bg_color.red()}, {bg_color.green()}, {bg_color.blue()}, "
            f"{bg_color.alpha()})"
        )
        self.info_panel.setStyleSheet(
            f"""
            #infoPanel {{
                background-color: {bg_color};
                border-radius: 5px;
            }}
            QLabel {{
                color: {text_color};
                background-color: transparent;
            }}
        """
        )

    def _update_info_panel(self):
        """Updates the content of the info panel based on the current image."""
        if not hasattr(self, "info_panel") or not self.image_path:
            return

        # Filename
        filename = os.path.basename(self.image_path)
        self.filename_label.setText(filename)

        # Filesystem Date
        try:
            mtime = os.path.getmtime(self.image_path)
            date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            self.date_label.setText(date_str)
        except OSError as e:
            logger.error(f"Could not get modification date for {self.image_path}: {e}")
            self.date_label.setText("Unknown Date")

        # Reposition and show
        self.info_panel.adjustSize()
        self._position_info_panel()
        self.info_panel.show()

    def _position_info_panel(self):
        """Positions the panel in the bottom-left corner."""
        if hasattr(self, "info_panel"):
            margin = 10  # Margin from the window edges
            self.info_panel.move(
                margin, self.height() - self.info_panel.height() - margin
            )

    def _load_current_image(self):
        """Load the image at the current index and reset zoom/pan state."""
        # Reset transformation state
        self._transform.reset()
        self._zoom_level = 1.0
        self._panning = False
        self._pan_start_pos = QPointF()

        global_index = self.visible_indices[self.current_visible_idx]
        if 0 <= global_index < len(self.all_items):
            image_data = self.all_items[global_index]
            self.image_path = image_data.path
            if self.image_path:
                self._pixmap = QPixmap(self.image_path)
                if self._pixmap.isNull():
                    logger.warning(f"Failed to load image: {self.image_path}")
                    self._pixmap = QPixmap()  # Fallback to empty pixmap
                self._update_info_panel()
                self.update()

    def _navigate_to(self, new_visible_idx: int):
        """Navigate to a new image index within the visible set."""
        total_visible = len(self.visible_indices)
        if total_visible == 0:
            return

        new_visible_idx = (
            new_visible_idx % total_visible + total_visible
        ) % total_visible

        if new_visible_idx != self.current_visible_idx:
            self.current_visible_idx = new_visible_idx
            self._load_current_image()
            global_index = self.visible_indices[self.current_visible_idx]
            self.index_changed.emit(global_index)

    def show_on_screen(self, target_screen: QScreen):
        """Moves the overlay to the specific screen and shows it fullscreen."""

        # 1. Hide macOS Chrome (Menu Bar & Dock) strictly
        self.hide_macos_ui()

        # 2. Move window to the target screen
        self.setScreen(target_screen)

        # CHANGE: Show the window FIRST.
        # If we setGeometry before show(), macOS constrains the window
        # to the 'available' area (excluding dock/menu).
        # Showing it first creates the window, then we stretch it.
        self.show()

        # 3. Force geometry to the screen's full geometry manually
        rect = target_screen.geometry()
        self.setGeometry(rect)

        # Redundant safety: explicitly set size and position to ensure
        # Qt applies the update even if it thinks the geometry hasn't changed.
        self.resize(rect.size())
        self.move(rect.topLeft())

        # 4. Force focus
        self.raise_()
        self.activateWindow()
        self.setFocus()

    # --- ADDED: macOS Specific Logic ---
    def hide_macos_ui(self):
        """Uses AppKit to strictly hide Dock and Menu Bar."""
        if sys.platform != "darwin":
            return
        app = AppKit.NSApplication.sharedApplication()

        # Save current options to restore later
        self._prev_presentation_opts = app.presentationOptions()

        # Options to hide Dock and Menu Bar nicely
        new_opts = (
            AppKit.NSApplicationPresentationHideDock
            | AppKit.NSApplicationPresentationHideMenuBar
        )
        app.setPresentationOptions_(new_opts)

    def restore_macos_ui(self):
        """Restores the Menu Bar and Dock."""
        if sys.platform != "darwin":
            return
        if self._prev_presentation_opts is None:
            return

        app = AppKit.NSApplication.sharedApplication()
        app.setPresentationOptions_(self._prev_presentation_opts)
        self._prev_presentation_opts = None

    def closeEvent(self, event):
        """Handle window closing."""
        self.restore_macos_ui()  # Restore UI when closed
        super().closeEvent(event)

    # -----------------------------------

    def paintEvent(self, event: QPaintEvent):
        """Custom painting to handle aspect ratio, letterboxing, zoom, and pan."""
        super().paintEvent(event)
        self._position_info_panel()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # Fill background
        painter.fillRect(self.rect(), self._background_color)

        if self._pixmap.isNull():
            return

        # --- Base Image Positioning (Letterboxing) ---
        scaled_pixmap = self._get_base_scaled_pixmap()

        # Calculate the centered position of the scaled pixmap
        target_rect = self.rect()
        base_x = (target_rect.width() - scaled_pixmap.width()) / 2
        base_y = (target_rect.height() - scaled_pixmap.height()) / 2

        # --- Apply Zoom and Pan Transformation ---
        painter.save()

        # The base position is now the origin for transformations
        painter.translate(base_x, base_y)

        # Apply the current zoom/pan transform
        painter.setTransform(self._transform, combine=True)

        # Draw the scaled pixmap at the new origin (0,0)
        painter.drawPixmap(0, 0, scaled_pixmap)

        painter.restore()

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard events to dismiss the overlay and navigate images."""
        key = event.key()

        if key in (Qt.Key_Escape, Qt.Key_Space):
            self.close()
        elif key == Qt.Key_Left:
            self._navigate_to(self.current_visible_idx - 1)
        elif key == Qt.Key_Right:
            self._navigate_to(self.current_visible_idx + 1)
        elif key in (Qt.Key_Up, Qt.Key_Down):
            # Ignore up/down keys in fullscreen
            pass
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        """Handle mouse wheel events for zooming."""
        self._wheel_acc += event.angleDelta().y()

        if abs(self._wheel_acc) >= 120 * Config.ZOOM_WHEEL_SENSITIVITY:
            scaled_pixmap = self._get_base_scaled_pixmap()
            base_x = (self.rect().width() - scaled_pixmap.width()) / 2
            base_y = (self.rect().height() - scaled_pixmap.height()) / 2

            # Translate mouse position to image's coordinate space
            center_pos = event.position() - QPointF(base_x, base_y)

            # Clamp to image rect
            img_rect = scaled_pixmap.rect()
            if not img_rect.contains(center_pos.toPoint()):
                center_pos.setX(
                    max(img_rect.left(), min(center_pos.x(), img_rect.right()))
                )
                center_pos.setY(
                    max(img_rect.top(), min(center_pos.y(), img_rect.bottom()))
                )

            if self._wheel_acc > 0:
                self._zoom_in(center_pos)
            else:
                self._zoom_out(center_pos)

            self._wheel_acc = 0

    def _get_base_scaled_pixmap(self):
        """Calculates the base scaled pixmap."""
        target_rect = self.rect()
        pixmap_size = self._pixmap.size()

        if (
            pixmap_size.width() <= target_rect.width()
            and pixmap_size.height() <= target_rect.height()
        ):
            return self._pixmap
        else:
            return self._pixmap.scaled(
                target_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )

    def _zoom_in(self, center_pos):
        """Zoom in, centered on the given position."""
        if self._zoom_level >= Config.ZOOM_MAX:
            logging.debug("Already at max zoom level.")
            return

        base_scaled_pixmap = self._get_base_scaled_pixmap()
        real_size_zoom = self._pixmap.width() / base_scaled_pixmap.width()

        factor = Config.ZOOM_FACTOR
        next_zoom_level = self._zoom_level * factor

        if self._zoom_level < real_size_zoom and next_zoom_level > real_size_zoom:
            factor = real_size_zoom / self._zoom_level
            self._zoom_level = real_size_zoom
            logging.debug("Snapped to real size zoom")
        else:
            self._zoom_level = next_zoom_level

        if self._zoom_level > Config.ZOOM_MAX:
            self._zoom_level = Config.ZOOM_MAX

        self._apply_zoom(factor, center_pos)

    def _zoom_out(self, center_pos):
        """Zoom out, centered on the given position."""
        if self._zoom_level <= 1.0:
            logging.debug("Already at base zoom level.")
            return

        base_scaled_pixmap = self._get_base_scaled_pixmap()
        real_size_zoom = self._pixmap.width() / base_scaled_pixmap.width()

        factor = 1.0 / Config.ZOOM_FACTOR
        next_zoom_level = self._zoom_level * factor

        if self._zoom_level > real_size_zoom and next_zoom_level < real_size_zoom:
            factor = real_size_zoom / self._zoom_level
            self._zoom_level = real_size_zoom
            logging.debug("Snapped to real size zoom")
        else:
            self._zoom_level = next_zoom_level

        if self._zoom_level < 1.0:
            self._zoom_level = 1.0

        if self._zoom_level == 1.0:
            self._transform.reset()
            self.update()
        else:
            self._apply_zoom(factor, center_pos)

    def _apply_zoom(self, factor, center_pos):
        """Apply zoom transformation."""
        transform = QTransform()
        transform.translate(center_pos.x(), center_pos.y())
        transform.scale(factor, factor)
        transform.translate(-center_pos.x(), -center_pos.y())
        self._transform = self._transform * transform
        logging.debug(f"Zoom level updated to: {self._zoom_level}")
        self._clamp_pan()
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press events to initiate panning."""
        if event.button() == Qt.LeftButton and self._zoom_level > 1.0:
            self._panning = True
            self._pan_start_pos = event.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move events to perform panning."""
        if not self._panning:
            return

        delta = event.position() - self._pan_start_pos
        self._pan_start_pos = event.position()

        # Apply the translation
        self._transform.translate(
            delta.x() / self._zoom_level, delta.y() / self._zoom_level
        )

        # Clamp immediately to prevent going beyond boundaries during drag
        self._clamp_pan_smooth()
        self.update()

    def _get_effective_empty_space(self):
        """Calculate the effective empty space around the image at current zoom
        level."""
        scaled_pixmap = self._get_base_scaled_pixmap()
        view_rect = self.rect()

        # 1. Configured empty space, scaled to the current view
        if self._pixmap.width() > 0:
            base_scale = scaled_pixmap.width() / self._pixmap.width()
            configured_empty_space = (
                Config.PAN_EMPTY_SPACE * base_scale * self._zoom_level
            )
        else:
            configured_empty_space = 0

        # 2. Size of the initial black bars (scaled with zoom to avoid discontinuity)
        # The black bars represent the letterbox area at zoom_level=1.0
        # As we zoom in, this area should also scale proportionally
        black_bar_x = (
            max(0, (view_rect.width() - scaled_pixmap.width()) / 2) * self._zoom_level
        )
        black_bar_y = (
            max(0, (view_rect.height() - scaled_pixmap.height()) / 2) * self._zoom_level
        )

        # The effective empty space is the larger of the two for each axis
        effective_h_space = max(configured_empty_space, black_bar_x)
        effective_v_space = max(configured_empty_space, black_bar_y)

        return effective_h_space, effective_v_space

    def _clamp_pan_smooth(self):
        """Smoothly clamps panning during drag to prevent going beyond boundaries."""
        scaled_pixmap = self._get_base_scaled_pixmap()
        view_rect = self.rect()
        base_x = (view_rect.width() - scaled_pixmap.width()) / 2
        base_y = (view_rect.height() - scaled_pixmap.height()) / 2

        # Get current image position
        final_img_rect = self._transform.mapRect(scaled_pixmap.rect()).translated(
            base_x, base_y
        )

        effective_h_space, effective_v_space = self._get_effective_empty_space()

        # Calculate required corrections
        dx = 0
        if final_img_rect.width() < view_rect.width():
            dx = view_rect.center().x() - final_img_rect.center().x()
        elif final_img_rect.left() > effective_h_space:
            dx = effective_h_space - final_img_rect.left()
        elif final_img_rect.right() < view_rect.width() - effective_h_space:
            dx = view_rect.width() - effective_h_space - final_img_rect.right()

        dy = 0
        if final_img_rect.height() < view_rect.height():
            dy = view_rect.center().y() - final_img_rect.center().y()
        elif final_img_rect.top() > effective_v_space:
            dy = effective_v_space - final_img_rect.top()
        elif final_img_rect.bottom() < view_rect.height() - effective_v_space:
            dy = view_rect.height() - effective_v_space - final_img_rect.bottom()

        # Apply corrections immediately (no update() call to avoid extra redraws)
        if dx or dy:
            self._transform.translate(dx / self._zoom_level, dy / self._zoom_level)

    def _clamp_pan(self):
        """Clamps the panning transformation to stay within the defined boundaries."""
        # This is now just a wrapper that calls the smooth version and triggers update
        self._clamp_pan_smooth()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release events to stop panning."""
        if event.button() == Qt.LeftButton and self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            self._clamp_pan()


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
        date = self.current_data.created
        state = self.current_data.state
        pixmap = self.current_data.pixmap

        # Unpack Layout Info (computed in parent resizeEvent)
        pad = self.layout_info.get("pad", 5)
        # Note: In the grid layout, the widget's rect() is the cell size.
        # We rely on rect() for the actual dimensions, but use layout_info for internal
        # proportions if needed.
        # However, to strictly follow the user's logic, we use the metrics derived.

        meta_h = self.layout_info.get("meta_h", 20)

        # Logic from PhotoDelegate.paint

        # Image Rect
        # Adjusted: left, top, right, bottom
        img_rect = rect.adjusted(pad, pad, -pad, -(pad + meta_h))

        if state == 0:
            painter.fillRect(img_rect, QColor("black"))
            # Lazy load request is handled in the Grid on_scroll, not paint
        else:
            if pixmap:
                # Center pixmap
                pixmap_rect = pixmap.rect()
                pixmap_rect.moveCenter(img_rect.center())

                # Check if scaling is needed (if pixmap is larger than rect or specific
                # fit mode)
                # The user's code just did: pixmap_rect.moveCenter(img_rect.center())
                # and draw.
                # Usually we want to scale to fit if it's too big:
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

        # Text
        # Logic: text_rect = option.rect.adjusted(pad, pad + img_rect_h, -pad, -pad)
        # Since img_rect_h is dynamic in the user's logic, we calculate the text area
        # from the bottom up
        text_rect = QRect(
            rect.left() + pad,
            rect.bottom() - meta_h - pad,
            rect.width() - (2 * pad),
            meta_h,
        )

        painter.setPen(QPen(Qt.white))

        # Filename
        font_metrics = painter.fontMetrics()
        elided_name = font_metrics.elidedText(name, Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignTop | Qt.AlignHCenter, elided_name)

        # Date
        painter.drawText(text_rect, Qt.AlignBottom | Qt.AlignHCenter, date)

        # Draw red border around item
        painter.setPen(QPen(QColor("red"), 2))
        painter.drawRect(rect.adjusted(1, 1, -1, -1))


class PagedPhotoGrid(QWidget):
    request_thumb = Signal(int)
    selection_changed = Signal(set)
    request_fullscreen = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)

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

    def resizeEvent(self, event):
        # Math ported identically from User's PhotoGrid.resizeEvent

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

        # Vertical Calculation
        meta_h = (cfg.METADATA_LINES * cfg.FONT_SIZE) + pad
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


class MainWindow(QMainWindow):
    def __init__(self, images):
        super().__init__()
        self.setWindowTitle(Config.APP_NAME)
        self.showMaximized()

        self._fullscreen_overlay = None

        self._create_menu_bar()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.grid = PagedPhotoGrid()
        layout.addWidget(self.grid)

        self.thumb_manager = ThumbnailManager()
        self.thumb_manager.thumb_ready.connect(self.on_thumb_ready)

        self.grid.request_thumb.connect(self.request_thumb_handler)
        self.grid.request_fullscreen.connect(self._handle_fullscreen_overlay)

        self.images_data = [ImageItem(**data) for data in images]
        self.grid.set_data(self.images_data)

    def _create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

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

        open_action = QAction("Open...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.on_open)
        file_menu.addAction(open_action)

    def on_about(self):
        pass

    def on_settings(self):
        pass

    def on_open(self):
        pass

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

    def request_thumb_handler(self, index):
        if 0 <= index < len(self.images_data):
            file_path = self.images_data[index].path
            self.thumb_manager.queue_image(file_path)

    def _get_physical_resolution(self, screen: QScreen) -> tuple[int, int]:
        """Calculates physical resolution based on logical size and pixel density."""
        geometry = screen.geometry()
        dpr = screen.devicePixelRatio()

        phy_width = int(geometry.width() * dpr)
        phy_height = int(geometry.height() * dpr)

        return phy_width, phy_height

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
        phy_w, phy_h = self._get_physical_resolution(current_screen)

        logger.debug(f"Screen Detected: {current_screen.name()}")
        logger.debug(f"Logical Size: {log_geo.width()} x {log_geo.height()}")
        logger.debug(f"Device Pixel Ratio: {dpr}")
        logger.debug(f"Physical Resolution: {phy_w} x {phy_h}")

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
        self.thumb_manager.stop()
        super().closeEvent(event)
