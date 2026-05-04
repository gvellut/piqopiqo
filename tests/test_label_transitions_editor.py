"""Tests for Flickr label-transition settings editor widgets."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QToolButton
import pytest

from piqopiqo.model import LabelTransitionRule, StatusLabel
from piqopiqo.settings_panel import label_transitions_editor as lte
from piqopiqo.ssf.settings_state import (
    UserSettingKey,
    init_qsettings_store,
    set_user_setting,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.STATUS_LABELS,
        [
            StatusLabel("Approved", "#ff0000", 1),
            StatusLabel("Rejected", "#ffff00", 2),
            StatusLabel("Uploaded", "#00ff00", 3),
        ],
    )
    return app


def test_label_transition_summary_pluralization():
    assert lte.format_label_transitions_summary(0) == "No rule"
    assert lte.format_label_transitions_summary(1) == "1 rule"
    assert lte.format_label_transitions_summary(2) == "2 rules"


def _widget_xy(widget):
    position = widget.pos()
    return position.x(), position.y()


def _center_y(widget):
    return widget.geometry().center().y()


def test_label_transition_rule_dialog_validation(qapp):  # noqa: ARG001
    dialog = lte._LabelTransitionRuleDialog(
        title="Add Transition",
        rules=[LabelTransitionRule("Approved", "Uploaded")],
    )
    dialog.show()
    qapp.processEvents()

    assert dialog.ok_btn.isEnabled() is False
    assert dialog.minimumWidth() == 340
    assert dialog.from_combo.count() == 5
    assert dialog.to_combo.count() == 5
    assert dialog.from_combo.itemText(0) == "Choose label..."
    assert dialog.from_combo.itemData(0) is None
    assert dialog.from_combo.itemText(1) == "No Label"
    assert dialog.from_combo.itemData(1) == ""
    assert dialog.from_combo.itemIcon(1).isNull() is False
    assert dialog.from_combo.itemIcon(2).isNull() is False
    assert abs(_center_y(dialog.from_label) - _center_y(dialog.from_combo)) <= 1
    assert abs(_center_y(dialog.to_label) - _center_y(dialog.to_combo)) <= 1
    initial_invalid_height = dialog.height()

    initial_positions = (
        _widget_xy(dialog.from_label),
        _widget_xy(dialog.from_combo),
        _widget_xy(dialog.to_label),
        _widget_xy(dialog.to_combo),
    )

    dialog.from_combo.setCurrentIndex(1)
    dialog.to_combo.setCurrentIndex(2)
    qapp.processEvents()
    assert dialog.ok_btn.isEnabled() is True
    assert dialog.get_value() == LabelTransitionRule("", "Approved")
    valid_height = dialog.height()
    assert dialog.error_label.isVisible() is False
    assert valid_height < initial_invalid_height
    assert (
        _widget_xy(dialog.from_label),
        _widget_xy(dialog.from_combo),
        _widget_xy(dialog.to_label),
        _widget_xy(dialog.to_combo),
    ) == initial_positions

    dialog.to_combo.setCurrentIndex(1)
    qapp.processEvents()
    assert dialog.ok_btn.isEnabled() is False
    assert dialog.error_label.isVisible() is True
    assert dialog.height() > valid_height
    assert (
        _widget_xy(dialog.from_label),
        _widget_xy(dialog.from_combo),
        _widget_xy(dialog.to_label),
        _widget_xy(dialog.to_combo),
    ) == initial_positions

    dialog.from_combo.setCurrentIndex(2)
    dialog.to_combo.setCurrentIndex(3)
    qapp.processEvents()
    assert dialog.ok_btn.isEnabled() is False
    assert "already has a transition" in dialog.error_label.text()
    assert (
        _widget_xy(dialog.from_label),
        _widget_xy(dialog.from_combo),
        _widget_xy(dialog.to_label),
        _widget_xy(dialog.to_combo),
    ) == initial_positions


def test_label_transitions_dialog_add_edit_delete_and_button_state(
    monkeypatch,
    qapp,  # noqa: ARG001
):
    dialog = lte._LabelTransitionsDialog()
    dialog.show()
    qapp.processEvents()

    assert isinstance(dialog._add_btn, QToolButton)
    assert isinstance(dialog._edit_btn, QToolButton)
    assert isinstance(dialog._delete_btn, QToolButton)
    assert dialog._edit_btn.isEnabled() is False
    assert dialog._delete_btn.isEnabled() is False
    assert dialog.ok_btn.isEnabled() is True

    responses = [
        (QDialog.DialogCode.Accepted, LabelTransitionRule("Approved", "Uploaded")),
        (QDialog.DialogCode.Accepted, LabelTransitionRule("Rejected", "")),
    ]

    class _DialogStub:
        def __init__(self, **_kwargs):
            result, value = responses.pop(0)
            self._result = result
            self._value = value

        def exec(self):
            return self._result

        def get_value(self):
            return self._value

    monkeypatch.setattr(lte, "_LabelTransitionRuleDialog", _DialogStub)

    dialog._on_add()
    assert dialog.get_value() == [LabelTransitionRule("Approved", "Uploaded")]
    item = dialog._list.item(0)
    assert item.text() == ""
    assert item.data(Qt.ItemDataRole.UserRole) == "Approved → Uploaded"
    assert item.toolTip() == "Approved → Uploaded"
    row = dialog._list.itemWidget(item)
    assert row is not None
    from_swatch = row.findChild(QLabel, "from_color")
    to_swatch = row.findChild(QLabel, "to_color")
    arrow = row.findChild(QLabel, "transition_arrow")
    assert from_swatch is not None
    assert to_swatch is not None
    assert arrow is not None
    assert arrow.text() == "→"
    assert from_swatch.pixmap() is not None
    assert from_swatch.pixmap().isNull() is False
    assert to_swatch.pixmap() is not None
    assert to_swatch.pixmap().isNull() is False

    assert item is not None
    item.setSelected(True)
    dialog._list.setCurrentItem(item)
    qapp.processEvents()
    assert dialog._edit_btn.isEnabled() is True
    assert dialog._delete_btn.isEnabled() is True

    dialog._on_edit()
    assert dialog.get_value() == [LabelTransitionRule("Rejected", "")]
    assert dialog._list.item(0).text() == ""
    assert dialog._list.item(0).data(Qt.ItemDataRole.UserRole) == "Rejected → No Label"

    dialog._on_delete()
    assert dialog.get_value() == []
    assert dialog._edit_btn.isEnabled() is False
    assert dialog._delete_btn.isEnabled() is False


def test_label_transitions_editor_summary_updates_after_dialog_accept(
    monkeypatch,
    qapp,  # noqa: ARG001
):
    editor = lte.LabelTransitionsEditor()
    assert editor._summary_label.text() == "No rule"

    returned_rules = [
        LabelTransitionRule("Approved", "Uploaded"),
        LabelTransitionRule("Rejected", ""),
    ]

    class _DialogStub:
        def __init__(self, _rules, parent=None):  # noqa: ARG002
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def get_value(self):
            return returned_rules

    monkeypatch.setattr(lte, "_LabelTransitionsDialog", _DialogStub)

    emitted: list[bool] = []
    editor.value_changed.connect(lambda: emitted.append(True))
    editor._on_edit()

    assert editor._summary_label.text() == "2 rules"
    assert editor.get_value() == returned_rules
    assert emitted == [True]
