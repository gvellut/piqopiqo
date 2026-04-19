"""Tests for map-link settings editor widgets."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGridLayout,
    QPushButton,
    QToolButton,
)
import pytest

from piqopiqo.model import MapLinkOption
from piqopiqo.settings_panel import map_links_editor as mle


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_map_link_option_dialog_layout_and_predefined_overwrites(  # noqa: ARG001
    monkeypatch, qapp
):
    dialog = mle._MapLinkOptionDialog(title="Add Map Link")
    dialog.show()
    QApplication.processEvents()

    assert isinstance(dialog._form_layout, QGridLayout)
    assert dialog._form_layout.itemAtPosition(2, 0) is None
    assert dialog._form_layout.horizontalSpacing() == 8
    assert isinstance(dialog.predefined_btn, QPushButton)
    assert dialog.predefined_btn.text() == "Predefined..."
    assert dialog.minimumWidth() == 440
    assert dialog.name_edit.x() == dialog.url_edit.x()
    assert dialog.name_label.x() == dialog.url_label.x()
    assert dialog.predefined_btn.x() == dialog.url_edit.x()
    assert dialog.predefined_btn.width() < dialog.url_edit.width()
    assert dialog.predefined_btn.isDefault() is False
    assert dialog.predefined_btn.autoDefault() is False
    assert dialog._ok_btn.isEnabled() is False
    assert dialog._ok_btn.isDefault() is False
    assert dialog._ok_btn.autoDefault() is False
    assert dialog.cancel_btn.isDefault() is False
    assert dialog.cancel_btn.autoDefault() is False
    assert dialog.name_edit.hasFocus() is True

    dialog.name_edit.setText("My Map")
    dialog.url_edit.setText("https://example.com/{lat}/{lon}")
    assert dialog._ok_btn.isEnabled() is True

    dialog.url_edit.setText("https://example.com/{lat}")
    assert dialog._ok_btn.isEnabled() is False
    assert dialog.url_edit.styleSheet() != ""

    dialog.url_edit.setText("https://example.com/{foo}/{lon}")
    assert dialog._ok_btn.isEnabled() is False

    popup_positions = []

    def _fake_popup(menu, pos):
        popup_positions.append(pos)

    monkeypatch.setattr(mle.QMenu, "popup", _fake_popup)
    dialog.url_edit.setText("https://old.example")
    dialog._on_open_predefined_menu()
    assert dialog._predefined_menu is not None
    assert [action.text() for action in dialog._predefined_menu.actions()] == [
        option.name for option in mle.PREDEFINED_MAP_LINK_OPTIONS
    ]
    assert popup_positions == [
        dialog.predefined_btn.mapToGlobal(dialog.predefined_btn.rect().bottomLeft())
    ]
    dialog._predefined_menu.actions()[0].trigger()
    assert dialog.name_edit.text() == "Google Maps"
    assert (
        dialog.url_edit.text()
        == "https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    )
    assert dialog._ok_btn.isEnabled() is True


def test_map_links_dialog_add_edit_delete_and_button_state(monkeypatch, qapp):  # noqa: ARG001
    dialog = mle._MapLinksDialog()
    dialog.show()
    qapp.processEvents()

    assert isinstance(dialog._add_btn, QToolButton)
    assert isinstance(dialog._edit_btn, QToolButton)
    assert isinstance(dialog._delete_btn, QToolButton)
    assert dialog._add_btn.text() == ""
    assert dialog._edit_btn.text() == ""
    assert dialog._delete_btn.text() == ""
    assert dialog._list.currentRow() == -1
    assert dialog._list.selectedItems() == []
    assert dialog._edit_btn.isEnabled() is False
    assert dialog._delete_btn.isEnabled() is False
    assert dialog.ok_btn.isDefault() is False
    assert dialog.ok_btn.autoDefault() is False
    assert dialog.cancel_btn.isDefault() is False
    assert dialog.cancel_btn.autoDefault() is False
    assert dialog.cancel_btn.x() < dialog.ok_btn.x()

    responses = [
        (
            QDialog.DialogCode.Accepted,
            MapLinkOption(
                name="Google Maps",
                url_template=(
                    "https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                ),
            ),
        ),
        (
            QDialog.DialogCode.Accepted,
            MapLinkOption(
                name="OpenStreetMap",
                url_template="https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=19/{lat}/{lon}",
            ),
        ),
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

    monkeypatch.setattr(mle, "_MapLinkOptionDialog", _DialogStub)

    dialog._on_add()
    assert dialog.get_value() == [
        MapLinkOption(
            name="Google Maps",
            url_template=(
                "https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            ),
        )
    ]
    assert dialog._list.currentRow() == -1
    assert dialog._list.selectedItems() == []
    assert dialog._edit_btn.isEnabled() is False
    assert dialog._delete_btn.isEnabled() is False

    item = dialog._list.item(0)
    assert item is not None
    item.setSelected(True)
    dialog._list.setCurrentItem(item)
    qapp.processEvents()
    assert dialog._edit_btn.isEnabled() is True
    assert dialog._delete_btn.isEnabled() is True

    dialog._on_edit()
    assert dialog.get_value() == [
        MapLinkOption(
            name="OpenStreetMap",
            url_template="https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=19/{lat}/{lon}",
        )
    ]

    dialog._on_delete()
    assert dialog.get_value() == []
    assert dialog._list.currentRow() == -1
    assert dialog._list.selectedItems() == []
    assert dialog._edit_btn.isEnabled() is False
    assert dialog._delete_btn.isEnabled() is False


def test_map_links_editor_summary_updates_after_dialog_accept(monkeypatch, qapp):  # noqa: ARG001
    editor = mle.MapLinksEditor()
    assert editor._summary_label.text() == "0 options defined"

    returned_options = [
        MapLinkOption(
            name="Map A",
            url_template="https://example.com/{lat}/{lon}",
        ),
        MapLinkOption(
            name="Map B",
            url_template="https://maps.example/?q={lat},{lon}",
        ),
    ]

    class _DialogStub:
        def __init__(self, _options, parent=None):  # noqa: ARG002
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def get_value(self):
            return returned_options

    monkeypatch.setattr(mle, "_MapLinksDialog", _DialogStub)

    emitted: list[bool] = []
    editor.value_changed.connect(lambda: emitted.append(True))
    editor._on_edit()

    assert editor._summary_label.text() == "2 options defined"
    assert editor.get_value() == returned_options
    assert emitted == [True]
