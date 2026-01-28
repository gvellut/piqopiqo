"""Fullscreen overlay for displaying images at full resolution with zoom/pan support."""

from __future__ import annotations

import atexit
from datetime import datetime
import logging
import sys

if sys.platform == "darwin":
    import AppKit

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
    QScreen,
    QTransform,
)
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .config import Config, Shortcut
from .db_fields import DBFields

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


def _get_label_color(label: str) -> str | None:
    """Get color hex for a label name from STATUS_LABELS."""
    for sl in Config.STATUS_LABELS:
        if sl.name == label:
            return sl.color
    return None


class ZoomDirection:
    """Enum-like class for zoom direction tracking."""

    NONE = "none"  # Initial state or reset
    IN = "in"  # Zooming in
    OUT = "out"  # Zooming out


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

        # Zoom overlay state
        self._is_base_view = True  # True when at base scale (fit to screen)
        self._zoom_direction = ZoomDirection.NONE  # Track zoom direction
        self._overlay_timer = QTimer(self)
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.timeout.connect(self._hide_zoom_overlay)
        self._show_zoom_overlay = False

        # Device pixel ratio for this screen (will be set in show_on_screen)
        self._device_pixel_ratio = 1.0

        self._setup_info_panel()
        self._setup_zoom_overlay()

        # Load the initial image
        self._load_current_image()

        # Window setup
        self.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )

        self.setAttribute(Qt.WA_DeleteOnClose)

        bg_color = Config.FULLSCREEN_BACKGROUND_COLOR
        self.setStyleSheet(f"background-color: {bg_color};")
        self._background_color = QColor(bg_color)

        # Register safety cleanup
        atexit.register(self.restore_macos_ui)

    def _setup_zoom_overlay(self):
        """Creates the zoom level overlay widget."""
        self.zoom_overlay = QLabel(self)
        self.zoom_overlay.setObjectName("zoomOverlay")

        # Style the overlay
        font = QFont()
        font.setPointSize(24)
        font.setBold(True)
        self.zoom_overlay.setFont(font)

        self.zoom_overlay.setStyleSheet(
            """
            QLabel#zoomOverlay {
                color: white;
                background-color: rgba(0, 0, 0, 150);
                padding: 10px 20px;
                border-radius: 8px;
            }
        """
        )
        self.zoom_overlay.hide()

    def _update_zoom_overlay(self):
        """Update and position the zoom overlay based on current zoom level."""
        # Calculate the zoom percentage relative to render buffer (1:1 pixel mapping)
        # 100% means 1 image pixel = 1 render buffer pixel
        # The base scale factor maps the image to fit the screen at zoom_level=1.0
        # We need to account for DPR when calculating the actual zoom percentage

        base_scale = self._get_base_scale_factor()
        # The actual scale in terms of render buffer pixels
        # At zoom_level=1.0, base_scale tells us how much the image is scaled
        # For 100%: image_pixel * base_scale * zoom_level * dpr = 1 render_buffer_pixel
        # So 100% zoom = 1 / (base_scale * dpr) in terms of zoom_level
        actual_zoom_pct = self._zoom_level * base_scale * self._device_pixel_ratio * 100

        self.zoom_overlay.setText(f"{actual_zoom_pct:.0f}%")
        self.zoom_overlay.adjustSize()

        # Center the overlay on screen
        overlay_x = (self.width() - self.zoom_overlay.width()) // 2
        overlay_y = (self.height() - self.zoom_overlay.height()) // 2
        self.zoom_overlay.move(overlay_x, overlay_y)

    def _should_show_zoom_overlay(self) -> bool:
        """Determine if the zoom overlay should be shown based on current state."""
        # Don't show at base view (unless we just zoomed out to it)
        if self._is_base_view:
            # Only show if we're returning to base view by zooming out
            return self._zoom_direction == ZoomDirection.OUT

        # Calculate if we're at 100% (1:1 pixel mapping with render buffer)
        base_scale = self._get_base_scale_factor()
        actual_zoom_pct = self._zoom_level * base_scale * self._device_pixel_ratio * 100

        # If at 100% zoom, only show if zooming out to it (not zooming in from base)
        if abs(actual_zoom_pct - 100.0) < 0.5:  # Within 0.5% of 100%
            # Don't show 100% when zooming in from base view
            if self._zoom_direction == ZoomDirection.IN:
                return False

        return True

    def _show_zoom_level(self):
        """Show the zoom overlay with auto-hide timer."""
        if self._should_show_zoom_overlay():
            self._update_zoom_overlay()
            self.zoom_overlay.show()
            self._show_zoom_overlay = True
            # Reset timer - hide after 1.5 seconds
            self._overlay_timer.start(1500)

    def _hide_zoom_overlay(self):
        """Hide the zoom overlay."""
        self.zoom_overlay.hide()
        self._show_zoom_overlay = False

    def _setup_info_panel(self):
        """Creates and configures the information panel."""
        self.info_panel = QFrame(self)
        self.info_panel.setObjectName("infoPanel")
        self.info_panel.setFrameShape(QFrame.StyledPanel)
        self.info_panel.setFrameShadow(QFrame.Raised)
        self.info_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Vertical layout: color swatch, filename, date
        panel_layout = QVBoxLayout(self.info_panel)
        panel_layout.setContentsMargins(10, 5, 10, 5)
        panel_layout.setSpacing(5)

        # Color Swatch (always occupies space, transparent when no label)
        self.color_swatch = QWidget(self)
        self.color_swatch.setFixedSize(20, 20)
        self.color_swatch.setStyleSheet("background-color: transparent;")
        panel_layout.addWidget(self.color_swatch)

        # Filename Label
        self.filename_label = QLabel(self)
        panel_layout.addWidget(self.filename_label)

        # Date Label
        self.date_label = QLabel(self)
        panel_layout.addWidget(self.date_label)

        self.info_panel.setLayout(panel_layout)

        # Set panel stylesheet
        bg_color = QColor(Config.INFO_PANEL_BACKGROUND_COLOR)
        alpha = int(255 * (Config.INFO_PANEL_BACKGROUND_TRANSPARENCY / 100.0))
        bg_color.setAlpha(alpha)

        text_color = Config.INFO_PANEL_TEXT_COLOR
        bg_color_str = (
            f"rgba({bg_color.red()}, {bg_color.green()}, {bg_color.blue()}, "
            f"{bg_color.alpha()})"
        )
        self.info_panel.setStyleSheet(
            f"""
            #infoPanel {{
                background-color: {bg_color_str};
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
        import os

        if not hasattr(self, "info_panel") or not self.image_path:
            return

        # Filename
        filename = os.path.basename(self.image_path)
        self.filename_label.setText(filename)

        # Date: prefer time_taken from metadata DB, fallback to filesystem date (in red)
        global_index = self.visible_indices[self.current_visible_idx]
        db_meta = (
            self.all_items[global_index].db_metadata or {}
            if 0 <= global_index < len(self.all_items)
            else {}
        )
        time_taken = db_meta.get(DBFields.TIME_TAKEN)
        if isinstance(time_taken, datetime):
            self.date_label.setText(time_taken.strftime("%Y-%m-%d %H:%M:%S"))
            self.date_label.setStyleSheet("color: white;")
        else:
            try:
                mtime = os.path.getmtime(self.image_path)
                date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                self.date_label.setText(date_str)
            except OSError as e:
                logger.error(
                    f"Could not get modification date for {self.image_path}: {e}"
                )
                self.date_label.setText("Unknown Date")
            self.date_label.setStyleSheet("color: red;")

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
                else:
                    self.color_swatch.setStyleSheet("background-color: transparent;")
            else:
                self.color_swatch.setStyleSheet("background-color: transparent;")

    def _position_info_panel(self):
        """Positions the panel on the left side, top or bottom per config."""
        if hasattr(self, "info_panel"):
            margin_edge = Config.INFO_PANEL_MARGIN_BOTTOM
            margin_side = Config.INFO_PANEL_MARGIN_SIDE
            if Config.INFO_PANEL_POSITION == "top":
                y = margin_edge
            else:
                y = self.height() - self.info_panel.height() - margin_edge
            self.info_panel.move(margin_side, y)

    def _load_current_image(self):
        """Load the image at the current index and reset zoom/pan state."""
        # Reset transformation state
        self._transform.reset()
        self._zoom_level = 1.0
        self._panning = False
        self._pan_start_pos = QPointF()

        # Reset zoom overlay state - entering base view
        self._is_base_view = True
        self._zoom_direction = ZoomDirection.NONE
        self._hide_zoom_overlay()

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

        # Get device pixel ratio before showing
        self._device_pixel_ratio = target_screen.devicePixelRatio()
        logger.debug(
            f"Screen DPR: {self._device_pixel_ratio}, "
            f"Logical size: {target_screen.size()}, "
            f"Render buffer: {target_screen.size().width() * self._device_pixel_ratio}x"
            f"{target_screen.size().height() * self._device_pixel_ratio}"
        )

        # Hide macOS Chrome (Menu Bar & Dock) strictly
        self.hide_macos_ui()

        # Move window to the target screen
        self.setScreen(target_screen)

        # Show the window FIRST.
        self.show()

        # Force geometry to the screen's full geometry manually
        rect = target_screen.geometry()
        self.setGeometry(rect)

        # Explicitly set size and position
        self.resize(rect.size())
        self.move(rect.topLeft())

        # Force focus
        self.raise_()
        self.activateWindow()
        self.setFocus()

    # --- macOS Specific Logic ---
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

    def _get_base_scale_factor(self) -> float:
        """Calculate the base scale factor to fit image to screen.

        Returns the scale factor that would be applied to fit the image
        within the screen bounds (1.0 if image fits without scaling).
        """
        if self._pixmap.isNull():
            return 1.0

        target_rect = self.rect()
        pixmap_size = self._pixmap.size()

        # If image fits on screen, no scaling needed
        if (
            pixmap_size.width() <= target_rect.width()
            and pixmap_size.height() <= target_rect.height()
        ):
            return 1.0

        # Calculate scale to fit
        scale_w = target_rect.width() / pixmap_size.width()
        scale_h = target_rect.height() / pixmap_size.height()
        return min(scale_w, scale_h)

    def _get_fit_scale_factor(self) -> float:
        """Calculate the scale factor to fit image to screen (always returns
        the fit scale, even if image is smaller than screen)."""
        if self._pixmap.isNull():
            return 1.0

        target_rect = self.rect()
        pixmap_size = self._pixmap.size()

        scale_w = target_rect.width() / pixmap_size.width()
        scale_h = target_rect.height() / pixmap_size.height()
        return min(scale_w, scale_h)

    def paintEvent(self, event: QPaintEvent):
        """Custom painting to handle aspect ratio, letterboxing, zoom, and pan.

        Rendering approach:
        - Always draw the full resolution pixmap
        - Apply scaling transformation to fit/zoom
        - This ensures proper quality at all zoom levels
        """
        super().paintEvent(event)
        self._position_info_panel()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # Fill background
        painter.fillRect(self.rect(), self._background_color)

        if self._pixmap.isNull():
            return

        # Calculate base scale to fit image to screen
        base_scale = self._get_base_scale_factor()
        pixmap_size = self._pixmap.size()

        # Calculate the dimensions of the scaled image
        scaled_width = pixmap_size.width() * base_scale
        scaled_height = pixmap_size.height() * base_scale

        # Calculate the centered position (letterboxing)
        target_rect = self.rect()
        base_x = (target_rect.width() - scaled_width) / 2
        base_y = (target_rect.height() - scaled_height) / 2

        # Apply transformations
        painter.save()

        # Move to the image origin
        painter.translate(base_x, base_y)

        # Apply base scaling to fit image to screen
        painter.scale(base_scale, base_scale)

        # Apply the zoom/pan transform
        painter.setTransform(self._transform, combine=True)

        # Draw the full resolution pixmap at origin
        painter.drawPixmap(0, 0, self._pixmap)

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
            center_pos = self._screen_to_image_coords(center)
            self._zoom_in(center_pos)
        elif _match_shortcut(event, Config.SHORTCUTS.get(Shortcut.ZOOM_OUT, "-")):
            # Zoom out centered on screen center
            center = QPointF(self.width() / 2.0, self.height() / 2.0)
            center_pos = self._screen_to_image_coords(center)
            self._zoom_out(center_pos)
        elif _match_shortcut(event, Config.SHORTCUTS.get(Shortcut.ZOOM_RESET, "0")):
            # Reset zoom
            self._transform.reset()
            self._zoom_level = 1.0
            self._is_base_view = True
            self._zoom_direction = ZoomDirection.NONE
            self._hide_zoom_overlay()
            self.update()
        else:
            super().keyPressEvent(event)

    def _screen_to_image_coords(self, screen_pos: QPointF) -> QPointF:
        """Convert screen coordinates to image coordinates."""
        base_scale = self._get_base_scale_factor()
        pixmap_size = self._pixmap.size()

        scaled_width = pixmap_size.width() * base_scale
        scaled_height = pixmap_size.height() * base_scale

        target_rect = self.rect()
        base_x = (target_rect.width() - scaled_width) / 2
        base_y = (target_rect.height() - scaled_height) / 2

        # Convert to image space (accounting for base scale)
        img_x = (screen_pos.x() - base_x) / base_scale
        img_y = (screen_pos.y() - base_y) / base_scale

        return QPointF(img_x, img_y)

    def wheelEvent(self, event):
        """Handle mouse wheel events for zooming."""
        self._wheel_acc += event.angleDelta().y()

        if abs(self._wheel_acc) >= 120 * Config.ZOOM_WHEEL_SENSITIVITY:
            # Convert mouse position to image coordinates
            center_pos = self._screen_to_image_coords(event.position())

            # Clamp to image rect
            img_rect = self._pixmap.rect()
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

    def _get_1_to_1_zoom_level(self) -> float:
        """Calculate the zoom level for 1:1 pixel mapping with render buffer.

        At this zoom level, 1 image pixel = 1 render buffer pixel.
        Since render buffer = logical size * DPR, and we apply base_scale
        at the painter level, the zoom level for 1:1 is:
        1 / (base_scale * DPR)
        """
        base_scale = self._get_base_scale_factor()
        return 1.0 / (base_scale * self._device_pixel_ratio)

    def _zoom_in(self, center_pos: QPointF):
        """Zoom in, centered on the given position (in image coordinates)."""
        if self._zoom_level >= Config.ZOOM_MAX:
            logger.debug("Already at max zoom level.")
            return

        # Mark that we're zooming in
        self._zoom_direction = ZoomDirection.IN
        self._is_base_view = False

        # Calculate 1:1 zoom level for snapping
        one_to_one_zoom = self._get_1_to_1_zoom_level()

        factor = Config.ZOOM_FACTOR
        next_zoom_level = self._zoom_level * factor

        # Snap to 1:1 (100% in render buffer terms) when crossing that threshold
        if self._zoom_level < one_to_one_zoom < next_zoom_level:
            factor = one_to_one_zoom / self._zoom_level
            self._zoom_level = one_to_one_zoom
            logger.debug("Snapped to 1:1 pixel zoom (100% render buffer)")
        else:
            self._zoom_level = next_zoom_level

        if self._zoom_level > Config.ZOOM_MAX:
            self._zoom_level = Config.ZOOM_MAX

        self._apply_zoom(factor, center_pos)
        self._show_zoom_level()

    def _zoom_out(self, center_pos: QPointF):
        """Zoom out, centered on the given position (in image coordinates)."""
        if self._zoom_level <= 1.0:
            logger.debug("Already at base zoom level.")
            return

        # Mark that we're zooming out
        self._zoom_direction = ZoomDirection.OUT

        # Calculate 1:1 zoom level for snapping
        one_to_one_zoom = self._get_1_to_1_zoom_level()

        factor = 1.0 / Config.ZOOM_FACTOR
        next_zoom_level = self._zoom_level * factor

        # Snap to 1:1 (100% in render buffer terms) when crossing that threshold
        if self._zoom_level > one_to_one_zoom > next_zoom_level:
            factor = one_to_one_zoom / self._zoom_level
            self._zoom_level = one_to_one_zoom
            logger.debug("Snapped to 1:1 pixel zoom (100% render buffer)")
        else:
            self._zoom_level = next_zoom_level

        if self._zoom_level < 1.0:
            self._zoom_level = 1.0

        if self._zoom_level == 1.0:
            self._transform.reset()
            self._is_base_view = True
            self._show_zoom_level()  # Show when returning to base by zooming out
            self.update()
        else:
            self._is_base_view = False
            self._apply_zoom(factor, center_pos)
            self._show_zoom_level()

    def _apply_zoom(self, factor: float, center_pos: QPointF):
        """Apply zoom transformation centered on the given image position."""
        transform = QTransform()
        transform.translate(center_pos.x(), center_pos.y())
        transform.scale(factor, factor)
        transform.translate(-center_pos.x(), -center_pos.y())
        self._transform = self._transform * transform
        logger.debug(f"Zoom level updated to: {self._zoom_level}")
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

        # Get base scale to convert delta to image coordinates
        base_scale = self._get_base_scale_factor()

        # Apply the translation (in image coordinates)
        self._transform.translate(
            delta.x() / (self._zoom_level * base_scale),
            delta.y() / (self._zoom_level * base_scale),
        )

        # Clamp immediately to prevent going beyond boundaries during drag
        self._clamp_pan_smooth()
        self.update()

    def _get_effective_empty_space(self):
        """Calculate the effective empty space around the image at current zoom
        level."""
        base_scale = self._get_base_scale_factor()
        pixmap_size = self._pixmap.size()
        view_rect = self.rect()

        scaled_width = pixmap_size.width() * base_scale
        scaled_height = pixmap_size.height() * base_scale

        # Configured empty space, scaled to the current view
        if pixmap_size.width() > 0:
            configured_empty_space = Config.PAN_EMPTY_SPACE * self._zoom_level
        else:
            configured_empty_space = 0

        # Size of the initial black bars (scaled with zoom)
        black_bar_x = max(0, (view_rect.width() - scaled_width) / 2) * self._zoom_level
        black_bar_y = (
            max(0, (view_rect.height() - scaled_height) / 2) * self._zoom_level
        )

        # The effective empty space is the larger of the two for each axis
        effective_h_space = max(configured_empty_space, black_bar_x)
        effective_v_space = max(configured_empty_space, black_bar_y)

        return effective_h_space, effective_v_space

    def _clamp_pan_smooth(self):
        """Smoothly clamps panning during drag to prevent going beyond boundaries."""
        base_scale = self._get_base_scale_factor()
        pixmap_size = self._pixmap.size()
        view_rect = self.rect()

        scaled_width = pixmap_size.width() * base_scale
        scaled_height = pixmap_size.height() * base_scale

        base_x = (view_rect.width() - scaled_width) / 2
        base_y = (view_rect.height() - scaled_height) / 2

        # Get the transformed image rect in screen coordinates
        # We need to map through: image coords -> transform -> scale -> translate
        img_rect = self._pixmap.rect()

        # Apply zoom transform, then base scale, then base position
        transformed_rect = self._transform.mapRect(img_rect)
        final_img_rect = transformed_rect.translated(
            transformed_rect.left() * (base_scale - 1) + base_x,
            transformed_rect.top() * (base_scale - 1) + base_y,
        )
        final_img_rect.setWidth(transformed_rect.width() * base_scale)
        final_img_rect.setHeight(transformed_rect.height() * base_scale)

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

        # Apply corrections (convert from screen coords to image coords)
        if dx or dy:
            self._transform.translate(
                dx / (self._zoom_level * base_scale),
                dy / (self._zoom_level * base_scale),
            )

    def _clamp_pan(self):
        """Clamps the panning transformation to stay within the defined boundaries."""
        self._clamp_pan_smooth()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release events to stop panning."""
        if event.button() == Qt.LeftButton and self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            self._clamp_pan()
