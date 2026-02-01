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

from piqopiqo.components.label_utils import get_label_color
from piqopiqo.config import Config, Shortcut
from piqopiqo.db_fields import DBFields
from piqopiqo.shortcuts import match_shortcut_sequence, match_simple_shortcut

from .pan import calculate_allowed_extra_from_current
from .zoom import (
    ZOOM_STATE_PERCENTAGES,
    ZoomDirection,
    ZoomState,
    get_next_zoom_state,
    get_zoom_level_for_state,
    should_show_zoom_overlay,
)

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
        self._click_start_pos = QPointF()  # Track click position for click-to-zoom
        self._did_pan = False  # Track if we panned during this click

        # Pan cursor delay timer - prevents cursor from changing to hand on brief clicks
        self._pan_cursor_timer = QTimer(self)
        self._pan_cursor_timer.setSingleShot(True)
        self._pan_cursor_timer.timeout.connect(self._activate_pan_cursor)
        self._pan_mode_active = False  # True once cursor changed to hand
        self._just_zoomed_in = False  # True when we zoomed in on mouse down

        self._wheel_acc = 0

        # Zoom state tracking
        self._zoom_state = ZoomState.BASE_VIEW
        self._zoom_direction = ZoomDirection.NONE
        self._is_small_image = False  # True if base view is already at 100%

        # Zoom overlay state
        self._overlay_timer = QTimer(self)
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.timeout.connect(self._hide_zoom_overlay)
        self._show_zoom_overlay = False

        # Per-side allowed extra space (set when navigating with preserved zoom)
        # This allows space > PAN_EMPTY_SPACE on sides where it was larger at load time
        self._allowed_extra_space = {"left": 0, "right": 0, "top": 0, "bottom": 0}

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
        """Update and position the zoom overlay based on current zoom state."""
        # Get the percentage from the zoom state
        percentage = ZOOM_STATE_PERCENTAGES.get(self._zoom_state)
        if percentage is None:
            return

        self.zoom_overlay.setText(f"{percentage}%")
        self.zoom_overlay.adjustSize()

        # Position at top of screen with margin
        overlay_x = (self.width() - self.zoom_overlay.width()) // 2
        overlay_y = 40  # Top margin
        self.zoom_overlay.move(overlay_x, overlay_y)

    def _show_zoom_level(self):
        """Show the zoom overlay with auto-hide timer."""
        if should_show_zoom_overlay(
            self._zoom_state, self._zoom_direction, self._is_small_image
        ):
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
                color = get_label_color(label)
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

    def _load_pixmap_at_current_index(self) -> bool:
        """Load the pixmap for the current index.

        Returns True if successfully loaded, False otherwise.
        This is the common loading logic shared by _load_current_image and
        _load_image_only.
        """
        global_index = self.visible_indices[self.current_visible_idx]
        if 0 <= global_index < len(self.all_items):
            image_data = self.all_items[global_index]
            self.image_path = image_data.path
            if self.image_path:
                self._pixmap = QPixmap(self.image_path)
                if self._pixmap.isNull():
                    logger.warning(f"Failed to load image: {self.image_path}")
                    self._pixmap = QPixmap()
                    return False
                self._update_small_image_flag()
                self._update_info_panel()
                return True
        return False

    def _load_current_image(self):
        """Load the image at the current index and reset zoom/pan state."""
        # Reset transformation state
        self._transform.reset()
        self._zoom_level = 1.0
        self._panning = False
        self._pan_start_pos = QPointF()
        self._did_pan = False

        # Reset zoom state - entering base view
        self._zoom_state = ZoomState.BASE_VIEW
        self._zoom_direction = ZoomDirection.NONE
        self._hide_zoom_overlay()

        # Reset allowed extra space (no extra allowance in base view)
        self._reset_allowed_extra_space()

        if self._load_pixmap_at_current_index():
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

    def _navigate_to_preserve_zoom(self, new_visible_idx: int):
        """Navigate to a new image while preserving zoom level and center position.

        Keeps the same zoom factor. The center of the image preserves its screen
        position - i.e., the center of the new image appears at the same screen
        coordinates as the center of the old image (can be negative if offscreen).

        Special cases:
        - If the new image would be completely offscreen, show it in base view
        - Allowed extra space is set based on the initial position to prevent
          clamping from shifting the image when navigating back and forth
        """
        total_visible = len(self.visible_indices)
        if total_visible == 0:
            return

        new_visible_idx = (
            new_visible_idx % total_visible + total_visible
        ) % total_visible

        if new_visible_idx != self.current_visible_idx:
            # Before leaving, update allowed extra space based on current pan state
            # If user panned and reduced space below PAN_EMPTY_SPACE, that's recorded
            self._update_allowed_extra_space_after_pan()

            # Get where the old image's center is on screen (can be offscreen)
            old_image_center_screen = self._get_image_center_screen_coords()

            # Save zoom state
            saved_zoom_level = self._zoom_level
            saved_zoom_state = self._zoom_state
            saved_zoom_direction = self._zoom_direction

            # Load new image
            self.current_visible_idx = new_visible_idx
            self._load_image_only()

            # Restore zoom state
            self._zoom_level = saved_zoom_level
            self._zoom_state = saved_zoom_state
            self._zoom_direction = saved_zoom_direction

            # Position new image center at the same screen position (without clamping)
            self._position_image_center_at_screen_no_clamp(old_image_center_screen)

            # Check if the new image would be completely offscreen
            if self._is_image_completely_offscreen():
                # Fall back to base view
                self._load_current_image()
            else:
                # Set allowed extra space based on the new position
                self._set_allowed_extra_space_from_current()
                # Now clamp with the new allowed space
                self._clamp_pan()

            # Emit signal
            global_index = self.visible_indices[self.current_visible_idx]
            self.index_changed.emit(global_index)

            self.update()

    def _load_image_only(self):
        """Load the image at current index WITHOUT resetting zoom/pan state."""
        self._load_pixmap_at_current_index()

    def _get_image_center_screen_coords(self) -> QPointF:
        """Get the screen coordinates where the image center is currently displayed.

        Returns the screen position of the center point of the image,
        accounting for the current transform (zoom/pan) and base scaling.
        """
        if self._pixmap.isNull():
            return QPointF(self.width() / 2.0, self.height() / 2.0)

        # Image center in image coordinates
        img_center = QPointF(self._pixmap.width() / 2.0, self._pixmap.height() / 2.0)

        # Apply the current transform
        transformed_center = self._transform.map(img_center)

        # Get base scale and position
        base_scale = self._get_base_scale_factor()
        pixmap_size = self._pixmap.size()
        scaled_width = pixmap_size.width() * base_scale
        scaled_height = pixmap_size.height() * base_scale
        target_rect = self.rect()
        base_x = (target_rect.width() - scaled_width) / 2
        base_y = (target_rect.height() - scaled_height) / 2

        # Convert to screen coordinates
        screen_x = base_x + transformed_center.x() * base_scale
        screen_y = base_y + transformed_center.y() * base_scale

        return QPointF(screen_x, screen_y)

    def _position_image_center_at_screen(self, target_screen_pos: QPointF):
        """Position the current image so its center is at the given screen position.

        Resets the transform and applies zoom centered on the image center,
        then translates so the image center appears at target_screen_pos.

        Args:
            target_screen_pos: The screen position where the image center should appear
        """
        if self._pixmap.isNull():
            return

        new_img_center = QPointF(
            self._pixmap.width() / 2.0, self._pixmap.height() / 2.0
        )

        # Get base parameters for new image
        base_scale = self._get_base_scale_factor()
        pixmap_size = self._pixmap.size()
        scaled_width = pixmap_size.width() * base_scale
        scaled_height = pixmap_size.height() * base_scale
        target_rect = self.rect()
        base_x = (target_rect.width() - scaled_width) / 2
        base_y = (target_rect.height() - scaled_height) / 2

        # Reset transform
        self._transform.reset()

        if self._zoom_state != ZoomState.BASE_VIEW:
            # Apply zoom centered on image center
            self._transform.translate(new_img_center.x(), new_img_center.y())
            self._transform.scale(self._zoom_level, self._zoom_level)
            self._transform.translate(-new_img_center.x(), -new_img_center.y())

        # Calculate where image center currently appears on screen.
        # After zoom centered on image center, it's still at (w/2, h/2) transformed
        current_screen_x = base_x + new_img_center.x() * base_scale
        current_screen_y = base_y + new_img_center.y() * base_scale

        # Calculate screen delta needed
        dx_screen = target_screen_pos.x() - current_screen_x
        dy_screen = target_screen_pos.y() - current_screen_y

        # Apply translation in transformed space (post-zoom)
        # Screen delta = transform delta * base_scale
        # So transform delta = screen delta / base_scale
        tx = dx_screen / base_scale
        ty = dy_screen / base_scale

        # Apply as post-multiplication (translation after zoom)
        translate_transform = QTransform()
        translate_transform.translate(tx, ty)
        self._transform = self._transform * translate_transform

        self._clamp_pan()
        self.update()

    def _position_image_center_at_screen_no_clamp(self, target_screen_pos: QPointF):
        """Position the current image so its center is at the given screen position.

        Same as _position_image_center_at_screen but does NOT clamp or update.
        Used during navigation to allow setting allowed extra space first.

        Args:
            target_screen_pos: The screen position where the image center should appear
        """
        if self._pixmap.isNull():
            return

        new_img_center = QPointF(
            self._pixmap.width() / 2.0, self._pixmap.height() / 2.0
        )

        # Get base parameters for new image
        base_scale = self._get_base_scale_factor()
        pixmap_size = self._pixmap.size()
        scaled_width = pixmap_size.width() * base_scale
        scaled_height = pixmap_size.height() * base_scale
        target_rect = self.rect()
        base_x = (target_rect.width() - scaled_width) / 2
        base_y = (target_rect.height() - scaled_height) / 2

        # Reset transform
        self._transform.reset()

        if self._zoom_state != ZoomState.BASE_VIEW:
            # Apply zoom centered on image center
            self._transform.translate(new_img_center.x(), new_img_center.y())
            self._transform.scale(self._zoom_level, self._zoom_level)
            self._transform.translate(-new_img_center.x(), -new_img_center.y())

        # Calculate where image center currently appears on screen
        current_screen_x = base_x + new_img_center.x() * base_scale
        current_screen_y = base_y + new_img_center.y() * base_scale

        # Calculate screen delta needed
        dx_screen = target_screen_pos.x() - current_screen_x
        dy_screen = target_screen_pos.y() - current_screen_y

        # Apply translation in transformed space (post-zoom)
        tx = dx_screen / base_scale
        ty = dy_screen / base_scale

        # Apply as post-multiplication (translation after zoom)
        translate_transform = QTransform()
        translate_transform.translate(tx, ty)
        self._transform = self._transform * translate_transform

    def _is_image_completely_offscreen(self) -> bool:
        """Check if the image would be completely offscreen with current transform.

        Returns True if no part of the image intersects the view rect.
        """
        if self._pixmap.isNull():
            return True

        view_rect = self.rect()
        img_rect = self._get_image_rect_in_screen_coords()

        # Check if there's any intersection
        return not view_rect.intersects(img_rect)

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

    def _update_small_image_flag(self):
        """Determine if the image is 'small' (base view is already at 100%).

        A small image is one where the base scale factor (fit to screen) is 1.0,
        meaning the image fits on screen without any scaling needed.
        """
        base_scale = self._get_base_scale_factor()
        # Small image means base_scale is 1.0 (no downscaling needed)
        self._is_small_image = base_scale >= 1.0

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

        # Hardcoded shortcuts (non-configurable)
        if match_simple_shortcut(event, Qt.Key_Escape) or match_simple_shortcut(
            event, Qt.Key_Space
        ):
            self.close()
        elif match_simple_shortcut(event, Qt.Key_Left):
            self._navigate_to_preserve_zoom(self.current_visible_idx - 1)
        elif match_simple_shortcut(event, Qt.Key_Right):
            self._navigate_to_preserve_zoom(self.current_visible_idx + 1)
        elif match_simple_shortcut(event, Qt.Key_Up):
            pass  # Ignore up key in fullscreen
        elif match_simple_shortcut(event, Qt.Key_Down):
            pass  # Ignore down key in fullscreen
        # Configurable shortcuts
        elif match_shortcut_sequence(event, Config.SHORTCUTS.get(Shortcut.ZOOM_IN)):
            # Zoom in centered on screen center
            center = QPointF(self.width() / 2.0, self.height() / 2.0)
            center_pos = self._screen_to_image_coords(center)
            self._zoom_in(center_pos)
        elif match_shortcut_sequence(event, Config.SHORTCUTS.get(Shortcut.ZOOM_OUT)):
            # Zoom out centered on screen center
            center = QPointF(self.width() / 2.0, self.height() / 2.0)
            center_pos = self._screen_to_image_coords(center)
            self._zoom_out(center_pos)
        elif match_shortcut_sequence(event, Config.SHORTCUTS.get(Shortcut.ZOOM_RESET)):
            # Reset zoom to base view
            self._zoom_to_base_view()
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

    def _zoom_to_base_view(self):
        """Reset zoom to base view."""
        self._transform.reset()
        self._zoom_level = 1.0
        self._zoom_state = ZoomState.BASE_VIEW
        self._zoom_direction = ZoomDirection.OUT
        self._hide_zoom_overlay()
        self.update()

    def _zoom_to_state(self, new_state: ZoomState, center_pos: QPointF):
        """Zoom to a specific state, centered on the given position."""
        old_zoom_level = self._zoom_level
        new_zoom_level = get_zoom_level_for_state(
            new_state, self._get_base_scale_factor(), self._device_pixel_ratio
        )

        self._zoom_state = new_state
        self._zoom_level = new_zoom_level

        if new_state == ZoomState.BASE_VIEW:
            self._transform.reset()
            self._show_zoom_level()
            self.update()
        else:
            factor = new_zoom_level / old_zoom_level
            self._apply_zoom(factor, center_pos)
            self._show_zoom_level()

    def _zoom_in(self, center_pos: QPointF):
        """Zoom in to the next discrete zoom state."""
        next_state = get_next_zoom_state(
            self._zoom_state, ZoomDirection.IN, self._is_small_image
        )
        if next_state is None:
            logger.debug("Already at max zoom state.")
            return

        self._zoom_direction = ZoomDirection.IN
        self._zoom_to_state(next_state, center_pos)

    def _zoom_out(self, center_pos: QPointF):
        """Zoom out to the previous discrete zoom state."""
        if self._zoom_state == ZoomState.BASE_VIEW:
            logger.debug("Already at base view.")
            return

        next_state = get_next_zoom_state(
            self._zoom_state, ZoomDirection.OUT, self._is_small_image
        )
        if next_state is None:
            logger.debug("Already at base view.")
            return

        self._zoom_direction = ZoomDirection.OUT
        self._zoom_to_state(next_state, center_pos)

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
        """Handle mouse press to initiate panning or zoom in.

        Behavior:
        - If zoomed in: start panning, delay cursor change (zoom out on quick release)
        - If at base view with large image: zoom in immediately on mouse down
        """
        if event.button() == Qt.LeftButton:
            self._click_start_pos = event.position()
            self._did_pan = False
            self._pan_mode_active = False
            self._just_zoomed_in = False

            if self._zoom_level > 1.0:
                # Already zoomed in: enable panning with delayed cursor change
                self._panning = True
                self._pan_start_pos = event.position()
                # Start timer for cursor change (don't change cursor immediately)
                self._pan_cursor_timer.start(Config.PAN_CURSOR_DELAY_MS)
            elif self._zoom_state == ZoomState.BASE_VIEW and not self._is_small_image:
                # Base view with large image: zoom in immediately on mouse down
                center_pos = self._screen_to_image_coords(event.position())
                self._zoom_direction = ZoomDirection.IN
                self._zoom_to_state(ZoomState.ZOOM_100, center_pos)
                # Mark that we just zoomed in (so release doesn't zoom back out)
                self._just_zoomed_in = True
                # Enable panning (cursor changes only on movement)
                self._panning = True
                self._pan_start_pos = event.position()

    def _activate_pan_cursor(self):
        """Called after delay to activate pan cursor."""
        if self._panning:
            self._pan_mode_active = True
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move events to perform panning."""
        if not self._panning:
            return

        delta = event.position() - self._pan_start_pos
        self._pan_start_pos = event.position()

        # Track if we've moved significantly (to distinguish pan from click)
        total_delta = event.position() - self._click_start_pos
        if abs(total_delta.x()) > 5 or abs(total_delta.y()) > 5:
            self._did_pan = True
            # If we just zoomed in and now moved, activate pan mode + cursor
            if self._just_zoomed_in and not self._pan_mode_active:
                self._pan_mode_active = True
                self.setCursor(Qt.ClosedHandCursor)

        # Get base scale to convert delta to image coordinates
        base_scale = self._get_base_scale_factor()

        # Apply the translation (in image coordinates)
        self._transform.translate(
            delta.x() / (self._zoom_level * base_scale),
            delta.y() / (self._zoom_level * base_scale),
        )

        # Clamp immediately to prevent going beyond boundaries during drag
        self._clamp_pan_smooth()

        # Update allowed extra space - if user reduced space below PAN_EMPTY_SPACE,
        # that side's extra allowance is reset
        self._update_allowed_extra_space_after_pan()

        self.update()

    def _get_image_rect_in_screen_coords(self):
        """Get the current image rectangle in screen coordinates.

        Returns the bounding rectangle of the image after all transforms
        (zoom, pan, base scale) have been applied.
        """
        if self._pixmap.isNull():
            return self.rect()

        base_scale = self._get_base_scale_factor()
        pixmap_size = self._pixmap.size()
        view_rect = self.rect()

        scaled_width = pixmap_size.width() * base_scale
        scaled_height = pixmap_size.height() * base_scale

        base_x = (view_rect.width() - scaled_width) / 2
        base_y = (view_rect.height() - scaled_height) / 2

        img_rect = self._pixmap.rect()
        transformed_rect = self._transform.mapRect(img_rect)
        final_rect = transformed_rect.translated(
            transformed_rect.left() * (base_scale - 1) + base_x,
            transformed_rect.top() * (base_scale - 1) + base_y,
        )
        final_rect.setWidth(transformed_rect.width() * base_scale)
        final_rect.setHeight(transformed_rect.height() * base_scale)

        return final_rect

    def _get_current_space_per_side(self) -> dict[str, float]:
        """Calculate the current empty space on each side in screen coordinates.

        Returns a dict with keys: left, right, top, bottom.
        Positive values mean empty space, negative means image extends beyond screen.
        """
        view_rect = self.rect()
        img_rect = self._get_image_rect_in_screen_coords()

        return {
            "left": img_rect.left(),
            "right": view_rect.width() - img_rect.right(),
            "top": img_rect.top(),
            "bottom": view_rect.height() - img_rect.bottom(),
        }

    def _get_effective_empty_space_per_side(self) -> dict[str, float]:
        """Get the effective allowed empty space for each side in screen coordinates.

        Returns base PAN_EMPTY_SPACE plus any extra allowance set at load time.
        This allows larger space on sides where it was larger at image load time.
        """
        base = Config.PAN_EMPTY_SPACE
        return {
            "left": base + self._allowed_extra_space["left"],
            "right": base + self._allowed_extra_space["right"],
            "top": base + self._allowed_extra_space["top"],
            "bottom": base + self._allowed_extra_space["bottom"],
        }

    def _reset_allowed_extra_space(self):
        """Reset the per-side allowed extra space to zero."""
        self._allowed_extra_space = {"left": 0, "right": 0, "top": 0, "bottom": 0}

    def _set_allowed_extra_space_from_current(self):
        """Set allowed extra space based on current image position.

        For each side, if the current space exceeds PAN_EMPTY_SPACE,
        that becomes the allowed space for that side.
        """
        current = self._get_current_space_per_side()
        self._allowed_extra_space = calculate_allowed_extra_from_current(
            current, Config.PAN_EMPTY_SPACE
        )

    def _update_allowed_extra_space_after_pan(self):
        """Update allowed extra space after panning.

        If panning has reduced the space on any side below PAN_EMPTY_SPACE,
        that side's extra allowance is reset to 0.
        """
        current = self._get_current_space_per_side()
        base = Config.PAN_EMPTY_SPACE
        for side, space in current.items():
            if space < base:
                self._allowed_extra_space[side] = 0

    def _clamp_pan_smooth(self):
        """Smoothly clamps panning during drag to prevent going beyond boundaries."""
        if self._pixmap.isNull():
            return

        base_scale = self._get_base_scale_factor()
        view_rect = self.rect()
        final_img_rect = self._get_image_rect_in_screen_coords()

        # Get per-side effective empty space (in screen coordinates)
        effective_space = self._get_effective_empty_space_per_side()

        # Calculate required corrections
        dx = 0
        if final_img_rect.width() < view_rect.width():
            dx = view_rect.center().x() - final_img_rect.center().x()
        elif final_img_rect.left() > effective_space["left"]:
            dx = effective_space["left"] - final_img_rect.left()
        elif final_img_rect.right() < view_rect.width() - effective_space["right"]:
            dx = view_rect.width() - effective_space["right"] - final_img_rect.right()

        dy = 0
        if final_img_rect.height() < view_rect.height():
            dy = view_rect.center().y() - final_img_rect.center().y()
        elif final_img_rect.top() > effective_space["top"]:
            dy = effective_space["top"] - final_img_rect.top()
        elif final_img_rect.bottom() < view_rect.height() - effective_space["bottom"]:
            bottom_limit = view_rect.height() - effective_space["bottom"]
            dy = bottom_limit - final_img_rect.bottom()

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
        """Handle mouse release events to stop panning or perform click-to-zoom."""
        if event.button() == Qt.LeftButton:
            was_panning = self._panning
            was_pan_mode_active = self._pan_mode_active
            just_zoomed_in = self._just_zoomed_in

            self._panning = False
            self._pan_mode_active = False
            self._just_zoomed_in = False
            self._pan_cursor_timer.stop()  # Cancel any pending timer
            self.setCursor(Qt.ArrowCursor)

            if was_panning:
                self._clamp_pan()

            # Handle click-to-zoom (zoom OUT) only if:
            # 1. We didn't actually pan (move > 5px)
            # 2. Pan mode was NOT activated (cursor didn't become hand)
            # 3. We didn't just zoom in on mouse down
            if not self._did_pan and not was_pan_mode_active and not just_zoomed_in:
                self._handle_click_zoom(event.position())

    def _handle_click_zoom(self, screen_pos: QPointF):
        """Handle click-to-zoom interaction (only zoom OUT).

        Note: Zoom IN from base view now happens on mouse down in mousePressEvent.
        This function only handles:
        - At 100% or beyond: click returns to base view
        - Small image at base view: click does nothing (already at 100%)
        """
        if self._zoom_state == ZoomState.BASE_VIEW:
            # At base view (including small images): do nothing
            # Zoom IN for large images is handled in mousePressEvent
            return
        else:
            # Zoomed in (100% or beyond): return to base view
            self._zoom_direction = ZoomDirection.OUT
            self._zoom_to_base_view()
