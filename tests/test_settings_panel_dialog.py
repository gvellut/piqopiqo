"""Behavioral tests for settings dialog save modes."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.color_management import ScreenColorProfileMode
from piqopiqo.settings_panel.dialog import SettingsDialog
from piqopiqo.settings_state import (
    UserSettingKey,
    get_user_setting,
    init_qsettings_store,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    # Ensure QSettings identity exists for the dialog-backed store.
    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-dialog-{uuid.uuid4().hex}")
    return app


def test_save_cancel_mode_tracks_dirty_state(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog()
    editor = dialog._editors[UserSettingKey.EXTERNAL_EDITOR]
    editor.set_value("EditorX")
    dialog._on_field_changed()

    assert dialog._dirty is True


def test_autosave_mode_commits_on_field_update(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("PIQO_SETTINGS_PANEL_SAVE_MODE", "autosave")
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog()
    app_path = tmp_path / "Viewer.app"
    app_path.mkdir()
    editor = dialog._editors[UserSettingKey.EXTERNAL_VIEWER]
    editor.set_value(str(app_path))
    dialog._autosave_field(UserSettingKey.EXTERNAL_VIEWER)

    assert get_user_setting(UserSettingKey.EXTERNAL_VIEWER) == str(app_path)
    assert UserSettingKey.EXTERNAL_VIEWER in dialog.changed_keys


def test_initial_tab_title_selects_requested_tab(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="External/Tools")

    assert dialog._tabs is not None
    current_title = dialog._tabs.tabText(dialog._tabs.currentIndex())
    assert current_title == "External/Tools"


def test_autosave_choice_enum_setting_roundtrip(qapp, monkeypatch):
    monkeypatch.setenv("PIQO_SETTINGS_PANEL_SAVE_MODE", "autosave")
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="Interface")
    editor = dialog._editors[UserSettingKey.SCREEN_COLOR_PROFILE]
    editor.set_value(ScreenColorProfileMode.BT2020)
    dialog._autosave_field(UserSettingKey.SCREEN_COLOR_PROFILE)

    assert (
        get_user_setting(UserSettingKey.SCREEN_COLOR_PROFILE)
        == ScreenColorProfileMode.BT2020
    )
    assert UserSettingKey.SCREEN_COLOR_PROFILE in dialog.changed_keys
