"""Tests for QSettings-backed settings/state store."""

from __future__ import annotations

from pathlib import Path
import uuid

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.color_management import ScreenColorProfileMode
from piqopiqo.model import ExifField, ManualLensPreset, StatusLabel
from piqopiqo.shortcuts import Shortcut
import piqopiqo.ssf.settings_state as settings_state
from piqopiqo.ssf.settings_state import (
    MandatorySettingInputKind,
    RuntimeSettingKey,
    SettingsPanelSaveMode,
    StateKey,
    UserSettingKey,
    _deserialize_exif_fields,
    _resolve_default_cache_base_dir,
    _resolve_default_exiftool_path,
    evaluate_pending_mandatory_settings,
    get_cache_base_dir_candidate,
    get_effective_exif_panel_fields,
    get_mandatory_setting_spec,
    get_mandatory_setting_specs,
    get_runtime_setting,
    get_state_value,
    get_user_setting,
    init_qsettings_store,
    set_state_value,
    set_user_setting,
    validate_mandatory_setting_value,
)


@pytest.fixture
def qcore_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def isolated_settings(qcore_app, monkeypatch):
    app_name = f"piqopiqo-test-{uuid.uuid4().hex}"
    qcore_app.setOrganizationName("PiqoPiqoTests")
    qcore_app.setOrganizationDomain("tests.local")
    qcore_app.setApplicationName(app_name)

    # Clear any stale env that can override values.
    for env_name in (
        "PIQO_CACHE_BASE_DIR",
        "PIQO_EXIFTOOL_PATH",
        "PIQO_NUM_COLUMNS",
        "PIQO_GRID_NUM_COLUMNS_MIN",
        "PIQO_GRID_NUM_COLUMNS_MAX",
        "PIQO_STATUS_BAR_SIDE_PADDING",
        "PIQO_SETTINGS_PANEL_SAVE_MODE",
        "PIQO_FONT_SIZE",
        "PIQO_GPX_IGNORE_OFFSET",
        "PIQO_GPX_TIMEZONE",
        "PIQO_TIME_SHIFT_UNKNOWN_FOLDER_IGNORE",
        "PIQO_TIMESHIFT_CACHE_NUM",
        "PIQO_FLICKR_UPLOAD_MAX_WORKERS",
        "PIQO_PROTECT_NON_TEXT_METADATA",
        "PIQO_FORCE_SRGB",
        "PIQO_SCREEN_COLOR_PROFILE",
        "PIQO_COLOR_MANAGE_EMBEDDED_THUMBNAILS",
        "PIQO_COLOR_MANAGE_HQ_THUMBNAILS",
        "PIQO_PILLOW_FOR_EXTRACT_IMAGE_COLOR_PROFILE",
    ):
        monkeypatch.delenv(env_name, raising=False)

    init_qsettings_store(dyn=False)
    settings = QSettings()
    settings.clear()
    settings.sync()
    return settings


def test_typed_state_roundtrip(isolated_settings):
    set_state_value(StateKey.COPY_SD_EJECT, False)

    value = get_state_value(StateKey.COPY_SD_EJECT)
    assert value is False
    assert isinstance(value, bool)


def test_sort_order_state_default_and_roundtrip(isolated_settings):
    assert get_state_value(StateKey.SORT_ORDER) == "FILE_NAME"

    set_state_value(StateKey.SORT_ORDER, "TIME_TAKEN")
    assert get_state_value(StateKey.SORT_ORDER) == "TIME_TAKEN"

    set_state_value(StateKey.SORT_ORDER, "FILE_NAME_BY_FOLDER")
    assert get_state_value(StateKey.SORT_ORDER) == "FILE_NAME_BY_FOLDER"


def test_gpx_timeshift_state_defaults(isolated_settings):
    assert get_state_value(StateKey.LAST_TIMESHIFT) is None
    assert get_state_value(StateKey.LAST_TIMESHIFT_BY_FOLDERS) == {}
    assert get_state_value(StateKey.LAST_GPX_FOLDER) is None


def test_gpx_timeshift_state_ordered_json_roundtrip(isolated_settings):
    value = {
        "abc/def": "1s",
        "poi/def": "2s",
    }
    set_state_value(StateKey.LAST_TIMESHIFT_BY_FOLDERS, value)

    roundtrip = get_state_value(StateKey.LAST_TIMESHIFT_BY_FOLDERS)
    assert roundtrip == value
    assert list(roundtrip.items()) == list(value.items())


def test_json_roundtrip_for_complex_user_settings(isolated_settings):
    labels = [
        StatusLabel("Approved", "#00FF00", 1),
        StatusLabel("Rejected", "#FF0000", 2),
    ]
    shortcuts = {
        Shortcut.ZOOM_IN: "=",
        Shortcut.ZOOM_OUT: "-",
        Shortcut.SELECT_ALL: "ctrl+a",
    }

    set_user_setting(UserSettingKey.STATUS_LABELS, labels)
    set_user_setting(UserSettingKey.SHORTCUTS, shortcuts)
    set_user_setting(UserSettingKey.CUSTOM_EXIF_FIELDS, ["File:FileSize", "EXIF:ISO"])

    roundtrip_labels = get_user_setting(UserSettingKey.STATUS_LABELS)
    roundtrip_shortcuts = get_user_setting(UserSettingKey.SHORTCUTS)
    roundtrip_custom_fields = get_user_setting(UserSettingKey.CUSTOM_EXIF_FIELDS)

    assert roundtrip_labels == labels
    assert roundtrip_shortcuts == shortcuts
    assert roundtrip_custom_fields == ["File:FileSize", "EXIF:ISO"]


def test_shortcuts_defaults_include_filter_shortcuts(isolated_settings):
    shortcuts = get_user_setting(UserSettingKey.SHORTCUTS)

    assert shortcuts[Shortcut.FILTER_LABEL_1] == "Alt+1"
    assert shortcuts[Shortcut.FILTER_LABEL_2] == "Alt+2"
    assert shortcuts[Shortcut.FILTER_LABEL_3] == "Alt+3"
    assert shortcuts[Shortcut.FILTER_LABEL_4] == "Alt+4"
    assert shortcuts[Shortcut.FILTER_LABEL_5] == "Alt+5"
    assert shortcuts[Shortcut.FILTER_LABEL_6] == "Alt+6"
    assert shortcuts[Shortcut.FILTER_LABEL_7] == "Alt+7"
    assert shortcuts[Shortcut.FILTER_LABEL_8] == "Alt+8"
    assert shortcuts[Shortcut.FILTER_LABEL_9] == "Alt+9"
    assert shortcuts[Shortcut.FILTER_LABEL_NONE] == "Alt+`"
    assert shortcuts[Shortcut.FILTER_FOLDER_ALL] == "Alt+0"
    assert shortcuts[Shortcut.FILTER_FOLDER_NEXT] == "Alt+="
    assert shortcuts[Shortcut.FILTER_FOLDER_PREV] == "Alt+-"
    assert shortcuts[Shortcut.FILTER_CLEAR_ALL] == "Alt+\\"
    assert shortcuts[Shortcut.FILTER_FOCUS_SEARCH] == "Ctrl+F"
    assert shortcuts[Shortcut.TOGGLE_RIGHT_SIDEBAR] == "Ctrl+]"


def test_manual_lenses_roundtrip(isolated_settings):
    presets = [
        ManualLensPreset(
            lens_make="Samyang",
            lens_model="Samyang 12mm f/2.0 NCS CS",
            focal_length="12",
            focal_length_35mm="18",
        ),
        ManualLensPreset(
            lens_make="Sigma",
            lens_model="Sigma 18-35mm F1.8 DC HSM | Art",
            focal_length="24,5",
            focal_length_35mm="36",
        ),
    ]

    set_user_setting(UserSettingKey.MANUAL_LENSES, presets)

    assert get_user_setting(UserSettingKey.MANUAL_LENSES) == presets


def test_env_override_takes_priority_over_persisted_values(
    isolated_settings, monkeypatch
):
    set_user_setting(UserSettingKey.NUM_COLUMNS, 12)
    assert get_user_setting(UserSettingKey.NUM_COLUMNS) == 12

    monkeypatch.setenv("PIQO_NUM_COLUMNS", "7")
    assert get_user_setting(UserSettingKey.NUM_COLUMNS) == 7


def test_grid_column_runtime_bounds_and_status_bar_padding_defaults_and_env_override(
    isolated_settings, monkeypatch
):
    assert get_runtime_setting(RuntimeSettingKey.GRID_NUM_COLUMNS_MIN) == 3
    assert get_runtime_setting(RuntimeSettingKey.GRID_NUM_COLUMNS_MAX) == 10
    assert get_runtime_setting(RuntimeSettingKey.STATUS_BAR_SIDE_PADDING) == 10

    monkeypatch.setenv("PIQO_GRID_NUM_COLUMNS_MIN", "4")
    monkeypatch.setenv("PIQO_GRID_NUM_COLUMNS_MAX", "12")
    monkeypatch.setenv("PIQO_STATUS_BAR_SIDE_PADDING", "16")
    init_qsettings_store(dyn=False)

    assert get_runtime_setting(RuntimeSettingKey.GRID_NUM_COLUMNS_MIN) == 4
    assert get_runtime_setting(RuntimeSettingKey.GRID_NUM_COLUMNS_MAX) == 12
    assert get_runtime_setting(RuntimeSettingKey.STATUS_BAR_SIDE_PADDING) == 16


def test_gpx_settings_defaults_and_env_override(isolated_settings, monkeypatch):
    assert get_user_setting(UserSettingKey.GPX_TIMEZONE) == ""
    assert get_user_setting(UserSettingKey.GPX_IGNORE_OFFSET) is False
    assert get_user_setting(UserSettingKey.GPX_KML_FOLDER) == ""
    assert get_user_setting(UserSettingKey.TIME_SHIFT_UNKNOWN_FOLDER_IGNORE) is True
    assert get_runtime_setting(RuntimeSettingKey.TIMESHIFT_CACHE_NUM) == 10

    monkeypatch.setenv("PIQO_GPX_IGNORE_OFFSET", "true")
    monkeypatch.setenv("PIQO_GPX_TIMEZONE", "Europe/Paris")
    monkeypatch.setenv("PIQO_TIME_SHIFT_UNKNOWN_FOLDER_IGNORE", "false")
    monkeypatch.setenv("PIQO_TIMESHIFT_CACHE_NUM", "3")
    init_qsettings_store(dyn=False)
    assert get_user_setting(UserSettingKey.GPX_IGNORE_OFFSET) is True
    assert get_user_setting(UserSettingKey.GPX_TIMEZONE) == "Europe/Paris"
    assert get_user_setting(UserSettingKey.TIME_SHIFT_UNKNOWN_FOLDER_IGNORE) is False
    assert get_runtime_setting(RuntimeSettingKey.TIMESHIFT_CACHE_NUM) == 3


def test_flickr_settings_defaults_and_roundtrip(isolated_settings):
    assert get_user_setting(UserSettingKey.FLICKR_API_KEY) == ""
    assert get_user_setting(UserSettingKey.FLICKR_API_SECRET) == ""

    set_user_setting(UserSettingKey.FLICKR_API_KEY, "key123")
    set_user_setting(UserSettingKey.FLICKR_API_SECRET, "secret456")

    assert get_user_setting(UserSettingKey.FLICKR_API_KEY) == "key123"
    assert get_user_setting(UserSettingKey.FLICKR_API_SECRET) == "secret456"


def test_flickr_runtime_workers_env_override(isolated_settings, monkeypatch):
    monkeypatch.setenv("PIQO_FLICKR_UPLOAD_MAX_WORKERS", "7")
    init_qsettings_store(dyn=False)
    assert get_runtime_setting(RuntimeSettingKey.FLICKR_UPLOAD_MAX_WORKERS) == 7


def test_filter_in_fullscreen_default_and_roundtrip(isolated_settings):
    assert get_user_setting(UserSettingKey.FILTER_IN_FULLSCREEN) is False

    set_user_setting(UserSettingKey.FILTER_IN_FULLSCREEN, True)
    assert get_user_setting(UserSettingKey.FILTER_IN_FULLSCREEN) is True


def test_show_description_field_default_and_roundtrip(isolated_settings):
    assert get_user_setting(UserSettingKey.SHOW_DESCRIPTION_FIELD) is True

    set_user_setting(UserSettingKey.SHOW_DESCRIPTION_FIELD, False)
    assert get_user_setting(UserSettingKey.SHOW_DESCRIPTION_FIELD) is False

    set_user_setting(UserSettingKey.SHOW_DESCRIPTION_FIELD, True)
    assert get_user_setting(UserSettingKey.SHOW_DESCRIPTION_FIELD) is True


def test_protect_non_text_metadata_default_and_roundtrip(isolated_settings):
    assert get_user_setting(UserSettingKey.PROTECT_NON_TEXT_METADATA) is True

    set_user_setting(UserSettingKey.PROTECT_NON_TEXT_METADATA, False)
    assert get_user_setting(UserSettingKey.PROTECT_NON_TEXT_METADATA) is False

    set_user_setting(UserSettingKey.PROTECT_NON_TEXT_METADATA, True)
    assert get_user_setting(UserSettingKey.PROTECT_NON_TEXT_METADATA) is True


def test_color_profile_user_settings_defaults_and_roundtrip(isolated_settings):
    assert get_user_setting(UserSettingKey.FORCE_SRGB) is False
    assert (
        get_user_setting(UserSettingKey.SCREEN_COLOR_PROFILE)
        == ScreenColorProfileMode.FROM_MAIN_SCREEN
    )

    set_user_setting(UserSettingKey.FORCE_SRGB, True)
    set_user_setting(
        UserSettingKey.SCREEN_COLOR_PROFILE,
        ScreenColorProfileMode.DISPLAY_P3,
    )

    assert get_user_setting(UserSettingKey.FORCE_SRGB) is True
    assert (
        get_user_setting(UserSettingKey.SCREEN_COLOR_PROFILE)
        == ScreenColorProfileMode.DISPLAY_P3
    )


def test_screen_color_profile_env_override(isolated_settings, monkeypatch):
    monkeypatch.setenv("PIQO_SCREEN_COLOR_PROFILE", "NO_CONVERSION")
    init_qsettings_store(dyn=False)

    assert (
        get_user_setting(UserSettingKey.SCREEN_COLOR_PROFILE)
        == ScreenColorProfileMode.NO_CONVERSION
    )


def test_color_management_runtime_settings_defaults_and_env_override(
    isolated_settings, monkeypatch
):
    assert (
        get_runtime_setting(RuntimeSettingKey.COLOR_MANAGE_EMBEDDED_THUMBNAILS) is True
    )
    assert get_runtime_setting(RuntimeSettingKey.COLOR_MANAGE_HQ_THUMBNAILS) is True
    assert (
        get_runtime_setting(RuntimeSettingKey.PILLOW_FOR_EXTRACT_IMAGE_COLOR_PROFILE)
        is False
    )

    monkeypatch.setenv("PIQO_COLOR_MANAGE_EMBEDDED_THUMBNAILS", "false")
    monkeypatch.setenv("PIQO_COLOR_MANAGE_HQ_THUMBNAILS", "0")
    monkeypatch.setenv("PIQO_PILLOW_FOR_EXTRACT_IMAGE_COLOR_PROFILE", "true")
    init_qsettings_store(dyn=False)

    assert (
        get_runtime_setting(RuntimeSettingKey.COLOR_MANAGE_EMBEDDED_THUMBNAILS) is False
    )
    assert get_runtime_setting(RuntimeSettingKey.COLOR_MANAGE_HQ_THUMBNAILS) is False
    assert (
        get_runtime_setting(RuntimeSettingKey.PILLOW_FOR_EXTRACT_IMAGE_COLOR_PROFILE)
        is True
    )


def test_runtime_settings_are_memory_only(isolated_settings, monkeypatch):
    monkeypatch.setenv("PIQO_FONT_SIZE", "19")

    init_qsettings_store(dyn=False)

    assert get_runtime_setting(RuntimeSettingKey.FONT_SIZE) == 19
    assert (
        get_runtime_setting(RuntimeSettingKey.SETTINGS_PANEL_SAVE_MODE)
        == SettingsPanelSaveMode.SAVE_CANCEL
    )

    settings = QSettings()
    persisted_keys = settings.allKeys()
    assert not any("fontSize" in key for key in persisted_keys)


def test_dyn_mode_is_memory_only(qcore_app):
    qcore_app.setOrganizationName("PiqoPiqoTests")
    qcore_app.setOrganizationDomain("tests.local")
    qcore_app.setApplicationName(f"piqopiqo-test-dyn-{uuid.uuid4().hex}")

    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.EXTERNAL_EDITOR, "EditorA")

    assert get_user_setting(UserSettingKey.EXTERNAL_EDITOR) == "EditorA"

    # New dyn store must not retain prior in-memory values.
    init_qsettings_store(dyn=True)
    assert get_user_setting(UserSettingKey.EXTERNAL_EDITOR) == ""

    # Nothing persisted to QSettings.
    settings = QSettings()
    assert not settings.contains("Settings/externalEditor")


def test_deserialize_exif_fields_accepts_optional_format():
    fields = _deserialize_exif_fields(
        [
            {
                "key": "Composite:ShutterSpeed",
                "label": "Shutter",
                "format": "shutter_speed",
            },
            {"key": "EXIF:ISO"},
            {"key": "EXIF:FNumber", "format": ""},
        ]
    )

    assert fields == [
        ExifField("Composite:ShutterSpeed", "Shutter", "shutter_speed"),
        ExifField("EXIF:ISO", None, None),
        ExifField("EXIF:FNumber", None, None),
    ]


def test_effective_exif_panel_fields_merge_custom_fields_dedupes(isolated_settings):
    set_user_setting(
        UserSettingKey.CUSTOM_EXIF_FIELDS,
        [" ", "EXIF:ISO", "File:FileSize", "EXIF:LensModel", "File:FileSize"],
    )

    fields = get_effective_exif_panel_fields()
    keys = [field.key for field in fields]

    assert keys[:6] == [
        "EXIF:FocalLength",
        "EXIF:FocalLengthIn35mmFormat",
        "Composite:ShutterSpeed",
        "EXIF:FNumber",
        "EXIF:ISO",
        "File:FileName",
    ]
    assert keys[6:] == ["File:FileSize", "EXIF:LensModel"]
    assert all(field.format is None for field in fields[6:])


def test_mandatory_setting_registry_contains_cache_and_exiftool():
    specs = get_mandatory_setting_specs()
    assert [spec.key for spec in specs] == [
        UserSettingKey.CACHE_BASE_DIR,
        UserSettingKey.EXIFTOOL_PATH,
    ]
    assert specs[0].input_kind == MandatorySettingInputKind.DIRECTORY
    assert specs[1].input_kind == MandatorySettingInputKind.EXECUTABLE_PATH


def test_validate_mandatory_exiftool_path_uses_executable_check(monkeypatch):
    spec = get_mandatory_setting_spec(UserSettingKey.EXIFTOOL_PATH)
    assert spec is not None

    monkeypatch.setattr(
        settings_state.os,
        "access",
        lambda path, mode: path == "/opt/tools/exiftool",
    )

    assert validate_mandatory_setting_value(spec, "/opt/tools/exiftool") is True
    assert validate_mandatory_setting_value(spec, "/opt/tools/missing") is False
    assert validate_mandatory_setting_value(spec, "") is False


def test_resolve_default_exiftool_path_prefers_homebrew_on_macos(monkeypatch):
    monkeypatch.setattr(settings_state.sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(
        settings_state.shutil,
        "which",
        lambda _name: "/usr/local/bin/exiftool",
    )
    monkeypatch.setattr(
        settings_state,
        "_validate_executable_path",
        lambda path: path in {"/opt/homebrew/bin/exiftool", "/usr/local/bin/exiftool"},
    )

    assert _resolve_default_exiftool_path() == "/opt/homebrew/bin/exiftool"


def test_resolve_default_exiftool_path_falls_back_to_which(monkeypatch):
    monkeypatch.setattr(settings_state.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(
        settings_state.shutil,
        "which",
        lambda _name: "/usr/bin/exiftool",
    )
    monkeypatch.setattr(
        settings_state,
        "_validate_executable_path",
        lambda path: path == "/usr/bin/exiftool",
    )

    assert _resolve_default_exiftool_path() == str(Path("/usr/bin/exiftool").resolve())


def test_resolve_default_cache_base_dir_matches_candidate():
    assert _resolve_default_cache_base_dir() == str(get_cache_base_dir_candidate())


def test_evaluate_pending_mandatory_settings_reports_missing_cache_auto_value(
    isolated_settings,
):
    set_user_setting(UserSettingKey.CACHE_BASE_DIR, "")
    set_user_setting(UserSettingKey.EXIFTOOL_PATH, "")

    pending = evaluate_pending_mandatory_settings()
    by_key = {item.spec.key: item for item in pending}

    assert UserSettingKey.CACHE_BASE_DIR in by_key
    assert UserSettingKey.EXIFTOOL_PATH in by_key
    assert by_key[UserSettingKey.CACHE_BASE_DIR].is_empty is True
    assert by_key[UserSettingKey.CACHE_BASE_DIR].auto_value == str(
        get_cache_base_dir_candidate()
    )
    assert by_key[UserSettingKey.EXIFTOOL_PATH].is_empty is True


def test_evaluate_pending_mandatory_settings_uses_env_override(
    isolated_settings,
    monkeypatch,
    tmp_path,
):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    exiftool_path = tmp_path / "exiftool"
    exiftool_path.write_text("#!/bin/sh\n")
    exiftool_path.chmod(0o755)

    set_user_setting(UserSettingKey.CACHE_BASE_DIR, str(cache_dir))
    set_user_setting(UserSettingKey.EXIFTOOL_PATH, "/definitely/invalid")
    monkeypatch.setenv("PIQO_EXIFTOOL_PATH", str(exiftool_path))

    pending_keys = {item.spec.key for item in evaluate_pending_mandatory_settings()}
    assert UserSettingKey.EXIFTOOL_PATH not in pending_keys
