"""Behavioral tests for settings dialog save modes."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

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


def test_autosave_mode_commits_on_field_update(qapp, monkeypatch):
    monkeypatch.setenv("PIQO_SETTINGS_PANEL_SAVE_MODE", "autosave")
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog()
    editor = dialog._editors[UserSettingKey.EXTERNAL_VIEWER]
    editor.set_value("ViewerX")
    dialog._autosave_field(UserSettingKey.EXTERNAL_VIEWER)

    assert get_user_setting(UserSettingKey.EXTERNAL_VIEWER) == "ViewerX"
    assert UserSettingKey.EXTERNAL_VIEWER in dialog.changed_keys
