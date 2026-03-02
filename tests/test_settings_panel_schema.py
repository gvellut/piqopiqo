"""Tests for settings panel descriptors."""

from piqopiqo.settings_panel.schema import SETTINGS_TABS, iter_all_field_specs
from piqopiqo.ssf.settings_state import UserSettingKey


def test_every_user_setting_is_present_in_schema():
    schema_keys = {field.key for field in iter_all_field_specs()}
    hidden_keys = {UserSettingKey.NUM_COLUMNS}
    assert schema_keys == (set(UserSettingKey) - hidden_keys)


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
        "Fullscreen",
        "Color",
        "Metadata Panel",
        "EXIF Panel",
    ]

    assert [field.key for field in interface_tab.groups[0].fields] == [
        UserSettingKey.ON_FULLSCREEN_EXIT_SELECTION_MODE
    ]
    assert [field.key for field in interface_tab.groups[1].fields] == [
        UserSettingKey.FORCE_SRGB,
        UserSettingKey.SCREEN_COLOR_PROFILE,
    ]
    assert [field.key for field in interface_tab.groups[2].fields] == [
        UserSettingKey.SHOW_DESCRIPTION_FIELD,
        UserSettingKey.PROTECT_NON_TEXT_METADATA,
    ]
    assert [field.key for field in interface_tab.groups[3].fields] == [
        UserSettingKey.CUSTOM_EXIF_FIELDS
    ]


def test_external_tools_tab_contains_manual_lens_group():
    external_tab = next(tab for tab in SETTINGS_TABS if tab.title == "External/Tools")
    group_by_title = {group.title: group for group in external_tab.groups}
    assert "Manual Lens" in group_by_title
    assert [field.key for field in group_by_title["Manual Lens"].fields] == [
        UserSettingKey.MANUAL_LENSES
    ]


def test_external_tools_tab_flickr_group_contains_required_metadata_toggle():
    external_tab = next(tab for tab in SETTINGS_TABS if tab.title == "External/Tools")
    group_by_title = {group.title: group for group in external_tab.groups}
    assert "Flickr" in group_by_title
    assert [field.key for field in group_by_title["Flickr"].fields] == [
        UserSettingKey.FLICKR_API_KEY,
        UserSettingKey.FLICKR_API_SECRET,
        UserSettingKey.FLICKR_UPLOAD_REQUIRE_TITLE_AND_KEYWORDS,
    ]


def test_labels_and_shortcuts_tabs_layout_matches_expected_groups_and_fields():
    labels_tab = next(tab for tab in SETTINGS_TABS if tab.title == "Labels")
    assert [group.title for group in labels_tab.groups] == ["Status Labels"]
    assert [field.key for field in labels_tab.groups[0].fields] == [
        UserSettingKey.STATUS_LABELS,
        UserSettingKey.FILTER_IN_FULLSCREEN,
    ]

    shortcuts_tab = next(tab for tab in SETTINGS_TABS if tab.title == "Shortcuts")
    assert [group.title for group in shortcuts_tab.groups] == ["Shortcuts"]
    assert [field.key for field in shortcuts_tab.groups[0].fields] == [
        UserSettingKey.SHORTCUTS
    ]
