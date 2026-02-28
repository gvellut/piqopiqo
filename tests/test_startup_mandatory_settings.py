"""Tests for startup mandatory settings controller loop."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog

import piqopiqo.startup_mandatory_settings as startup_mandatory_settings
from piqopiqo.ssf.settings_state import (
    MandatorySettingInputKind,
    MandatorySettingSpec,
    PendingMandatorySetting,
    UserSettingKey,
)


def _pending(
    key: UserSettingKey,
    *,
    label: str,
) -> PendingMandatorySetting:
    spec = MandatorySettingSpec(
        key=key,
        label=label,
        input_kind=MandatorySettingInputKind.TEXT,
        can_create=False,
        validator=lambda value: bool(value.strip()),
    )
    return PendingMandatorySetting(
        spec=spec,
        current_value="",
        auto_value=None,
        is_empty=True,
    )


def _build_fake_dialog_class(scripted_responses: list[dict]) -> type:
    class _FakeDialog:
        calls: list[dict] = []

        def __init__(self, pending, *, error_message=None, parent=None):
            index = len(self.calls)
            self._script = scripted_responses[index]
            self.calls.append(
                {
                    "pending_keys": [item.spec.key for item in pending],
                    "error_message": error_message,
                    "parent": parent,
                }
            )

        def exec(self):
            return self._script["code"]

        def values(self):
            return self._script.get("values", {})

    return _FakeDialog


def test_ensure_mandatory_settings_returns_true_without_dialog(monkeypatch):
    monkeypatch.setattr(
        startup_mandatory_settings,
        "evaluate_pending_mandatory_settings",
        lambda: [],
    )

    class _NeverCalledDialog:
        def __init__(self, *args, **kwargs):
            raise AssertionError("dialog should not be instantiated")

    monkeypatch.setattr(
        startup_mandatory_settings,
        "MandatorySettingsDialog",
        _NeverCalledDialog,
    )

    assert startup_mandatory_settings.ensure_mandatory_settings_configured() is True


def test_ensure_mandatory_settings_persists_valid_and_retries_invalid(monkeypatch):
    cache_pending = _pending(UserSettingKey.CACHE_BASE_DIR, label="Cache")
    exif_pending = _pending(UserSettingKey.EXIFTOOL_PATH, label="Exiftool")
    pending_sequence = [[cache_pending, exif_pending], [exif_pending], []]
    fake_dialog = _build_fake_dialog_class(
        [
            {
                "code": QDialog.DialogCode.Accepted,
                "values": {
                    UserSettingKey.CACHE_BASE_DIR: "/cache/ok",
                    UserSettingKey.EXIFTOOL_PATH: "/bad/exiftool",
                },
            },
            {
                "code": QDialog.DialogCode.Accepted,
                "values": {
                    UserSettingKey.EXIFTOOL_PATH: "/opt/tools/exiftool",
                },
            },
        ]
    )
    saved: list[tuple[UserSettingKey, str]] = []

    monkeypatch.setattr(
        startup_mandatory_settings,
        "MandatorySettingsDialog",
        fake_dialog,
    )
    monkeypatch.setattr(
        startup_mandatory_settings,
        "evaluate_pending_mandatory_settings",
        lambda: pending_sequence.pop(0),
    )

    def _validate(setting: PendingMandatorySetting, value: str) -> str | None:
        if setting.spec.key == UserSettingKey.CACHE_BASE_DIR and value == "/cache/ok":
            saved.append((setting.spec.key, value))
            return None
        if (
            setting.spec.key == UserSettingKey.EXIFTOOL_PATH
            and value == "/opt/tools/exiftool"
        ):
            saved.append((setting.spec.key, value))
            return None
        return "invalid"

    monkeypatch.setattr(
        startup_mandatory_settings,
        "_validate_and_persist_pending_setting",
        _validate,
    )

    assert startup_mandatory_settings.ensure_mandatory_settings_configured() is True
    assert fake_dialog.calls[0]["pending_keys"] == [
        UserSettingKey.CACHE_BASE_DIR,
        UserSettingKey.EXIFTOOL_PATH,
    ]
    assert fake_dialog.calls[1]["pending_keys"] == [UserSettingKey.EXIFTOOL_PATH]
    assert saved == [
        (UserSettingKey.CACHE_BASE_DIR, "/cache/ok"),
        (UserSettingKey.EXIFTOOL_PATH, "/opt/tools/exiftool"),
    ]


def test_ensure_mandatory_settings_returns_false_on_cancel(monkeypatch):
    cache_pending = _pending(UserSettingKey.CACHE_BASE_DIR, label="Cache")
    fake_dialog = _build_fake_dialog_class(
        [
            {
                "code": QDialog.DialogCode.Rejected,
            },
        ]
    )

    monkeypatch.setattr(
        startup_mandatory_settings,
        "MandatorySettingsDialog",
        fake_dialog,
    )
    monkeypatch.setattr(
        startup_mandatory_settings,
        "evaluate_pending_mandatory_settings",
        lambda: [cache_pending],
    )

    assert startup_mandatory_settings.ensure_mandatory_settings_configured() is False


def test_ensure_mandatory_settings_reopens_with_error_message(monkeypatch):
    cache_pending = _pending(UserSettingKey.CACHE_BASE_DIR, label="Cache")
    pending_sequence = [[cache_pending], [cache_pending], []]
    fake_dialog = _build_fake_dialog_class(
        [
            {
                "code": QDialog.DialogCode.Accepted,
                "values": {UserSettingKey.CACHE_BASE_DIR: ""},
            },
            {
                "code": QDialog.DialogCode.Accepted,
                "values": {UserSettingKey.CACHE_BASE_DIR: "/cache/ok"},
            },
        ]
    )

    monkeypatch.setattr(
        startup_mandatory_settings,
        "MandatorySettingsDialog",
        fake_dialog,
    )
    monkeypatch.setattr(
        startup_mandatory_settings,
        "evaluate_pending_mandatory_settings",
        lambda: pending_sequence.pop(0),
    )

    attempts = {"count": 0}

    def _validate(_setting: PendingMandatorySetting, value: str) -> str | None:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return "invalid"
        if value == "/cache/ok":
            return None
        return "invalid"

    monkeypatch.setattr(
        startup_mandatory_settings,
        "_validate_and_persist_pending_setting",
        _validate,
    )

    assert startup_mandatory_settings.ensure_mandatory_settings_configured() is True
    assert fake_dialog.calls[1]["error_message"] is not None
    assert "still invalid" in fake_dialog.calls[1]["error_message"]
