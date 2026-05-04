"""Custom editor widget for Flickr upload label transitions."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.components.ellided_label import EllidedLabel
from piqopiqo.label_transitions import is_valid_label_transition_rules
from piqopiqo.model import LabelTransitionRule, StatusLabel
from piqopiqo.ssf.settings_state import UserSettingKey, get_user_setting

from .map_links_editor import _build_edit_icon, _build_minus_icon, _build_plus_icon

_NO_LABEL_DISPLAY = "No Label"
_TRANSITION_ARROW = "→"
StatusLabelProvider = Callable[[], list[StatusLabel]]


def format_label_transitions_summary(count: int) -> str:
    if count <= 0:
        return "No rule"
    if count == 1:
        return "1 rule"
    return f"{count} rules"


def _display_label(value: str) -> str:
    text = str(value or "").strip()
    return text if text else _NO_LABEL_DISPLAY


def _as_rule(value: object) -> LabelTransitionRule | None:
    if isinstance(value, LabelTransitionRule):
        return LabelTransitionRule(
            from_label=str(value.from_label).strip(),
            to_label=str(value.to_label).strip(),
        )
    if not isinstance(value, dict):
        return None
    return LabelTransitionRule(
        from_label=str(value.get("from_label", "")).strip(),
        to_label=str(value.get("to_label", "")).strip(),
    )


def _current_status_labels() -> list[StatusLabel]:
    return list(get_user_setting(UserSettingKey.STATUS_LABELS) or [])


def _status_labels_from_provider(provider: StatusLabelProvider) -> list[StatusLabel]:
    return list(provider() or [])


def _status_label_color(status_labels: list[StatusLabel], value: str) -> str:
    target = str(value or "").strip()
    if not target:
        return ""
    for label in status_labels:
        if str(label.name).strip() == target:
            return str(label.color or "").strip()
    return ""


def _build_swatch_icon(color: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = pixmap.rect().adjusted(2, 2, -2, -2)
    color_value = str(color or "").strip()
    if color_value:
        painter.fillRect(rect, QColor(color_value))
    painter.setPen(QPen(QColor("#888888"), 1))
    painter.drawRect(rect)
    painter.end()

    return QIcon(pixmap)


def _configure_action_button(
    button: QToolButton,
    *,
    icon,
    tooltip: str,
    accessible_name: str,
) -> None:
    button.setIcon(icon)
    button.setToolTip(tooltip)
    button.setAccessibleName(accessible_name)
    button.setIconSize(QSize(16, 16))
    button.setFixedSize(28, 28)
    button.setStyleSheet("QToolButton { padding: 0px; }")
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class _LabelTransitionRuleDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        rules: list[LabelTransitionRule],
        status_labels: list[StatusLabel] | None = None,
        editing_index: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(340)
        self._status_labels = list(
            status_labels if status_labels is not None else _current_status_labels()
        )
        self._editing_index = editing_index
        self._rules = list(rules)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        form_layout = QGridLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setHorizontalSpacing(8)
        form_layout.setVerticalSpacing(6)
        form_layout.setColumnStretch(1, 1)

        self.from_label = QLabel("From", self)
        self.from_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.from_combo = QComboBox(self)
        self.from_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.from_combo.currentIndexChanged.connect(self._update_validity)
        form_layout.addWidget(self.from_label, 0, 0)
        form_layout.addWidget(self.from_combo, 0, 1)

        self.to_label = QLabel("To", self)
        self.to_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.to_combo = QComboBox(self)
        self.to_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.to_combo.currentIndexChanged.connect(self._update_validity)
        form_layout.addWidget(self.to_label, 1, 0)
        form_layout.addWidget(self.to_combo, 1, 1)

        layout.addLayout(form_layout)

        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

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

        self._populate_label_combo(self.from_combo)
        self._populate_label_combo(self.to_combo)

        if editing_index is not None and 0 <= editing_index < len(self._rules):
            rule = self._rules[editing_index]
            self._select_value(self.from_combo, rule.from_label)
            self._select_value(self.to_combo, rule.to_label)

        self._update_validity()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(
            0, lambda: self.from_combo.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        )

    def _populate_label_combo(self, combo: QComboBox) -> None:
        combo.addItem("Choose label...", None)
        entries = [("", _NO_LABEL_DISPLAY, "")]
        entries.extend(
            (label.name, label.name, label.color)
            for label in self._status_labels
            if str(label.name).strip()
        )
        for value, text, color in entries:
            combo.addItem(
                _build_swatch_icon(str(color)),
                str(text),
                str(value).strip(),
            )

    def _select_value(self, combo: QComboBox, value: str) -> None:
        expected = str(value or "").strip()
        for row in range(combo.count()):
            if combo.itemData(row) == expected:
                combo.setCurrentIndex(row)
                return

    def _selected_value(self, combo: QComboBox) -> str | None:
        value = combo.currentData()
        if value is None:
            return None
        return str(value or "").strip()

    def _duplicate_from_values(self) -> set[str]:
        values: set[str] = set()
        for index, rule in enumerate(self._rules):
            if self._editing_index is not None and index == self._editing_index:
                continue
            values.add(rule.from_label)
        return values

    def _update_validity(self, *_args) -> None:
        from_value = self._selected_value(self.from_combo)
        to_value = self._selected_value(self.to_combo)

        error = ""
        if from_value is None or to_value is None:
            error = "Choose both labels."
        elif from_value == to_value:
            error = "From and To must be different."
        elif from_value in self._duplicate_from_values():
            error = "This From label already has a transition."

        if error:
            self.error_label.setText(error)
            self.error_label.show()
            self.ok_btn.setEnabled(False)
            self._resize_to_current_message()
            return

        self.error_label.clear()
        self.error_label.hide()
        self.ok_btn.setEnabled(True)
        self._resize_to_current_message()

    def _resize_to_current_message(self) -> None:
        if self.isVisible():
            self.adjustSize()

    def get_value(self) -> LabelTransitionRule:
        return LabelTransitionRule(
            from_label=self._selected_value(self.from_combo) or "",
            to_label=self._selected_value(self.to_combo) or "",
        )


class _LabelTransitionsDialog(QDialog):
    def __init__(
        self,
        rules: list[LabelTransitionRule] | None = None,
        *,
        status_labels: list[StatusLabel] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Transitions")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._rules: list[LabelTransitionRule] = []
        self._status_labels = list(
            status_labels if status_labels is not None else _current_status_labels()
        )

        layout = QVBoxLayout(self)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(8)

        self._list = QListWidget(self)
        self._list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._list.itemSelectionChanged.connect(self._update_buttons)
        content_layout.addWidget(self._list, 1)

        buttons_layout = QVBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(6)

        self._add_btn = QToolButton(self)
        _configure_action_button(
            self._add_btn,
            icon=_build_plus_icon(),
            tooltip="Add transition",
            accessible_name="Add",
        )
        self._add_btn.clicked.connect(self._on_add)
        buttons_layout.addWidget(self._add_btn)

        self._edit_btn = QToolButton(self)
        _configure_action_button(
            self._edit_btn,
            icon=_build_edit_icon(),
            tooltip="Edit selected transition",
            accessible_name="Edit",
        )
        self._edit_btn.clicked.connect(self._on_edit)
        buttons_layout.addWidget(self._edit_btn)

        self._delete_btn = QToolButton(self)
        _configure_action_button(
            self._delete_btn,
            icon=_build_minus_icon(),
            tooltip="Delete selected transition",
            accessible_name="Delete",
        )
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

        self.set_value(rules or [])

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._focus_list_without_selection)

    def _selected_index(self) -> int | None:
        selected_indexes = self._list.selectedIndexes()
        if len(selected_indexes) != 1:
            return None
        index = selected_indexes[0].row()
        if index < 0 or index >= len(self._rules):
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
        self.ok_btn.setEnabled(self.is_valid())

    def _refresh_list(self, *, selected_index: int | None = None) -> None:
        self._list.clear()
        for rule in self._rules:
            text = (
                f"{_display_label(rule.from_label)} "
                f"{_TRANSITION_ARROW} {_display_label(rule.to_label)}"
            )
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, text)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, text)
            item.setToolTip(text)
            self._list.addItem(item)
            row = self._build_rule_row(rule, text)
            item.setSizeHint(row.sizeHint())
            self._list.setItemWidget(item, row)

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

    def _build_rule_row(self, rule: LabelTransitionRule, tooltip: str) -> QWidget:
        row = QWidget(self._list)
        row.setToolTip(tooltip)
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(8)

        from_swatch = self._build_row_swatch(rule.from_label, "From color")
        layout.addWidget(from_swatch)

        from_label = EllidedLabel(_display_label(rule.from_label), row)
        from_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        from_label.setToolTip(_display_label(rule.from_label))
        from_label.setMinimumWidth(24)
        from_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(from_label)

        arrow_label = QLabel(_TRANSITION_ARROW, row)
        arrow_label.setObjectName("transition_arrow")
        arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow_label.setContentsMargins(4, 0, 4, 0)
        arrow_label.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(arrow_label)

        to_swatch = self._build_row_swatch(rule.to_label, "To color")
        layout.addWidget(to_swatch)

        to_label = EllidedLabel(_display_label(rule.to_label), row)
        to_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        to_label.setToolTip(_display_label(rule.to_label))
        to_label.setMinimumWidth(24)
        to_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(to_label)

        return row

    def _build_row_swatch(self, value: str, accessible_name: str) -> QLabel:
        swatch = QLabel(self._list)
        swatch.setAccessibleName(accessible_name)
        swatch.setObjectName(accessible_name.replace(" ", "_").lower())
        swatch.setFixedSize(16, 16)
        color = _status_label_color(self._status_labels, value)
        swatch.setPixmap(_build_swatch_icon(color).pixmap(16, 16))
        return swatch

    def _on_add(self) -> None:
        dialog = _LabelTransitionRuleDialog(
            title="Add Transition",
            rules=self._rules,
            status_labels=self._status_labels,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._rules.append(dialog.get_value())
        self._refresh_list()

    def _on_edit(self) -> None:
        index = self._selected_index()
        if index is None:
            return

        dialog = _LabelTransitionRuleDialog(
            title="Edit Transition",
            rules=self._rules,
            status_labels=self._status_labels,
            editing_index=index,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._rules[index] = dialog.get_value()
        self._refresh_list(selected_index=index)

    def _on_delete(self) -> None:
        index = self._selected_index()
        if index is None:
            return

        del self._rules[index]
        self._refresh_list()

    def is_valid(self) -> bool:
        return is_valid_label_transition_rules(
            self._rules,
            status_labels=self._status_labels,
        )

    def set_value(self, value: list[LabelTransitionRule] | None) -> None:
        rules: list[LabelTransitionRule] = []
        for raw in value or []:
            rule = _as_rule(raw)
            if rule is not None:
                rules.append(rule)
        self._rules = rules
        self._refresh_list()

    def get_value(self) -> list[LabelTransitionRule]:
        return list(self._rules)


class LabelTransitionsEditor(QWidget):
    """Summary editor for Flickr label transitions."""

    value_changed = Signal()

    def __init__(
        self,
        parent=None,
        *,
        status_label_provider: StatusLabelProvider | None = None,
    ):
        super().__init__(parent)
        self._rules: list[LabelTransitionRule] = []
        self._status_label_provider = status_label_provider or _current_status_labels

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
        self._edit_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self._edit_btn.clicked.connect(self._on_edit)
        layout.addWidget(self._edit_btn)

        layout.addStretch(1)

        self._refresh_summary()

    def _refresh_summary(self) -> None:
        self._summary_label.setText(format_label_transitions_summary(len(self._rules)))

    def set_status_label_provider(
        self,
        provider: StatusLabelProvider | None,
    ) -> None:
        self._status_label_provider = provider or _current_status_labels

    def _status_labels(self) -> list[StatusLabel]:
        return _status_labels_from_provider(self._status_label_provider)

    def _on_edit(self) -> None:
        dialog = _LabelTransitionsDialog(
            self._rules,
            status_labels=self._status_labels(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._rules = dialog.get_value()
        self._refresh_summary()
        self.value_changed.emit()

    def is_valid(self) -> bool:
        return is_valid_label_transition_rules(
            self._rules,
            status_labels=self._status_labels(),
        )

    def set_value(self, value: list[LabelTransitionRule] | None) -> None:
        rules: list[LabelTransitionRule] = []
        for raw in value or []:
            rule = _as_rule(raw)
            if rule is not None:
                rules.append(rule)
        self._rules = rules
        self._refresh_summary()

    def get_value(self) -> list[LabelTransitionRule]:
        return list(self._rules)
