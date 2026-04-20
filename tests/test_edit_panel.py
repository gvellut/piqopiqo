"""Tests for edit panel UI behaviors."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication, QPoint
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.model import ImageItem, MapLinkOption
from piqopiqo.panels.edit_panel import EditPanel
from piqopiqo.panels.edit_widgets import MULTIPLE_VALUES
from piqopiqo.ssf.settings_state import (
    UserSettingKey,
    init_qsettings_store,
    set_user_setting,
)


class _DummyDBManager:
    pass


class _StubDB:
    def has_metadata(self, _path: str) -> bool:
        return True


class _StubDBManager:
    def __init__(self) -> None:
        self.db = _StubDB()

    def get_db_for_image(self, _path: str) -> _StubDB:
        return self.db


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-edit-panel-{uuid.uuid4().hex}")
    return app


def test_description_field_visibility_follows_user_setting(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.SHOW_DESCRIPTION_FIELD, False)

    panel = EditPanel(_DummyDBManager())

    assert panel.description_label.isHidden() is True
    assert panel.description_edit.isHidden() is True

    panel.set_description_field_visible(True)
    assert panel.description_label.isHidden() is False
    assert panel.description_edit.isHidden() is False

    panel.set_description_field_visible(False)
    assert panel.description_label.isHidden() is True
    assert panel.description_edit.isHidden() is True


def test_keywords_height_change_keeps_edit_panel_rows_stable(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.SHOW_DESCRIPTION_FIELD, True)

    panel = EditPanel(_DummyDBManager())
    panel.resize(420, 700)
    panel.show()
    qapp.processEvents()

    keywords_edit_index = panel.layout.indexOf(panel.keywords_edit)
    keyword_row, _, _, _ = panel.layout.getItemPosition(keywords_edit_index)
    keyword_label_item = panel.layout.itemAtPosition(keyword_row, 0)
    assert keyword_label_item is not None
    keyword_label = keyword_label_item.widget()
    assert keyword_label is not None
    container = panel.layout.parentWidget()
    assert container is not None

    def snapshot() -> dict[str, int]:
        return {
            "title_y": panel.title_edit.mapTo(container, QPoint(0, 0)).y(),
            "description_y": panel.description_edit.mapTo(container, QPoint(0, 0)).y(),
            "lat_y": panel.lat_edit.mapTo(container, QPoint(0, 0)).y(),
            "lon_y": panel.lon_edit.mapTo(container, QPoint(0, 0)).y(),
            "keywords_y": panel.keywords_edit.mapTo(container, QPoint(0, 0)).y(),
            "keywords_h": panel.keywords_edit.height(),
            "keyword_tree_y": panel.keyword_tree_btn.mapTo(container, QPoint(0, 0)).y(),
            "time_y": panel.time_edit.mapTo(container, QPoint(0, 0)).y(),
            "keyword_label_y": keyword_label.mapTo(container, QPoint(0, 0)).y(),
            "keyword_label_h": keyword_label.height(),
        }

    panel.keywords_edit.set_value("")
    qapp.processEvents()
    base = snapshot()

    long_keywords = ", ".join(
        [
            "alpha",
            "beta",
            "gamma",
            "delta",
            "epsilon",
            "zeta",
            "eta",
            "theta",
            "iota",
            "kappa",
            "lambda",
            "mu",
            "nu",
            "xi",
            "omicron",
            "pi",
            "rho",
            "sigma",
            "tau",
            "upsilon",
            "phi",
            "chi",
            "psi",
            "omega",
        ]
    )

    panel.keywords_edit.set_value(long_keywords)
    qapp.processEvents()
    long_pass1 = snapshot()
    qapp.processEvents()
    long_pass2 = snapshot()
    assert long_pass1 == long_pass2
    long_state = long_pass2

    panel.keywords_edit.set_value("a")
    qapp.processEvents()
    short_pass1 = snapshot()
    qapp.processEvents()
    short_pass2 = snapshot()
    assert short_pass1 == short_pass2
    short_state = short_pass2

    assert long_state["keywords_h"] > base["keywords_h"]
    assert short_state["keywords_h"] == base["keywords_h"]

    assert long_state["keywords_y"] == base["keywords_y"]
    assert short_state["keywords_y"] == base["keywords_y"]

    keyword_height_delta = long_state["keywords_h"] - base["keywords_h"]
    assert keyword_height_delta > 0

    for key in (
        "time_y",
        "title_y",
        "description_y",
        "keyword_tree_y",
        "lat_y",
        "lon_y",
    ):
        if base[key] < base["keywords_y"]:
            assert long_state[key] == base[key]
            assert short_state[key] == base[key]
            continue

        assert base[key] > base["keywords_y"]
        assert long_state[key] - base[key] == keyword_height_delta
        assert short_state[key] == base[key]

    assert long_state["keyword_label_y"] == base["keyword_label_y"]
    assert short_state["keyword_label_y"] == base["keyword_label_y"]
    assert long_state["keyword_label_h"] == base["keyword_label_h"]
    assert short_state["keyword_label_h"] == base["keyword_label_h"]


def test_selection_pending_summary_disables_editors_then_clears_on_update(qapp):
    init_qsettings_store(dyn=True)

    panel = EditPanel(_StubDBManager())
    panel.show_selection_pending(1234)

    assert panel.reading_label.isHidden() is False
    assert panel.reading_label.text() == "1234 photos selected (updating...)"
    assert panel.title_edit.isEnabled() is False
    assert panel.keywords_edit.isEnabled() is False

    item = ImageItem(
        path="/tmp/a.jpg",
        name="a.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.TITLE: "Test"},
    )
    panel.update_for_selection([item])

    assert panel.reading_label.isHidden() is True
    assert panel.title_edit.isEnabled() is True
    assert panel.keywords_edit.isEnabled() is True


def test_non_text_protection_read_only_toggle(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.SHOW_DESCRIPTION_FIELD, True)
    set_user_setting(UserSettingKey.PROTECT_NON_TEXT_METADATA, True)

    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/protected.jpg",
        name="protected.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.TITLE: "Test"},
    )
    panel.update_for_selection([item])

    assert panel.title_edit.isReadOnly() is False
    assert panel.description_edit.isReadOnly() is False
    assert panel.keywords_edit.isReadOnly() is False
    assert panel.time_edit.isReadOnly() is True
    assert panel.lat_edit.isReadOnly() is True
    assert panel.lon_edit.isReadOnly() is True
    assert panel.time_edit.toolTip() == "Protected field. Change in Settings Panel"
    assert panel.lat_edit.toolTip() == "Protected field. Change in Settings Panel"
    assert panel.lon_edit.toolTip() == "Protected field. Change in Settings Panel"
    assert panel.title_edit.toolTip() == ""
    assert panel.description_edit.toolTip() == ""
    assert panel.keywords_edit.toolTip() == ""
    assert panel.keyword_tree_btn.isEnabled() is True

    panel.set_non_text_metadata_protection(False)

    assert panel.title_edit.isReadOnly() is False
    assert panel.description_edit.isReadOnly() is False
    assert panel.keywords_edit.isReadOnly() is False
    assert panel.time_edit.isReadOnly() is False
    assert panel.lat_edit.isReadOnly() is False
    assert panel.lon_edit.isReadOnly() is False
    assert panel.time_edit.toolTip() == ""
    assert panel.lat_edit.toolTip() == ""
    assert panel.lon_edit.toolTip() == ""
    assert panel.keyword_tree_btn.isEnabled() is True


def test_non_text_protection_preserves_multiple_values_on_focus(qapp):
    """Protected non-text fields must keep <Multiple Values> text when clicked."""
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.PROTECT_NON_TEXT_METADATA, True)

    panel = EditPanel(_StubDBManager())
    item1 = ImageItem(
        path="/tmp/multi-a.jpg",
        name="multi-a.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.TITLE: "A",
            DBFields.LATITUDE: "1.0",
            DBFields.LONGITUDE: "2.0",
            DBFields.TIME_TAKEN: "2020-01-01 00:00:00",
        },
    )
    item2 = ImageItem(
        path="/tmp/multi-b.jpg",
        name="multi-b.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.TITLE: "B",
            DBFields.LATITUDE: "3.0",
            DBFields.LONGITUDE: "4.0",
            DBFields.TIME_TAKEN: "2020-01-02 00:00:00",
        },
    )
    panel.update_for_selection([item1, item2])

    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QFocusEvent

    focus_in = QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason)

    # Simulate clicking on each protected field
    for widget in (panel.lat_edit, panel.lon_edit, panel.time_edit):
        assert widget.isReadOnly() is True
        assert widget.text() == "<Multiple Values>"
        widget.focusInEvent(focus_in)
        assert widget.text() == "<Multiple Values>"


def test_non_text_protection_blocks_gui_save_for_locked_fields(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.PROTECT_NON_TEXT_METADATA, True)

    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/save-guard.jpg",
        name="save-guard.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.TITLE: "Before"},
    )
    panel.update_for_selection([item])

    saved_fields: list[str] = []
    emitted: list[str] = []
    monkeypatch.setattr(
        panel,
        "_save_field_for_item",
        lambda _item, field_name, _value: saved_fields.append(field_name),
    )
    panel.metadata_saved.connect(emitted.append)

    panel.lat_edit.set_value(48.8566)
    panel._on_field_saved(DBFields.LATITUDE)

    assert saved_fields == []
    assert emitted == []

    panel.title_edit.set_value("After")
    panel._on_field_saved(DBFields.TITLE)

    assert saved_fields == [DBFields.TITLE]
    assert emitted == [DBFields.TITLE]


def test_title_refresh_with_same_saved_value_preserves_cursor_position(qapp):
    init_qsettings_store(dyn=True)

    panel = EditPanel(_StubDBManager())
    panel.show()
    item = ImageItem(
        path="/tmp/cursor-title.jpg",
        name="cursor-title.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.TITLE: "Before"},
    )
    panel.update_for_selection([item])
    qapp.processEvents()

    panel.title_edit.setFocus()
    panel.title_edit.setText("Edited title")
    panel.title_edit.setCursorPosition(3)

    item.db_metadata[DBFields.TITLE] = "Edited title"
    panel.update_for_selection([item])

    assert panel.title_edit.text() == "Edited title"
    assert panel.title_edit.cursorPosition() == 3
    assert panel.title_edit._original_value == "Edited title"


def test_description_refresh_with_same_saved_value_preserves_cursor_position(qapp):
    init_qsettings_store(dyn=True)

    panel = EditPanel(_StubDBManager())
    panel.show()
    item = ImageItem(
        path="/tmp/cursor-description.jpg",
        name="cursor-description.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.DESCRIPTION: "Before"},
    )
    panel.update_for_selection([item])
    qapp.processEvents()

    panel.description_edit.setFocus()
    panel.description_edit.setPlainText("Edited description")
    cursor = panel.description_edit.textCursor()
    cursor.setPosition(4)
    panel.description_edit.setTextCursor(cursor)

    item.db_metadata[DBFields.DESCRIPTION] = "Edited description"
    panel.update_for_selection([item])

    assert panel.description_edit.toPlainText() == "Edited description"
    assert panel.description_edit.textCursor().position() == 4
    assert panel.description_edit._original_value == "Edited description"


def test_map_button_hidden_when_no_options_are_configured(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.MAP_LINKS, [])

    panel = EditPanel(_StubDBManager())

    assert panel.map_btn.isHidden() is True


def test_map_button_state_follows_selection_and_coordinate_validity(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.MAP_LINKS,
        [
            MapLinkOption(
                name="Google Maps",
                url_template=(
                    "https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                ),
            )
        ],
    )

    panel = EditPanel(_StubDBManager())
    assert panel.map_btn.isHidden() is False
    assert panel.map_btn.isEnabled() is False

    item = ImageItem(
        path="/tmp/map.jpg",
        name="map.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.LATITUDE: "48.8566",
            DBFields.LONGITUDE: "2.3522",
        },
    )
    panel.update_for_selection([item])
    assert panel.map_btn.isEnabled() is True

    panel.lon_edit.setText("")
    assert panel.map_btn.isEnabled() is False

    panel.lon_edit.setText("invalid")
    assert panel.map_btn.isEnabled() is False

    panel.lon_edit.setText("2.3522")
    assert panel.map_btn.isEnabled() is True

    panel.show_selection_pending(2)
    assert panel.map_btn.isEnabled() is False

    item2 = ImageItem(
        path="/tmp/map-2.jpg",
        name="map-2.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.LATITUDE: "50.0000",
            DBFields.LONGITUDE: "10.0000",
        },
    )
    panel.update_for_selection([item, item2])
    assert panel.lat_edit.text() == MULTIPLE_VALUES
    assert panel.lon_edit.text() == MULTIPLE_VALUES
    assert panel.map_btn.isEnabled() is False


def test_map_button_sits_below_longitude_and_keeps_fields_aligned(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.MAP_LINKS,
        [
            MapLinkOption(
                name="Google Maps",
                url_template=(
                    "https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                ),
            )
        ],
    )

    panel = EditPanel(_StubDBManager())
    panel.resize(420, 700)
    item = ImageItem(
        path="/tmp/map-layout.jpg",
        name="map-layout.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.LATITUDE: "48.8566",
            DBFields.LONGITUDE: "2.3522",
        },
    )
    panel.update_for_selection([item])
    panel.show()
    qapp.processEvents()

    container = panel.layout.parentWidget()
    assert container is not None

    keywords_pos = panel.keywords_edit.mapTo(container, QPoint(0, 0))
    keyword_btn_pos = panel.keyword_tree_btn.mapTo(container, QPoint(0, 0))
    lat_pos = panel.lat_edit.mapTo(container, QPoint(0, 0))
    lon_pos = panel.lon_edit.mapTo(container, QPoint(0, 0))
    map_btn_pos = panel.map_btn.mapTo(container, QPoint(0, 0))

    assert panel.map_btn.isVisible() is True
    assert keyword_btn_pos.x() == lon_pos.x()
    assert lat_pos.x() == lon_pos.x()
    assert map_btn_pos.x() == lon_pos.x()
    assert panel.lat_edit.width() == panel.lon_edit.width()
    assert panel.lat_edit.height() == panel.lat_edit.sizeHint().height()
    assert panel.lon_edit.height() == panel.lon_edit.sizeHint().height()
    assert panel.keyword_tree_btn.height() == panel.keyword_tree_btn.sizeHint().height()
    assert panel.map_btn.height() == panel.map_btn.sizeHint().height()
    assert (
        keyword_btn_pos.y() - (keywords_pos.y() + panel.keywords_edit.height())
        == panel.layout.spacing()
    )
    assert (
        lat_pos.y() - (keyword_btn_pos.y() + panel.keyword_tree_btn.height())
        == panel.layout.spacing()
    )
    assert (
        lon_pos.y() - (lat_pos.y() + panel.lat_edit.height())
        == panel.layout.spacing()
    )
    assert (
        map_btn_pos.y() - (lon_pos.y() + panel.lon_edit.height())
        == panel.layout.spacing()
    )


def test_map_button_opens_single_option_directly(monkeypatch, qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.MAP_LINKS,
        [
            MapLinkOption(
                name="OpenStreetMap",
                url_template="https://www.openstreetmap.org/#map=15/{lat}/{lon}",
            )
        ],
    )

    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/map.jpg",
        name="map.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.LATITUDE: "48.8566",
            DBFields.LONGITUDE: "2.3522",
        },
    )
    panel.update_for_selection([item])

    opened_urls: list[str] = []
    monkeypatch.setattr(
        "piqopiqo.panels.edit_panel.webbrowser.open_new_tab",
        lambda url: opened_urls.append(url) or True,
    )

    panel._on_open_map()

    assert opened_urls == ["https://www.openstreetmap.org/#map=15/48.8566/2.3522"]


def test_map_button_builds_menu_for_multiple_options(monkeypatch, qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.MAP_LINKS,
        [
            MapLinkOption(
                name="Google Maps",
                url_template=(
                    "https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                ),
            ),
            MapLinkOption(
                name="OpenStreetMap",
                url_template="https://www.openstreetmap.org/#map=15/{lat}/{lon}",
            ),
        ],
    )

    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/map.jpg",
        name="map.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.LATITUDE: "48.8566",
            DBFields.LONGITUDE: "2.3522",
        },
    )
    panel.update_for_selection([item])

    opened_urls: list[str] = []
    monkeypatch.setattr(
        "piqopiqo.panels.edit_panel.webbrowser.open_new_tab",
        lambda url: opened_urls.append(url) or True,
    )

    panel._on_open_map()

    assert panel._map_menu is not None
    assert [action.text() for action in panel._map_menu.actions()] == [
        "Google Maps",
        "OpenStreetMap",
    ]

    panel._map_menu.actions()[1].trigger()

    assert opened_urls == ["https://www.openstreetmap.org/#map=15/48.8566/2.3522"]
