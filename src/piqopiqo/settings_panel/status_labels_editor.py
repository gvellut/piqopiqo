"""Custom editor widget for status labels with drag-and-drop reordering."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDrag,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.model import StatusLabel

_MAX_LABELS = 9
_MIME_TYPE = "application/x-piqo-label-row"


class _DragHandle(QLabel):
    """Small grip icon indicating the row is draggable."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText("\u2261")  # ≡ trigram / hamburger
        self.setFixedWidth(20)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setStyleSheet("color: #888; font-size: 16px;")


class _ColorButton(QPushButton):
    """Square colour swatch that opens QColorDialog on click."""

    color_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = "#000000"
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._pick_color)
        self._apply_style()

    def color(self) -> str:
        return self._color

    def set_color(self, hex_color: str) -> None:
        self._color = hex_color or "#000000"
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"background-color: {self._color};"
            " border: 1px solid #888;"
            " border-radius: 3px;"
        )

    def _pick_color(self) -> None:
        initial = QColor(self._color)
        if not initial.isValid():
            initial = QColor("#000000")
        chosen = QColorDialog.getColor(initial, self, "Pick label colour")
        if chosen.isValid():
            self._color = chosen.name()
            self._apply_style()
            self.color_changed.emit()


class _StatusLabelRow(QWidget):
    remove_requested = Signal(object)
    value_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_start: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.drag_handle = _DragHandle()
        layout.addWidget(self.drag_handle, 0)

        self.index_label = QLabel("1")
        self.index_label.setFixedWidth(16)
        self.index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.index_label.setStyleSheet("color: #888;")
        layout.addWidget(self.index_label, 0)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name")
        self.name_edit.editingFinished.connect(self._on_editing_finished)
        layout.addWidget(self.name_edit, 2)

        self.color_btn = _ColorButton()
        self.color_btn.color_changed.connect(self.value_changed)
        layout.addWidget(self.color_btn, 0)

        remove_btn = QPushButton()
        remove_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton)
        )
        remove_btn.setFixedSize(26, 26)
        remove_btn.setFlat(True)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(remove_btn, 0)

    def _on_editing_finished(self) -> None:
        self._update_name_validation()
        self.value_changed.emit()

    def set_index(self, index: int) -> None:
        self.index_label.setText(str(index))

    def set_value(self, value: StatusLabel) -> None:
        self.name_edit.setText(value.name)
        self.color_btn.set_color(value.color)
        self._update_name_validation()

    def get_label_data(self) -> tuple[str, str]:
        """Return (name, color) — index is set by position."""
        return self.name_edit.text().strip(), self.color_btn.color()

    def has_valid_name(self) -> bool:
        return bool(self.name_edit.text().strip())

    def _update_name_validation(self) -> None:
        if self.name_edit.text().strip():
            self.name_edit.setStyleSheet("")
        else:
            self.name_edit.setStyleSheet("QLineEdit { border: 2px solid red; }")

    # --- Drag support (only from the handle) ---

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle_rect = self.drag_handle.geometry()
            if handle_rect.contains(event.position().toPoint()):
                self._drag_start = event.position().toPoint()
                self.drag_handle.setCursor(Qt.CursorShape.ClosedHandCursor)
                super().mousePressEvent(event)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_start is None:
            super().mouseMoveEvent(event)
            return
        dist = (event.position().toPoint() - self._drag_start).manhattanLength()
        if dist < 10:
            super().mouseMoveEvent(event)
            return

        # Capture drag pixmap BEFORE applying opacity effect
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setOpacity(0.7)
        self.render(painter, QPoint())
        painter.end()

        # Now make the in-place row transparent
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.25)
        self.setGraphicsEffect(effect)

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_MIME_TYPE, b"")
        drag.setMimeData(mime)
        drag.setPixmap(pixmap)
        drag.setHotSpot(self._drag_start)

        self._drag_start = None
        drag.exec(Qt.DropAction.MoveAction)

        # Restore after drag ends (drop or cancel)
        self.setGraphicsEffect(None)
        self.drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_start = None
        self.drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


class StatusLabelsEditor(QWidget):
    """Editor for STATUS_LABELS: list of (name, color, index)."""

    value_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[_StatusLabelRow] = []
        self._drop_indicator_y: int | None = None
        self.setAcceptDrops(True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 2, 0, 2)
        self._rows_layout.setSpacing(4)
        self._layout.addWidget(self._rows_container)

        self._add_btn = QPushButton("Add Label")
        self._add_btn.clicked.connect(self._on_add_row)
        self._layout.addWidget(self._add_btn)

    # --- Drag-and-drop ---

    def _drop_target_index(self, event) -> int:
        container_pos = self._rows_container.mapFrom(self, event.position().toPoint())
        drop_y = container_pos.y()
        target_idx = len(self._rows)
        for i, row in enumerate(self._rows):
            row_rect = row.geometry()
            row_mid = row_rect.top() + row_rect.height() / 2
            if drop_y < row_mid:
                target_idx = i
                break
        return target_idx

    def _indicator_y_for_index(self, target_idx: int) -> int:
        """Return the Y coordinate (in self) for the drop indicator line."""
        offset = self._rows_container.mapTo(self, QPoint(0, 0)).y()
        spacing = self._rows_layout.spacing()
        if not self._rows:
            return offset
        if target_idx <= 0:
            first = self._rows[0]
            return offset + first.geometry().top()
        if target_idx >= len(self._rows):
            last = self._rows[-1]
            return offset + last.geometry().bottom() + 1
        row = self._rows[target_idx]
        return offset + row.geometry().top() - spacing // 2 - 1

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(_MIME_TYPE):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(_MIME_TYPE):
            target_idx = self._drop_target_index(event)
            self._drop_indicator_y = self._indicator_y_for_index(target_idx)
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._drop_indicator_y = None
        self.update()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._drop_indicator_y = None
        self.update()

        source = event.source()
        if not isinstance(source, _StatusLabelRow) or source not in self._rows:
            return

        target_idx = self._drop_target_index(event)
        old_idx = self._rows.index(source)

        if old_idx == target_idx or old_idx + 1 == target_idx:
            return

        self._rows.pop(old_idx)
        if target_idx > old_idx:
            target_idx -= 1
        self._rows.insert(target_idx, source)
        self._rebuild_layout()
        self._update_indices()
        self.value_changed.emit()
        event.acceptProposedAction()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._drop_indicator_y is not None:
            painter = QPainter(self)
            pen = QPen(QColor("#3daee9"), 2)
            painter.setPen(pen)
            y = self._drop_indicator_y
            painter.drawLine(0, y, self.width(), y)
            painter.end()

    # --- Row management ---

    def _on_add_row(self):
        idx = len(self._rows) + 1
        self._add_row(StatusLabel(name="", color="#000000", index=idx))
        self._update_add_btn()
        self._update_indices()
        self.value_changed.emit()

    def _add_row(self, value: StatusLabel):
        row = _StatusLabelRow()
        row.set_value(value)
        row.remove_requested.connect(self._remove_row)
        row.value_changed.connect(self._on_row_changed)
        self._rows.append(row)
        self._rows_layout.addWidget(row)

    def _remove_row(self, row: _StatusLabelRow):
        if row not in self._rows:
            return
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.deleteLater()
        self._update_add_btn()
        self._update_indices()
        self.value_changed.emit()

    def _on_row_changed(self):
        self.value_changed.emit()

    def _rebuild_layout(self):
        for row in self._rows:
            self._rows_layout.removeWidget(row)
        for row in self._rows:
            self._rows_layout.addWidget(row)

    def _update_indices(self):
        for i, row in enumerate(self._rows):
            row.set_index(i + 1)

    def _update_add_btn(self):
        self._add_btn.setEnabled(len(self._rows) < _MAX_LABELS)

    def is_valid(self) -> bool:
        return all(row.has_valid_name() for row in self._rows)

    def set_value(self, value: list[StatusLabel] | None) -> None:
        for row in self._rows:
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows = []

        for item in value or []:
            self._add_row(item)

        self._update_add_btn()
        self._update_indices()

    def get_value(self) -> list[StatusLabel]:
        out: list[StatusLabel] = []
        for i, row in enumerate(self._rows):
            name, color = row.get_label_data()
            if not name:
                continue
            out.append(StatusLabel(name=name, color=color, index=i + 1))
        return out
