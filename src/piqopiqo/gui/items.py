import logging

from PySide6.QtCore import QAbstractListModel, QSize, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

logger = logging.getLogger(__name__)


class PhotoModel(QAbstractListModel):
    Role_Path = Qt.UserRole + 1
    Role_Date = Qt.UserRole + 2
    Role_State = Qt.UserRole + 3
    Role_Thumb = Qt.UserRole + 4

    def __init__(self, images, parent=None):
        super().__init__(parent)
        self.items = images
        for item in self.items:
            item["state"] = 0
            item["pixmap"] = None

    def data(self, index, role):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        if role == Qt.DisplayRole:
            return item["name"]
        elif role == self.Role_Path:
            return item["path"]
        elif role == self.Role_Date:
            return item["created"]
        elif role == self.Role_State:
            return item["state"]
        elif role == self.Role_Thumb:
            return item["pixmap"]
        return None

    def rowCount(self, parent=None):
        return len(self.items)

    def update_thumbnail(self, index, pixmap, state):
        if index.isValid():
            self.items[index.row()]["pixmap"] = pixmap
            self.items[index.row()]["state"] = state
            self.dataChanged.emit(index, index)


class PhotoDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        # Use the cell height from the grid's layout_info
        layout_info = option.widget.layout_info
        img_rect_w = layout_info["img_rect_w"]
        img_rect_h = layout_info["img_rect_h"]
        return QSize(img_rect_w, img_rect_h)

    def paint(self, painter, option, index):
        # We don't use the default paint method
        # super().paint(painter, option, index)

        logger.debug(f"rect {option.rect}")

        # Selection
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        # Data
        state = index.data(PhotoModel.Role_State)
        pixmap = index.data(PhotoModel.Role_Thumb)
        name = index.data(Qt.DisplayRole)
        date = index.data(PhotoModel.Role_Date)

        # Layout
        layout_info = option.widget.layout_info
        pad = layout_info["pad"]
        img_rect_w = layout_info["img_rect_w"]
        img_rect_h = layout_info["img_rect_h"]
        meta_h = layout_info["meta_h"]

        # Image
        img_rect = option.rect.adjusted(pad, pad, -pad, -(pad + meta_h))
        if state == 0:
            painter.fillRect(img_rect, QColor("black"))
            # Trigger lazy load
            if hasattr(option.widget, "request_thumb"):
                option.widget.request_thumb(index)
        else:
            if pixmap:
                # Center pixmap in img_rect
                pixmap_rect = pixmap.rect()
                pixmap_rect.moveCenter(img_rect.center())
                painter.drawPixmap(pixmap_rect, pixmap)

        # Text
        text_rect = option.rect.adjusted(pad, pad + img_rect_h, -pad, -pad)
        painter.setPen(QPen(Qt.white))
        # Filename
        font_metrics = painter.fontMetrics()
        elided_name = font_metrics.elidedText(name, Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignTop | Qt.AlignHCenter, elided_name)
        # Date
        painter.drawText(text_rect, Qt.AlignBottom | Qt.AlignHCenter, date)

        # Draw red border around item
        painter.setPen(QPen(QColor("red"), 2))
        painter.drawRect(option.rect.adjusted(1, 1, -1, -1))
