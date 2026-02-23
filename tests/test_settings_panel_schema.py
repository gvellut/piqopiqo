"""Tests for settings panel descriptors."""

from piqopiqo.settings_panel.schema import SETTINGS_TABS, iter_all_field_specs
from piqopiqo.settings_state import UserSettingKey


def test_every_user_setting_is_present_in_schema():
    schema_keys = {field.key for field in iter_all_field_specs()}
    assert schema_keys == set(UserSettingKey)


def test_schema_field_keys_are_unique():
    fields = iter_all_field_specs()
    keys = [field.key for field in fields]
    assert len(keys) == len(set(keys))


def test_tabs_have_groups_and_groups_have_fields():
    assert SETTINGS_TABS
    for tab in SETTINGS_TABS:
        assert tab.groups
        for group in tab.groups:
            assert group.fields


def test_interface_tab_layout_matches_expected_groups_and_fields():
    interface_tab = next(tab for tab in SETTINGS_TABS if tab.title == "Interface")

    assert [group.title for group in interface_tab.groups] == [
        "Grid",
        "Fullscreen",
        "Metadata Panel",
        "EXIF Panel",
    ]

    assert [field.key for field in interface_tab.groups[0].fields] == [
        UserSettingKey.NUM_COLUMNS
    ]
    assert [field.key for field in interface_tab.groups[1].fields] == [
        UserSettingKey.ON_FULLSCREEN_EXIT_SELECTION_MODE
    ]
    assert [field.key for field in interface_tab.groups[2].fields] == [
        UserSettingKey.SHOW_DESCRIPTION_FIELD
    ]
    assert [field.key for field in interface_tab.groups[3].fields] == [
        UserSettingKey.CUSTOM_EXIF_FIELDS
    ]
