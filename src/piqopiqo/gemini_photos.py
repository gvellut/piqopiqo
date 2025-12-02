import atexit  # ADDED: For safety cleanup of macOS UI state
import logging
import math

import AppKit
from PySide6.QtCore import QRect, Qt, Signal
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
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMainWindow,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.config import Config
from piqopiqo.thumb_man import ThumbnailManager

logger = logging.getLogger(__name__)


class FullscreenOverlay(QWidget):
    """A fullscreen overlay widget for displaying an image at full resolution."""

    def __init__(self, image_path: str):
        super().__init__()
        self.image_path = image_path
        self._pixmap = QPixmap(image_path)
        self._prev_presentation_opts = None  # ADDED: Store previous macOS state

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
        """Custom painting to handle aspect ratio and letterboxing."""
        # (Logic kept exactly as provided)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # Fill background with configured color
        painter.fillRect(self.rect(), self._background_color)

        if self._pixmap.isNull():
            return

        # Get the geometry of the widget (logical pixels)
        target_rect = self.rect()
        pixmap_size = self._pixmap.size()

        # Check if image is smaller than screen in both dimensions
        if (
            pixmap_size.width() <= target_rect.width()
            and pixmap_size.height() <= target_rect.height()
        ):
            # Image is smaller - display at original resolution, centered
            x = (target_rect.width() - pixmap_size.width()) // 2
            y = (target_rect.height() - pixmap_size.height()) // 2
            painter.drawPixmap(x, y, self._pixmap)
        else:
            # Image is larger - scale to fit while keeping aspect ratio
            scaled_pixmap = self._pixmap.scaled(
                target_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )

            # Calculate position to center the image
            x = (target_rect.width() - scaled_pixmap.width()) // 2
            y = (target_rect.height() - scaled_pixmap.height()) // 2

            painter.drawPixmap(x, y, scaled_pixmap)

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard events to dismiss the overlay."""
        if event.key() in (Qt.Key_Escape, Qt.Key_Space):
            self.close()
        else:
            super().keyPressEvent(event)


class PhotoCell(QFrame):
    clicked = Signal(int)

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
            # We assume current_data has the globally injected index or we handle it in
            # the grid
            # Here we just emit the grid index, the parent logic can map it if needed,
            # but usually the data item itself carries its identity.
            global_index = self.current_data.get("_global_index", -1)
            self.clicked.emit(global_index)
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
        # Mimicking PhotoModel.data logic
        name = self.current_data.get("name", "")
        date = self.current_data.get("created", "")
        state = self.current_data.get("state", 0)
        pixmap = self.current_data.get("pixmap", None)

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
    selection_changed = Signal(int)
    request_fullscreen = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setFocusPolicy(Qt.StrongFocus)

        self.n_cols = Config.NUM_COLUMNS
        self.n_rows = 1  # Will be calculated in resizeEvent
        self.items_data = []
        self.selected_index = -1
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
            item["_global_index"] = i
        self.items_data = items
        self.selected_index = -1
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
                is_sel = item.get("_global_index") == self.selected_index
                cell.set_content(item, is_sel)
                cell.show()

                if item.get("state") == 0:
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
                is_sel = global_index == self.selected_index
                cell.set_content(item, is_sel)

    def on_cell_clicked(self, global_index):
        if global_index == -1:
            return
        self.selected_index = global_index
        self.selection_changed.emit(global_index)
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

        # If no items, do nothing
        if total_items == 0:
            super().keyPressEvent(event)
            return

        # If nothing is selected, select the first one
        if self.selected_index == -1:
            self.on_cell_clicked(0)
            self._ensure_visible(0)
            return

        new_index = self.selected_index

        # Calculate new index based on key
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
        elif key == Qt.Key_Space:
            # Request fullscreen display when a photo is selected
            self.request_fullscreen.emit(self.selected_index)
            return
        else:
            # Let parent handle other keys (like Tab, Escape, etc)
            super().keyPressEvent(event)
            return

        # Apply change if index moved
        if new_index != self.selected_index:
            self.on_cell_clicked(
                new_index
            )  # Updates selection variable and emits signal
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

        # In the previous code, model wrapped the list. Here we pass the list
        # directly.
        self.images_data = images
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
            if item["path"] == file_path:
                pixmap = QPixmap(cache_path)
                state = 1 if thumb_type == "embedded" else 2

                # Update dict
                item["pixmap"] = pixmap
                item["state"] = state

                # Refresh Grid View
                self.grid.refresh_item(i)
                break

    def request_thumb_handler(self, index):
        if 0 <= index < len(self.images_data):
            file_path = self.images_data[index]["path"]
            self.thumb_manager.queue_image(file_path)

    def _get_physical_resolution(self, screen: QScreen) -> tuple[int, int]:
        """Calculates physical resolution based on logical size and pixel density."""
        geometry = screen.geometry()
        dpr = screen.devicePixelRatio()

        phy_width = int(geometry.width() * dpr)
        phy_height = int(geometry.height() * dpr)

        return phy_width, phy_height

    def _handle_fullscreen_overlay(self, selected_index: int):
        """Display the selected image in a fullscreen overlay."""
        # Close any existing overlay first
        if self._fullscreen_overlay is not None:
            try:
                self._fullscreen_overlay.close()
            except Exception:
                pass
            self._fullscreen_overlay = None

        # Validate the index
        if selected_index < 0 or selected_index >= len(self.images_data):
            logger.debug("Invalid image index for fullscreen display")
            return

        # Get the image path
        image_data = self.images_data[selected_index]
        image_path = image_data.get("path")
        if not image_path:
            logger.debug("Selected image has no path")
            return

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

        # Create and show the overlay
        self._fullscreen_overlay = FullscreenOverlay(image_path)
        self._fullscreen_overlay.show_on_screen(current_screen)

    def closeEvent(self, event):
        self.thumb_manager.stop()
        super().closeEvent(event)
