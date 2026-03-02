"""Startup dialog for mandatory settings missing/invalid values."""

from __future__ import annotations

import html
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.ssf.settings_state import (
    MandatorySettingInputKind,
    PendingMandatorySetting,
    UserSettingKey,
)


class MandatorySettingsDialog(QDialog):
    def __init__(
        self,
        pending_settings: list[PendingMandatorySetting],
        *,
        error_message: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Required Settings")
        self.resize(760, 360)

        self._pending_settings = list(pending_settings)
        self._line_edits: dict[UserSettingKey, QLineEdit] = {}
        self._create_notes: dict[UserSettingKey, QLabel] = {}

        self._build_ui(error_message=error_message)

    def values(self) -> dict[UserSettingKey, str]:
        return {
            key: line_edit.text().strip() for key, line_edit in self._line_edits.items()
        }

    def _build_ui(self, *, error_message: str | None) -> None:
        root = QVBoxLayout(self)

        intro = QLabel(
            (
                "PiqoPiqo cannot start yet. Please confirm required settings used for "
                "cache/metadata storage and exiftool execution."
            ),
            self,
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self._error_label = QLabel(self)
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #b00020;")
        if error_message:
            self._error_label.setText(error_message)
        else:
            self._error_label.hide()
        root.addWidget(self._error_label)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        for pending in self._pending_settings:
            row_widget = self._build_setting_row(pending)
            form.addRow(f"{pending.spec.label}:", row_widget)

        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_setting_row(self, pending: PendingMandatorySetting) -> QWidget:
        row = QWidget(self)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        input_row = QWidget(row)
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)

        line_edit = QLineEdit(input_row)
        initial = pending.current_value
        if pending.is_empty and pending.auto_value:
            initial = pending.auto_value
        line_edit.setText(initial)
        input_layout.addWidget(line_edit, 1)
        self._line_edits[pending.spec.key] = line_edit

        if pending.spec.input_kind in (
            MandatorySettingInputKind.DIRECTORY,
            MandatorySettingInputKind.EXECUTABLE_PATH,
        ):
            browse_btn = QPushButton("Browse", input_row)
            browse_btn.clicked.connect(
                lambda _checked=False, key=pending.spec.key: self._browse_for_setting(
                    key
                )
            )
            input_layout.addWidget(browse_btn)

        layout.addWidget(input_row)
        self._add_auto_value_hint(layout, pending, line_edit)

        if (
            pending.spec.input_kind == MandatorySettingInputKind.DIRECTORY
            and pending.spec.can_create
        ):
            create_note = QLabel(row)
            create_note.setWordWrap(True)
            self._create_notes[pending.spec.key] = create_note
            line_edit.textChanged.connect(
                lambda _text, key=pending.spec.key: self._update_create_note_label(key)
            )
            layout.addWidget(create_note)
            self._update_create_note_label(pending.spec.key)

        return row

    def _add_auto_value_hint(
        self,
        layout: QVBoxLayout,
        pending: PendingMandatorySetting,
        line_edit: QLineEdit,
    ) -> None:
        if pending.auto_value:
            escaped_auto = html.escape(pending.auto_value)
            if pending.is_empty:
                auto_label = QLabel("Auto value")
                auto_label.setStyleSheet("color: red;")
                auto_label.setWordWrap(True)
                layout.addWidget(auto_label)
                return

            hint_row = QWidget(self)
            hint_layout = QHBoxLayout(hint_row)
            hint_layout.setContentsMargins(0, 0, 0, 0)
            hint_layout.setSpacing(8)

            auto_label = QLabel(f"Suggested auto value: <b>{escaped_auto}</b>")
            auto_label.setWordWrap(True)
            hint_layout.addWidget(auto_label, 1)

            set_auto_btn = QPushButton("Set to auto", hint_row)
            set_auto_btn.clicked.connect(
                lambda _checked=False, value=pending.auto_value: line_edit.setText(
                    value
                )
            )
            hint_layout.addWidget(set_auto_btn)
            layout.addWidget(hint_row)
            return

        auto_label = QLabel("Auto value: not available")
        auto_label.setWordWrap(True)
        layout.addWidget(auto_label)

    def _browse_for_setting(self, key: UserSettingKey) -> None:
        pending = next(item for item in self._pending_settings if item.spec.key == key)
        line_edit = self._line_edits[key]
        current = line_edit.text().strip()
        start_dir = self._resolve_start_dir(current)

        if pending.spec.input_kind == MandatorySettingInputKind.DIRECTORY:
            value = QFileDialog.getExistingDirectory(
                self,
                f"Select {pending.spec.label}",
                start_dir,
            )
            if value:
                line_edit.setText(value)
            return

        if pending.spec.input_kind == MandatorySettingInputKind.EXECUTABLE_PATH:
            value, _ = QFileDialog.getOpenFileName(
                self,
                f"Select {pending.spec.label}",
                start_dir,
            )
            if value:
                line_edit.setText(value)

    def _resolve_start_dir(self, value: str) -> str:
        if not value:
            return str(Path.home())

        expanded = os.path.expanduser(value)
        if os.path.isdir(expanded):
            return expanded

        parent = os.path.dirname(expanded)
        if parent:
            return parent

        return str(Path.home())

    def _update_create_note_label(self, key: UserSettingKey) -> None:
        note = self._create_notes.get(key)
        line_edit = self._line_edits.get(key)
        if note is None or line_edit is None:
            return

        path = line_edit.text().strip()
        if not path:
            note.setText("This directory will be created on save if missing.")
            return

        escaped_path = html.escape(path)
        note.setText(
            f"This directory will be created on save if missing: <u>{escaped_path}</u>"
        )
