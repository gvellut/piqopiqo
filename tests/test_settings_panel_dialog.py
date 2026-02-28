"""Behavioral tests for settings dialog save modes."""

from __future__ import annotations

from copy import replace
import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
import pytest

from piqopiqo.color_management import ScreenColorProfileMode
from piqopiqo.settings_panel.dialog import SettingsDialog
from piqopiqo.ssf import settings_state
from piqopiqo.ssf.settings_state import (
    MandatorySettingInputKind,
    MandatorySettingSpec,
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
    dialog._on_field_changed(UserSettingKey.EXTERNAL_EDITOR)

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


def test_save_shows_inline_auto_hint_for_invalid_mandatory_field(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="Core")
    editor = dialog._editors[UserSettingKey.EXIFTOOL_PATH]
    editor.set_value("/invalid/exiftool")
    dialog._on_field_changed(UserSettingKey.EXIFTOOL_PATH)

    auto_spec = MandatorySettingSpec(
        key=UserSettingKey.EXIFTOOL_PATH,
        label="Exiftool Path",
        input_kind=MandatorySettingInputKind.EXECUTABLE_PATH,
        can_create=False,
        validator=lambda value: value == "/valid/exiftool",
        default_resolver=lambda: "/auto/exiftool",
    )
    monkeypatch.setattr(
        "piqopiqo.settings_panel.dialog.get_mandatory_setting_spec",
        lambda key: auto_spec if key == UserSettingKey.EXIFTOOL_PATH else None,
    )
    monkeypatch.setattr(
        "piqopiqo.settings_panel.dialog.validate_mandatory_setting_value",
        lambda spec, value: spec.validator(str(value).strip()),
    )
    warning_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "piqopiqo.settings_panel.dialog.QMessageBox.warning",
        lambda _parent, title, text: warning_calls.append((title, text)),
    )

    dialog._on_save()

    assert warning_calls
    labels = [label.text() for label in editor.findChildren(QLabel)]
    assert any("Suggested auto value:" in text for text in labels)
    set_auto_btn = next(
        btn for btn in editor.findChildren(QPushButton) if btn.text() == "Set to auto"
    )
    set_auto_btn.click()
    assert editor.get_value() == "/auto/exiftool"


def test_mandatory_hint_clears_when_user_edits_field(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="Core")
    editor = dialog._editors[UserSettingKey.CACHE_BASE_DIR]
    editor.set_value("/invalid/cache")
    dialog._on_field_changed(UserSettingKey.CACHE_BASE_DIR)

    base_spec = settings_state.get_mandatory_setting_spec(UserSettingKey.CACHE_BASE_DIR)
    assert base_spec is not None
    fake_spec = replace(
        base_spec,
        default_resolver=lambda: "/auto/cache",
        validator=lambda value: value == "/valid/cache",
    )
    monkeypatch.setattr(
        "piqopiqo.settings_panel.dialog.get_mandatory_setting_spec",
        lambda key: fake_spec if key == UserSettingKey.CACHE_BASE_DIR else None,
    )
    monkeypatch.setattr(
        "piqopiqo.settings_panel.dialog.validate_mandatory_setting_value",
        lambda spec, value: spec.validator(str(value).strip()),
    )
    monkeypatch.setattr(
        "piqopiqo.settings_panel.dialog.QMessageBox.warning",
        lambda *_args, **_kwargs: None,
    )

    dialog._on_save()
    assert any(
        "Suggested auto value:" in label.text() for label in editor.findChildren(QLabel)
    )

    editor.set_value("/some/edit")
    dialog._on_field_changed(UserSettingKey.CACHE_BASE_DIR)
    assert not any(
        "Suggested auto value:" in label.text() and label.isVisible()
        for label in editor.findChildren(QLabel)
    )
