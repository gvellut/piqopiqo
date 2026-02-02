"""Photo cell widget for displaying a single photo in the grid."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import QFrame, QSizePolicy

from piqopiqo.config import Config
from piqopiqo.label_utils import get_label_color
from piqopiqo.metadata.db_fields import DBFields


class PhotoCell(QFrame):
    """Widget for displaying a single photo cell in the grid."""

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
                color = get_label_color(label)
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
                # Format datetime objects as ISO string
                if field_name == DBFields.TIME_TAKEN and isinstance(value, datetime):
                    display_value = value.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    display_value = str(value)
                field_rect = QRect(
                    text_rect.left(),
                    text_rect.top() + y_offset,
                    text_rect.width(),
                    line_height,
                )
                elided_value = font_metrics.elidedText(
                    display_value, Qt.ElideRight, text_rect.width()
                )
                painter.drawText(
                    field_rect, Qt.AlignTop | Qt.AlignHCenter, elided_value
                )
            y_offset += line_height

        # Draw red border around item
        painter.setPen(QPen(QColor("red"), 2))
        painter.drawRect(rect.adjusted(1, 1, -1, -1))
