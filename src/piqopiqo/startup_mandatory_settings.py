"""Startup-time validation flow for mandatory user settings."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QDialog, QWidget

from .dialogs.mandatory_settings_dialog import MandatorySettingsDialog
from .ssf.settings_state import (
    MandatorySettingInputKind,
    PendingMandatorySetting,
    evaluate_pending_mandatory_settings,
    set_user_setting,
    validate_mandatory_setting_value,
)


def ensure_mandatory_settings_configured(parent: QWidget | None = None) -> bool:
    pending = evaluate_pending_mandatory_settings()
    error_message: str | None = None

    while pending:
        dialog = MandatorySettingsDialog(
            pending,
            error_message=error_message,
            parent=parent,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False

        submitted = dialog.values()
        errors: list[str] = []
        for setting in pending:
            error = _validate_and_persist_pending_setting(
                setting,
                submitted.get(setting.spec.key, ""),
            )
            if error:
                errors.append(error)

        pending = evaluate_pending_mandatory_settings()
        if pending:
            error_message = _format_error_message(errors, pending)

    return True


def _validate_and_persist_pending_setting(
    pending_setting: PendingMandatorySetting,
    entered_value: str,
) -> str | None:
    spec = pending_setting.spec
    value = str(entered_value or "").strip()

    if (
        spec.input_kind == MandatorySettingInputKind.DIRECTORY
        and spec.can_create
        and value
        and not os.path.isdir(value)
    ):
        try:
            os.makedirs(value, exist_ok=True)
        except OSError as exc:
            return f"{spec.label}: cannot create directory ({exc})."

    if validate_mandatory_setting_value(spec, value):
        set_user_setting(spec.key, value)
        return None

    if not value:
        return f"{spec.label}: value is required."
    return f"{spec.label}: invalid value."


def _format_error_message(
    errors: list[str],
    pending: list[PendingMandatorySetting],
) -> str:
    if errors:
        details = "\n".join(f"- {line}" for line in errors)
        return f"Some required settings are still invalid.\n{details}"

    details = "\n".join(f"- {item.spec.label}" for item in pending)
    return f"Some required settings are still invalid.\n{details}"
