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
