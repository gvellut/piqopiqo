"""Tests for QSettings-backed settings/state store."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.model import StatusLabel
from piqopiqo.settings_state import (
    RuntimeSettingKey,
    SettingsPanelSaveMode,
    StateKey,
    UserSettingKey,
    get_runtime_setting,
    get_state_value,
    get_user_setting,
    init_qsettings_store,
    set_state_value,
    set_user_setting,
)
from piqopiqo.shortcuts import Shortcut


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
        "PIQO_NUM_COLUMNS",
        "PIQO_SETTINGS_PANEL_SAVE_MODE",
        "PIQO_FONT_SIZE",
        "PIQO_GPX_IGNORE_OFFSET",
        "PIQO_GPX_TIMEZONE",
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


def test_env_override_takes_priority_over_persisted_values(
    isolated_settings, monkeypatch
):
    set_user_setting(UserSettingKey.NUM_COLUMNS, 12)
    assert get_user_setting(UserSettingKey.NUM_COLUMNS) == 12

    monkeypatch.setenv("PIQO_NUM_COLUMNS", "7")
    assert get_user_setting(UserSettingKey.NUM_COLUMNS) == 7


def test_gpx_settings_defaults_and_env_override(isolated_settings, monkeypatch):
    assert get_user_setting(UserSettingKey.GPX_TIMEZONE) == ""
    assert get_user_setting(UserSettingKey.GPX_IGNORE_OFFSET) is False
    assert get_user_setting(UserSettingKey.GPX_KML_FOLDER) == ""

    monkeypatch.setenv("PIQO_GPX_IGNORE_OFFSET", "true")
    monkeypatch.setenv("PIQO_GPX_TIMEZONE", "Europe/Paris")
    assert get_user_setting(UserSettingKey.GPX_IGNORE_OFFSET) is True
    assert get_user_setting(UserSettingKey.GPX_TIMEZONE) == "Europe/Paris"


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
