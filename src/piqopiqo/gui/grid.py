import logging

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QListView

from piqopiqo.config import Config

logger = logging.getLogger(__name__)


class PhotoGrid(QListView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self.setContentsMargins(0, 0, 0, 0)
        self.layout_info = {}

    # TODO change : only on first resize : do computations of numbers of rows / cols
    # otherwise when changing number of cols
    def resizeEvent(self, event):
        panel_w = event.size().width()
        panel_h = event.size().height()

        logger.debug(f"{panel_w},{panel_h}")

        cfg = Config
        cols = cfg.NUM_COLUMNS
        pad = cfg.PADDING

        # Horizontal Calculation
        total_h_pad = (cols + 1) * pad
        avail_w = panel_w - total_h_pad
        img_box_side = avail_w / cols

        # Vertical Calculation (Base)
        # TODO font size : dynamic : max + smaller if not enough size
        # Or remove the meta if not enough size for the lines at defined font size
        meta_h = (cfg.METADATA_LINES * cfg.FONT_SIZE) + pad
        row_base_h = pad + img_box_side + meta_h + pad

        # Vertical Stretching (Fit to View)
        if row_base_h < 1:
            row_base_h = 1
        visible_rows = int(panel_h / row_base_h)
        if visible_rows < 1:
            visible_rows = 1

        logger.debug(f"Cols {cols} Row {visible_rows}")

        used_h = visible_rows * row_base_h
        remaining = panel_h - used_h
        if visible_rows > 0:
            extra_per_row = remaining / visible_rows
        else:
            extra_per_row = 0

        logger.debug(f"remaining {remaining}")

        # Final Dimensions
        self.cell_w = int(img_box_side + (2 * pad))
        self.cell_h = int(row_base_h + extra_per_row)

        logger.debug(f"{self.cell_w},{self.cell_h}")

        # Store calculated rects for the Delegate to use
        self.layout_info = {
            "img_rect_w": img_box_side,
            "img_rect_h": img_box_side + extra_per_row,
            "meta_h": meta_h,
            "pad": pad,
        }

        self.setGridSize(QSize(self.cell_w, self.cell_h))
        super().resizeEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        current_index = self.currentIndex()
        model = self.model()
        if not model:
            return

        rows = model.rowCount()
        cols = Config.NUM_COLUMNS

        if key == Qt.Key_Up:
            new_index = current_index.row() - cols
            if new_index >= 0:
                self.setCurrentIndex(model.index(new_index, 0))
        elif key == Qt.Key_Down:
            new_index = current_index.row() + cols
            if new_index < rows:
                self.setCurrentIndex(model.index(new_index, 0))
        else:
            super().keyPressEvent(event)

    def request_thumb(self, index):
        # This will be connected to the thumbnail manager
        pass
