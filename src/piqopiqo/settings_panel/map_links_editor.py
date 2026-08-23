"""Custom editor widget for metadata-panel map links."""

from __future__ import annotations

from string import Formatter

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.dialogs.unsaved_changes_dialog import UnsavedChangesDialog
from piqopiqo.model import MapLinkOption

_INVALID_STYLE = "QLineEdit { border: 2px solid red; }"
_ALLOWED_MAP_LINK_FIELDS = {"lat", "lon"}

PREDEFINED_MAP_LINK_OPTIONS: tuple[MapLinkOption, ...] = (
    MapLinkOption(
        name="Google Maps",
        url_template="https://www.google.com/maps/search/?api=1&query={lat},{lon}",
    ),
    MapLinkOption(
        name="OpenStreetMap",
        url_template="https://www.openstreetmap.org/#map=19/{lat}/{lon}",
    ),
)


def _build_plus_icon() -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor("#1f9d55")
    painter.fillRect(3, 7, 10, 2, color)
    painter.fillRect(7, 3, 2, 10, color)
    painter.end()

    return QIcon(pixmap)


def _build_minus_icon() -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillRect(3, 7, 10, 2, QColor("#cc3344"))
    painter.end()

    return QIcon(pixmap)


def _build_edit_icon() -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    outline = QColor("#3f3f46")

    pen = QPen(outline)
    pen.setWidth(1)
    painter.setPen(pen)
    painter.setBrush(Qt.GlobalColor.white)
    painter.drawRect(3, 2, 8, 11)
    painter.drawLine(9, 2, 11, 4)
    painter.drawLine(11, 4, 11, 13)

    pen.setWidth(2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(7, 11, 12, 6)
    painter.drawLine(11, 5, 13, 7)
    painter.end()

    return QIcon(pixmap)


def format_map_links_summary(count: int) -> str:
    suffix = "option" if count == 1 else "options"
    return f"{count} {suffix} defined"


def is_valid_map_link_template(value: str) -> bool:
    text = str(value).strip()
    if not text:
        return False

    fields_found: set[str] = set()
    try:
        for _literal, field_name, _format_spec, _conversion in Formatter().parse(text):
            if field_name is None:
                continue
            if field_name not in _ALLOWED_MAP_LINK_FIELDS:
                return False
            fields_found.add(field_name)
    except ValueError:
        return False

    return fields_found == _ALLOWED_MAP_LINK_FIELDS


class _MapLinkOptionDialog(UnsavedChangesDialog):
    def __init__(
        self,
        *,
        title: str,
        initial: MapLinkOption | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(440)
        self._predefined_menu: QMenu | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._form_layout = QGridLayout()
        self._form_layout.setContentsMargins(0, 0, 0, 0)
        self._form_layout.setHorizontalSpacing(8)
        self._form_layout.setVerticalSpacing(6)
        self._form_layout.setColumnStretch(1, 1)

        self.name_label = QLabel("Name", self)
        self.name_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("Google Maps")
        self._form_layout.addWidget(self.name_label, 0, 0)
        self._form_layout.addWidget(self.name_edit, 0, 1)

        self.url_label = QLabel("URL", self)
        self.url_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.url_edit = QLineEdit(self)
        self.url_edit.setPlaceholderText(
            "https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        )
        self._form_layout.addWidget(self.url_label, 1, 0)
        self._form_layout.addWidget(self.url_edit, 1, 1)

        self.predefined_btn = QPushButton("Predefined...", self)
        self.predefined_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.predefined_btn.setDefault(False)
        self.predefined_btn.setAutoDefault(False)
        self._form_layout.addWidget(
            self.predefined_btn,
            2,
            1,
            alignment=Qt.AlignmentFlag.AlignLeft,
        )

        layout.addLayout(self._form_layout)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setDefault(False)
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_btn)

        self._ok_btn = QPushButton("OK", self)
        self._ok_btn.setDefault(False)
        self._ok_btn.setAutoDefault(False)
        self._ok_btn.clicked.connect(self.accept)
        button_row.addWidget(self._ok_btn)

        layout.addLayout(button_row)

        self.name_edit.textChanged.connect(self._update_validity)
        self.url_edit.textChanged.connect(self._update_validity)
        self.predefined_btn.clicked.connect(self._on_open_predefined_menu)

        if initial is not None:
            self.name_edit.setText(initial.name)
            self.url_edit.setText(initial.url_template)

        self._update_validity()
        self._set_unsaved_changes_state(
            lambda: (self.name_edit.text(), self.url_edit.text())
        )

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(
            0, lambda: self.name_edit.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        )

    def _apply_predefined_option(self, option: MapLinkOption) -> None:
        self.name_edit.setText(option.name)
        self.url_edit.setText(option.url_template)

    def _on_open_predefined_menu(self) -> None:
        if self._predefined_menu is not None:
            self._predefined_menu.deleteLater()

        menu = QMenu(self.predefined_btn)
        for option in PREDEFINED_MAP_LINK_OPTIONS:
            action = menu.addAction(option.name)
            action.triggered.connect(
                lambda _checked=False, current_option=option: (
                    self._apply_predefined_option(current_option)
                )
            )
        self._predefined_menu = menu
        menu.popup(
            self.predefined_btn.mapToGlobal(self.predefined_btn.rect().bottomLeft())
        )

    def _set_line_validity(self, line_edit: QLineEdit, *, valid: bool) -> None:
        line_edit.setStyleSheet("" if valid else _INVALID_STYLE)

    def _update_validity(self) -> None:
        name_valid = bool(self.name_edit.text().strip())
        url_text = self.url_edit.text().strip()
        url_valid = bool(url_text) and is_valid_map_link_template(url_text)

        self._set_line_validity(self.name_edit, valid=name_valid)
        self._set_line_validity(self.url_edit, valid=url_valid)
        self._ok_btn.setEnabled(name_valid and url_valid)

    def get_value(self) -> MapLinkOption:
        return MapLinkOption(
            name=self.name_edit.text().strip(),
            url_template=self.url_edit.text().strip(),
        )


class _MapLinksDialog(UnsavedChangesDialog):
    def __init__(self, options: list[MapLinkOption] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Map Links")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._options: list[MapLinkOption] = []

        layout = QVBoxLayout(self)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(8)

        self._list = QListWidget(self)
        self._list.itemSelectionChanged.connect(self._update_buttons)
        content_layout.addWidget(self._list, 1)

        buttons_layout = QVBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(6)

        self._add_btn = QToolButton(self)
        self._add_btn.setIcon(_build_plus_icon())
        self._add_btn.setToolTip("Add map link")
        self._add_btn.setAccessibleName("Add")
        self._add_btn.setIconSize(QSize(16, 16))
        self._add_btn.setFixedSize(28, 28)
        self._add_btn.setStyleSheet("QToolButton { padding: 0px; }")
        self._add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._add_btn.clicked.connect(self._on_add)
        buttons_layout.addWidget(self._add_btn)

        self._edit_btn = QToolButton(self)
        self._edit_btn.setIcon(_build_edit_icon())
        self._edit_btn.setToolTip("Edit selected map link")
        self._edit_btn.setAccessibleName("Edit")
        self._edit_btn.setIconSize(QSize(16, 16))
        self._edit_btn.setFixedSize(28, 28)
        self._edit_btn.setStyleSheet("QToolButton { padding: 0px; }")
        self._edit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._edit_btn.clicked.connect(self._on_edit)
        buttons_layout.addWidget(self._edit_btn)

        self._delete_btn = QToolButton(self)
        self._delete_btn.setIcon(_build_minus_icon())
        self._delete_btn.setToolTip("Delete selected map link")
        self._delete_btn.setAccessibleName("Delete")
        self._delete_btn.setIconSize(QSize(16, 16))
        self._delete_btn.setFixedSize(28, 28)
        self._delete_btn.setStyleSheet("QToolButton { padding: 0px; }")
        self._delete_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._delete_btn.clicked.connect(self._on_delete)
        buttons_layout.addWidget(self._delete_btn)

        buttons_layout.addStretch(1)
        content_layout.addLayout(buttons_layout)

        layout.addLayout(content_layout)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setDefault(False)
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_btn)

        self.ok_btn = QPushButton("OK", self)
        self.ok_btn.setDefault(False)
        self.ok_btn.setAutoDefault(False)
        self.ok_btn.clicked.connect(self.accept)
        button_row.addWidget(self.ok_btn)

        layout.addLayout(button_row)

        self.set_value(options or [])
        self._set_unsaved_changes_state(lambda: tuple(self._options))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._focus_list_without_selection)

    def _selected_index(self) -> int | None:
        selected_indexes = self._list.selectedIndexes()
        if len(selected_indexes) != 1:
            return None
        index = selected_indexes[0].row()
        if index < 0 or index >= len(self._options):
            return None
        return index

    def _clear_selection(self) -> None:
        self._list.setCurrentItem(None)
        self._list.clearSelection()
        self._update_buttons()

    def _focus_list_without_selection(self) -> None:
        self._clear_selection()
        self._list.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def _update_buttons(self, *_args) -> None:
        has_selection = self._selected_index() is not None
        self._edit_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)

    def _refresh_list(self, *, selected_index: int | None = None) -> None:
        self._list.clear()
        for option in self._options:
            self._list.addItem(option.name)
        if selected_index is None or selected_index >= self._list.count():
            self._clear_selection()
            return

        item = self._list.item(selected_index)
        if item is None:
            self._clear_selection()
            return
        item.setSelected(True)
        self._list.setCurrentItem(item)
        self._update_buttons()

    def _on_add(self) -> None:
        dialog = _MapLinkOptionDialog(title="Add Map Link", parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._options.append(dialog.get_value())
        self._refresh_list()

    def _on_edit(self) -> None:
        index = self._selected_index()
        if index is None:
            return

        dialog = _MapLinkOptionDialog(
            title="Edit Map Link",
            initial=self._options[index],
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._options[index] = dialog.get_value()
        self._refresh_list(selected_index=index)

    def _on_delete(self) -> None:
        index = self._selected_index()
        if index is None:
            return

        del self._options[index]
        self._refresh_list()

    def is_valid(self) -> bool:
        for option in self._options:
            name = str(option.name).strip()
            url_template = str(option.url_template).strip()
            if not name or not url_template:
                return False
            if not is_valid_map_link_template(url_template):
                return False
        return True

    def set_value(self, value: list[MapLinkOption] | None) -> None:
        self._options = [
            MapLinkOption(
                name=str(option.name).strip(),
                url_template=str(option.url_template).strip(),
            )
            for option in (value or [])
        ]
        self._refresh_list()

    def get_value(self) -> list[MapLinkOption]:
        return list(self._options)


class MapLinksEditor(QWidget):
    """Summary editor for MAP_LINKS with a modal manager dialog."""

    value_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._options: list[MapLinkOption] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._summary_label = QLabel(self)
        self._summary_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._summary_label)

        self._edit_btn = QPushButton("Edit...", self)
        self._edit_btn.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect)
        self._edit_btn.clicked.connect(self._on_edit)
        layout.addWidget(self._edit_btn)

        layout.addStretch(1)

        self._refresh_summary()

    def _refresh_summary(self) -> None:
        self._summary_label.setText(format_map_links_summary(len(self._options)))

    def _on_edit(self) -> None:
        dialog = _MapLinksDialog(self._options, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._options = dialog.get_value()
        self._refresh_summary()
        self.value_changed.emit()

    def is_valid(self) -> bool:
        for option in self._options:
            name = str(option.name).strip()
            url_template = str(option.url_template).strip()
            if not name or not url_template:
                return False
            if not is_valid_map_link_template(url_template):
                return False
        return True

    def set_value(self, value: list[MapLinkOption] | None) -> None:
        self._options = [
            MapLinkOption(
                name=str(option.name).strip(),
                url_template=str(option.url_template).strip(),
            )
            for option in (value or [])
        ]
        self._refresh_summary()

    def get_value(self) -> list[MapLinkOption]:
        return list(self._options)
