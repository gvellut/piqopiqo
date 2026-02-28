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

from piqopiqo.label_utils import get_label_color
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.ssf.settings_state import RuntimeSettingKey, get_runtime_setting


class PhotoCell(QFrame):
    """Widget for displaying a single photo cell in the grid."""

    clicked = Signal(int, bool, bool)  # global_index, is_shift, is_ctrl
    right_clicked = Signal(int)  # global_index

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

    def set_selected_state(self, is_selected: bool) -> None:
        if self.is_selected == is_selected:
            return
        self.is_selected = is_selected
        self.update()

    def set_layout_info(self, info: dict):
        self.layout_info = info
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if self.current_data:
                modifiers = event.modifiers()
                self.clicked.emit(
                    self.current_data._global_index,
                    bool(modifiers & Qt.ShiftModifier),
                    bool(modifiers & Qt.ControlModifier),
                )
            else:
                # Empty cell clicked - emit with -1 to signal clear selection
                self.clicked.emit(-1, False, False)
        elif event.button() == Qt.RightButton and self.current_data:
            self.right_clicked.emit(self.current_data._global_index)
        super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent):
        if not self.layout_info:
            return

        painter = QPainter(self)
        try:
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
            square_size = max(0, min(img_rect.width(), img_rect.height()))
            square_rect = QRect(0, 0, square_size, square_size)
            square_rect.moveCenter(img_rect.center())

            if state == 0:
                painter.fillRect(square_rect, QColor("black"))
            else:
                if pixmap:
                    # Orientation is already applied in item.pixmap by the grid.
                    # Always scale to fit a centered square area (up or down)
                    # while preserving aspect ratio, then keep centered.
                    if square_rect.width() > 0 and square_rect.height() > 0:
                        scaled = pixmap.scaled(
                            square_rect.size(),
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation,
                        )
                        pixmap_rect = scaled.rect()
                        pixmap_rect.moveCenter(square_rect.center())
                        painter.drawPixmap(pixmap_rect, scaled)

            # Draw label swatch (top-right corner of image area)
            if get_runtime_setting(RuntimeSettingKey.GRID_ITEM_SHOW_LABEL_SWATCH):
                label = db_meta.get(DBFields.LABEL)
                if label:
                    color = get_label_color(label)
                    if color:
                        swatch_size = 16
                        swatch_margin = 4
                        swatch_rect = QRect(
                            square_rect.right() - swatch_size - swatch_margin,
                            square_rect.top() + swatch_margin,
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

            # Keep the same font sizing as PhotoGrid._calculate_metadata_height.
            painter.font().setPointSize(
                int(get_runtime_setting(RuntimeSettingKey.FONT_SIZE))
            )

            painter.setPen(QPen(Qt.white))
            font_metrics = painter.fontMetrics()
            line_height = font_metrics.lineSpacing()

            # Vertical padding inside the metadata area.
            # The grid reserves a few extra pixels (see
            # PhotoGrid._calculate_metadata_height) but we still need to actually
            # use them when drawing.
            expected_lines = 1 + sum(
                1
                for field_name in get_runtime_setting(
                    RuntimeSettingKey.GRID_ITEM_FIELDS
                )
                if field_name != DBFields.LABEL
            )
            reserved_text_h = expected_lines * line_height
            extra_h = max(0, text_rect.height() - reserved_text_h)
            top_pad = extra_h
            text_top = text_rect.top() + top_pad

            # Filename (first line)
            elided_name = font_metrics.elidedText(
                name, Qt.ElideRight, text_rect.width()
            )
            filename_rect = QRect(
                text_rect.left(),
                text_top,
                text_rect.width(),
                line_height,
            )
            painter.drawText(filename_rect, Qt.AlignTop | Qt.AlignHCenter, elided_name)

            # DB fields (subsequent lines)
            y_offset = line_height
            for field_name in get_runtime_setting(RuntimeSettingKey.GRID_ITEM_FIELDS):
                if field_name == DBFields.LABEL:
                    continue  # Label shown as swatch, not text

                value = db_meta.get(field_name, "")
                if value:
                    # Format datetime objects as ISO string
                    if field_name == DBFields.TIME_TAKEN and isinstance(
                        value, datetime
                    ):
                        display_value = value.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        display_value = str(value)
                    field_rect = QRect(
                        text_rect.left(),
                        text_top + y_offset,
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

            # Draw border around item Wiw look like lines of the grid
            painter.setPen(QPen(QColor("#555555"), 1))
            painter.drawRect(rect)
        finally:
            painter.end()
