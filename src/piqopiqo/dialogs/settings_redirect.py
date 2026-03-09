"""Shared settings-redirect dialogs for missing configuration."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def prompt_open_settings_for_missing_setting(
    parent,
    *,
    title: str,
    text: str,
    icon: QMessageBox.Icon = QMessageBox.Icon.Warning,
) -> bool:
    dialog_parent = parent if isinstance(parent, QWidget) else None
    dialog = QMessageBox(dialog_parent)
    dialog.setIcon(icon)
    dialog.setWindowTitle(title)
    dialog.setText(text)
    go_to_settings_btn = dialog.addButton(
        "Go to settings",
        QMessageBox.ButtonRole.AcceptRole,
    )
    dialog.addButton(QMessageBox.StandardButton.Cancel)
    dialog.exec()
    return dialog.clickedButton() == go_to_settings_btn
