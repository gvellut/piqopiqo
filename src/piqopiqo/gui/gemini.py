import math
import sys

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollBar,
    QVBoxLayout,
    QWidget,
)


# 1. Custom Widget to act as a Cell
# This makes it easy to handle resizing and painting logic cleanly.
class ImageCell(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Box)
        self.setLineWidth(1)
        self.data = None  # This will hold your image path or object
        self.index_label = None

        # Style for demo purposes
        self.setStyleSheet(
            "background-color: #333; color: white; border: 1px solid #555;"
        )

    def set_content(self, data):
        """
        Update the cell content.
        'data' could be an image path, a pixmap, or an object.
        """
        self.data = data
        self.update()  # Trigger paintEvent

    def paintEvent(self, event):
        """
        Custom painting to handle aspect ratios or empty states.
        """
        super().paintEvent(event)
        painter = QPainter(self)

        if self.data is None:
            # Draw empty state
            return

        # --- DEMO DRAWING LOGIC ---
        # In a real app, you would draw a QPixmap here:
        # painter.drawPixmap(rect, scaled_pixmap)

        # Draw a colored background based on data to simulate an image
        bg_color = QColor(self.data["color"])
        painter.fillRect(self.rect().adjusted(2, 2, -2, -2), bg_color)

        # Draw the text/ID
        painter.setPen(Qt.white)
        painter.setFont(QFont("Arial", 20, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, f"Item {self.data['id']}")
        # --------------------------


# 2. The Main Grid Controller
class PagedGridView(QWidget):
    def __init__(self, rows=2, cols=2):
        super().__init__()

        self.visible_rows = rows
        self.visible_cols = cols
        self.items_data = []  # The list of all your images/data

        # Main Layout: Grid on the left, Scrollbar on the right
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Container for the grid
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(5, 5, 5, 5)
        self.grid_layout.setSpacing(10)

        # The Artificial Scrollbar
        self.scrollbar = QScrollBar(Qt.Vertical)
        self.scrollbar.setSingleStep(1)  # Scroll 1 row at a time
        self.scrollbar.valueChanged.connect(self.on_scroll)

        # Add to layout
        self.main_layout.addWidget(self.grid_container, stretch=1)
        self.main_layout.addWidget(self.scrollbar, stretch=0)

        # Create the Fixed Widgets (Pool)
        self.cells = []
        for r in range(self.visible_rows):
            for c in range(self.visible_cols):
                cell = ImageCell()
                self.grid_layout.addWidget(cell, r, c)
                self.cells.append(cell)

    def load_data(self, data_list):
        """
        Load the total list of items and reset scrollbar.
        """
        self.items_data = data_list
        self.recalculate_scrollbar()
        self.on_scroll(0)  # Force update to top

    def recalculate_scrollbar(self):
        """
        Calculate the range of the scrollbar based on data count and grid size.
        """
        total_items = len(self.items_data)

        # Calculate total rows required for data
        total_rows = math.ceil(total_items / self.visible_cols)

        # The maximum value is the total rows minus the rows we can see at once.
        # Ensure it doesn't go below 0.
        max_scroll = max(0, total_rows - self.visible_rows)

        self.scrollbar.setRange(0, max_scroll)
        self.scrollbar.setPageStep(self.visible_rows)

        # Hide scrollbar if content fits fully
        if total_rows <= self.visible_rows:
            self.scrollbar.hide()
        else:
            self.scrollbar.show()

    def on_scroll(self, value):
        """
        The core logic: Map scrollbar row index to data slice.
        """
        start_row_index = value

        # Calculate the starting index in the 1D list
        start_data_index = start_row_index * self.visible_cols

        # Iterate over our fixed cell widgets and assign data
        for i, cell in enumerate(self.cells):
            data_index = start_data_index + i

            if data_index < len(self.items_data):
                # We have data for this cell
                cell.set_content(self.items_data[data_index])
                cell.show()
            else:
                # We ran out of data (end of list), hide the cell or clear it
                cell.set_content(None)
                # Option A: Hide completely
                # cell.hide()
                # Option B: Show empty placeholder (preferred for grids)
                cell.show()

    def wheelEvent(self, event):
        """
        Detect mouse wheel movement and update the scrollbar manually.
        """
        # If the scrollbar is hidden, there is nothing to scroll
        if not self.scrollbar.isVisible():
            return

        # angleDelta().y() gives the vertical scroll amount.
        # Positive = Scrolling UP (Moving away from user)
        # Negative = Scrolling DOWN (Moving towards user)
        delta = event.angleDelta().y()

        current_value = self.scrollbar.value()

        # Standard Mouse Wheel:
        # One "notch" is usually 120 units.
        # We want 1 notch = 1 Row step.

        if delta > 0:
            # Scroll UP -> Decrease index (go to previous items)
            new_value = current_value - self.scrollbar.singleStep()
        else:
            # Scroll DOWN -> Increase index (go to next items)
            new_value = current_value + self.scrollbar.singleStep()

        # Set the new value (QScrollBar handles min/max clamping automatically)
        self.scrollbar.setValue(new_value)

        # Accept the event so parents don't try to handle it too
        event.accept()


# 3. Application Entry Point
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Discrete Grid Scroll")
        self.resize(600, 400)

        layout = QVBoxLayout(self)

        # Settings
        rows_displayed = 2
        cols_displayed = 2

        # Create the Viewer
        self.viewer = PagedGridView(rows=rows_displayed, cols=cols_displayed)
        layout.addWidget(self.viewer)

        # Generate Dummy Data (100 items)
        # In reality, this would be a list of file paths: ["img1.jpg", "img2.jpg"...]
        dummy_data = []
        colors = ["#FF5733", "#33FF57", "#3357FF", "#F333FF", "#FF33A8", "#33FFF5"]
        for i in range(50):
            dummy_data.append({"id": i, "color": colors[i % len(colors)]})

        self.viewer.load_data(dummy_data)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
