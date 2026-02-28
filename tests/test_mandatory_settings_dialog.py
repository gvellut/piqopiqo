"""Tests for startup mandatory settings dialog behavior."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QPushButton
import pytest

from piqopiqo.dialogs.mandatory_settings_dialog import MandatorySettingsDialog
from piqopiqo.ssf.settings_state import (
    PendingMandatorySetting,
    UserSettingKey,
    get_mandatory_setting_spec,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _pending(
    key: UserSettingKey,
    *,
    current_value: str,
    auto_value: str | None,
    is_empty: bool,
) -> PendingMandatorySetting:
    spec = get_mandatory_setting_spec(key)
    assert spec is not None
    return PendingMandatorySetting(
        spec=spec,
        current_value=current_value,
        auto_value=auto_value,
        is_empty=is_empty,
    )


def test_empty_value_prefills_auto_value_and_shows_auto_label(qapp):
    pending = _pending(
        UserSettingKey.CACHE_BASE_DIR,
        current_value="",
        auto_value="/tmp/piqopiqo-cache",
        is_empty=True,
    )
    dialog = MandatorySettingsDialog([pending])

    line_edit = dialog._line_edits[UserSettingKey.CACHE_BASE_DIR]
    assert line_edit.text() == "/tmp/piqopiqo-cache"
    assert any("Auto value:" in lbl.text() for lbl in dialog.findChildren(QLabel))


def test_invalid_non_empty_value_keeps_user_value_and_set_to_auto(qapp):
    pending = _pending(
        UserSettingKey.EXIFTOOL_PATH,
        current_value="/custom/invalid/exiftool",
        auto_value="/opt/homebrew/bin/exiftool",
        is_empty=False,
    )
    dialog = MandatorySettingsDialog([pending])

    line_edit = dialog._line_edits[UserSettingKey.EXIFTOOL_PATH]
    assert line_edit.text() == "/custom/invalid/exiftool"

    set_auto_btn = next(
        btn for btn in dialog.findChildren(QPushButton) if btn.text() == "Set to auto"
    )
    set_auto_btn.click()
    assert line_edit.text() == "/opt/homebrew/bin/exiftool"


def test_creatable_directory_row_shows_creation_note(qapp):
    pending = _pending(
        UserSettingKey.CACHE_BASE_DIR,
        current_value="/tmp/future-cache",
        auto_value="/tmp/future-cache",
        is_empty=False,
    )
    dialog = MandatorySettingsDialog([pending])
    labels = [lbl.text() for lbl in dialog.findChildren(QLabel)]
    assert any("created on save if missing" in text for text in labels)
    assert any("/tmp/future-cache" in text for text in labels)


def test_save_cancel_buttons_and_values_roundtrip(qapp):
    pending = _pending(
        UserSettingKey.EXIFTOOL_PATH,
        current_value="",
        auto_value="/usr/bin/exiftool",
        is_empty=True,
    )

    save_dialog = MandatorySettingsDialog([pending])
    save_dialog._line_edits[UserSettingKey.EXIFTOOL_PATH].setText("  /custom/exiftool  ")
    assert save_dialog.values()[UserSettingKey.EXIFTOOL_PATH] == "/custom/exiftool"
    button_box = save_dialog.findChild(QDialogButtonBox)
    assert button_box is not None
    save_btn = button_box.button(QDialogButtonBox.StandardButton.Save)
    assert save_btn is not None
    save_btn.click()
    assert save_dialog.result() == QDialog.DialogCode.Accepted

    cancel_dialog = MandatorySettingsDialog([pending])
    cancel_box = cancel_dialog.findChild(QDialogButtonBox)
    assert cancel_box is not None
    cancel_btn = cancel_box.button(QDialogButtonBox.StandardButton.Cancel)
    assert cancel_btn is not None
    cancel_btn.click()
    assert cancel_dialog.result() == QDialog.DialogCode.Rejected
