from __future__ import annotations

import atexit
from datetime import datetime
import logging
import math
import os
import sys
import threading

# TODO refactor : add variable to indicate loading
# OR assumes it is going to be on macos for now
if sys.platform == "darwin":
    import AppKit

from functools import partial

from PySide6.QtCore import QPointF, QRect, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QKeyEvent,
    QKeySequence,
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
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QScrollBar,
    QShortcut,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .config import Config, Shortcut
from .db_fields import EDITABLE_FIELDS, DBFields
from .edit_panel import EditPanel
from .exif_loader import ExifLoaderManager
from .exif_man import ExifManager, ExifPanel
from .filter_panel import FolderFilterPanel
from .metadata_db import MetadataDBManager
from .model import ImageItem, OnFullscreenExitMultipleSelected
from .status_bar import ErrorListDialog, LoadingStatusBar
from .support import save_last_folder
from .thumb_man import ThumbnailManager, scan_folder

logger = logging.getLogger(__name__)

# Map of modifier name => Qt modifier flag
_MODIFIER_MAP = {
    "ctrl": Qt.ControlModifier,
    "alt": Qt.AltModifier,
    "cmd": Qt.MetaModifier,
    "meta": Qt.MetaModifier,
    "shift": Qt.ShiftModifier,
}

# Map of special key name => Qt.Key
_SPECIAL_KEY_MAP = {
    "=": Qt.Key_Equal,
    "-": Qt.Key_Minus,
    "`": Qt.Key_QuoteLeft,
    "0": Qt.Key_0,
    "1": Qt.Key_1,
    "2": Qt.Key_2,
    "3": Qt.Key_3,
    "4": Qt.Key_4,
    "5": Qt.Key_5,
    "6": Qt.Key_6,
    "7": Qt.Key_7,
    "8": Qt.Key_8,
    "9": Qt.Key_9,
}


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


def _match_shortcut(event: QKeyEvent, shortcut_str: str) -> bool:
    """Check if a key event matches a shortcut string."""
    parts = [p.strip().lower() for p in shortcut_str.split("+")]
    key_str = parts[-1]
    modifier_names = parts[:-1]

    # Build expected modifiers
    expected_mods = Qt.KeyboardModifier(0)
    for mod_name in modifier_names:
        if mod_name in _MODIFIER_MAP:
            expected_mods |= _MODIFIER_MAP[mod_name]

    # Get expected key
    if key_str in _SPECIAL_KEY_MAP:
        expected_key = _SPECIAL_KEY_MAP[key_str]
    elif len(key_str) == 1:
        expected_key = getattr(Qt, f"Key_{key_str.upper()}", None)
        if expected_key is None:
            return False
    else:
        expected_key = getattr(Qt, f"Key_{key_str.capitalize()}", None)
        if expected_key is None:
            return False

    return event.key() == expected_key and event.modifiers() == expected_mods


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

        # Label color swatch
        self._update_color_swatch()

        # Reposition and show
        self.info_panel.adjustSize()
        self._position_info_panel()
        self.info_panel.show()

    def _update_color_swatch(self):
        """Update the color swatch based on the current image's label."""
        global_index = self.visible_indices[self.current_visible_idx]
        if 0 <= global_index < len(self.all_items):
            item = self.all_items[global_index]
            db_meta = item.db_metadata or {}
            label = db_meta.get(DBFields.LABEL)
            if label:
                color = _get_label_color(label)
                if color:
                    self.color_swatch.setStyleSheet(f"background-color: {color};")
                    self.color_swatch.show()
                else:
                    self.color_swatch.hide()
            else:
                self.color_swatch.hide()

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
        elif _match_shortcut(event, Config.SHORTCUTS.get(Shortcut.ZOOM_IN, "=")):
            # Zoom in centered on screen center
            center = QPointF(self.width() / 2.0, self.height() / 2.0)
            scaled_pixmap = self._get_base_scaled_pixmap()
            base_x = (self.rect().width() - scaled_pixmap.width()) / 2
            base_y = (self.rect().height() - scaled_pixmap.height()) / 2
            center_pos = center - QPointF(base_x, base_y)
            self._zoom_in(center_pos)
        elif _match_shortcut(event, Config.SHORTCUTS.get(Shortcut.ZOOM_OUT, "-")):
            # Zoom out centered on screen center
            center = QPointF(self.width() / 2.0, self.height() / 2.0)
            scaled_pixmap = self._get_base_scaled_pixmap()
            base_x = (self.rect().width() - scaled_pixmap.width()) / 2
            base_y = (self.rect().height() - scaled_pixmap.height()) / 2
            center_pos = center - QPointF(base_x, base_y)
            self._zoom_out(center_pos)
        elif _match_shortcut(event, Config.SHORTCUTS.get(Shortcut.ZOOM_RESET, "0")):
            # Reset zoom
            self._transform.reset()
            self._zoom_level = 1.0
            self.update()
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
                field_rect = QRect(
                    text_rect.left(),
                    text_rect.top() + y_offset,
                    text_rect.width(),
                    line_height,
                )
                elided_value = font_metrics.elidedText(
                    str(value), Qt.ElideRight, text_rect.width()
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
