"""Shared confirmation behavior for dialogs with discardable input."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from piqopiqo.ssf.settings_state import (
    DialogDiscardConfirmationMode,
    RuntimeSettingKey,
    get_runtime_setting,
)


class UnsavedChangesDialog(QDialog):
    """QDialog that can confirm before changed input is discarded."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._unsaved_state_getter: Callable[[], object] | None = None
        self._initial_unsaved_state: object = None
        self._bypass_discard_confirmation = False

    def _set_unsaved_changes_state(self, getter: Callable[[], object]) -> None:
        self._unsaved_state_getter = getter
        self._reset_unsaved_changes_baseline()

    def _reset_unsaved_changes_baseline(self) -> None:
        if self._unsaved_state_getter is None:
            self._initial_unsaved_state = None
            return
        self._initial_unsaved_state = deepcopy(self._unsaved_state_getter())

    def _has_unsaved_changes(self) -> bool:
        if self._unsaved_state_getter is None:
            return False
        return self._unsaved_state_getter() != self._initial_unsaved_state

    def _escape_would_close(self) -> bool:
        return True

    def _confirm_discard_changes_if_required(
        self,
        *,
        escape: bool = False,
        force: bool = False,
    ) -> bool:
        if self._bypass_discard_confirmation or not self._has_unsaved_changes():
            return True

        mode = get_runtime_setting(RuntimeSettingKey.DIALOG_DISCARD_CONFIRMATION_MODE)
        if (
            not force
            and not escape
            and (mode != DialogDiscardConfirmationMode.EVERY_DISMISSAL)
        ):
            return True

        answer = QMessageBox.question(
            self,
            "Discard changes",
            "This dialog has changed values. Discard them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _reject_without_discard_confirmation(self) -> None:
        previous = self._bypass_discard_confirmation
        self._bypass_discard_confirmation = True
        try:
            super().reject()
        finally:
            self._bypass_discard_confirmation = previous

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._escape_would_close():
            if not self._confirm_discard_changes_if_required(escape=True):
                event.accept()
                return

            previous = self._bypass_discard_confirmation
            self._bypass_discard_confirmation = True
            try:
                super().keyPressEvent(event)
            finally:
                self._bypass_discard_confirmation = previous
            return

        super().keyPressEvent(event)

    def reject(self) -> None:
        if not self._confirm_discard_changes_if_required():
            return
        self._reject_without_discard_confirmation()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._confirm_discard_changes_if_required():
            event.ignore()
            return

        previous = self._bypass_discard_confirmation
        self._bypass_discard_confirmation = True
        try:
            super().closeEvent(event)
        finally:
            self._bypass_discard_confirmation = previous
