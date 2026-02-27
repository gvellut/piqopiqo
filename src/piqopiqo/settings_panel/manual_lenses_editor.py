"""Custom editor widget for manual lens presets."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.model import ManualLensPreset

_INVALID_STYLE = "QLineEdit { border: 2px solid red; }"


def _is_decimal_text(value: str) -> bool:
    text = value.strip().replace(",", ".")
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


class _ManualLensPresetDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        existing_models: set[str],
        initial: ManualLensPreset | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(520)

        self._existing_models = {model.casefold() for model in existing_models}
        self._initial_model = (
            str(initial.lens_model).strip().casefold() if initial is not None else None
        )

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.lens_make_edit = QLineEdit(self)
        self.lens_make_edit.setPlaceholderText("Samyang")
        form.addRow("Lens make", self.lens_make_edit)

        self.lens_model_edit = QLineEdit(self)
        self.lens_model_edit.setPlaceholderText("Samyang 12mm f/2.0 NCS CS")
        form.addRow("Lens model", self.lens_model_edit)

        self.focal_length_edit = QLineEdit(self)
        self.focal_length_edit.setPlaceholderText("12")
        form.addRow("Focal length", self.focal_length_edit)

        self.focal_length_35mm_edit = QLineEdit(self)
        self.focal_length_35mm_edit.setPlaceholderText("18")
        form.addRow("Focal length (35mm)", self.focal_length_35mm_edit)

        self._error_label = QLabel(self)
        self._error_label.setStyleSheet("color: red;")
        self._error_label.hide()

        layout.addLayout(form)
        layout.addWidget(self._error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for edit in (
            self.lens_make_edit,
            self.lens_model_edit,
            self.focal_length_edit,
            self.focal_length_35mm_edit,
        ):
            edit.textChanged.connect(self._update_validity)

        if initial is not None:
            self.lens_make_edit.setText(initial.lens_make)
            self.lens_model_edit.setText(initial.lens_model)
            self.focal_length_edit.setText(initial.focal_length)
            self.focal_length_35mm_edit.setText(initial.focal_length_35mm)

        self._update_validity()

    def _set_line_validity(self, line_edit: QLineEdit, *, valid: bool) -> None:
        line_edit.setStyleSheet("" if valid else _INVALID_STYLE)

    def _update_validity(self) -> None:
        lens_make = self.lens_make_edit.text().strip()
        lens_model = self.lens_model_edit.text().strip()
        focal_length = self.focal_length_edit.text().strip()
        focal_length_35mm = self.focal_length_35mm_edit.text().strip()

        lens_make_valid = bool(lens_make)
        lens_model_valid = bool(lens_model)
        focal_length_valid = _is_decimal_text(focal_length)
        focal_length_35mm_valid = _is_decimal_text(focal_length_35mm)

        self._set_line_validity(self.lens_make_edit, valid=lens_make_valid)
        self._set_line_validity(self.lens_model_edit, valid=lens_model_valid)
        self._set_line_validity(self.focal_length_edit, valid=focal_length_valid)
        self._set_line_validity(
            self.focal_length_35mm_edit, valid=focal_length_35mm_valid
        )

        lens_model_conflict = False
        if lens_model_valid:
            normalized_model = lens_model.casefold()
            lens_model_conflict = (
                normalized_model in self._existing_models
                and normalized_model != self._initial_model
            )
            if lens_model_conflict:
                self._set_line_validity(self.lens_model_edit, valid=False)

        error_message = ""
        if lens_model_conflict:
            error_message = "Lens model must be unique."
        elif not focal_length_valid or not focal_length_35mm_valid:
            error_message = "Focal lengths must be valid numbers."

        if error_message:
            self._error_label.setText(error_message)
            self._error_label.show()
        else:
            self._error_label.hide()

        is_valid = (
            lens_make_valid
            and lens_model_valid
            and not lens_model_conflict
            and focal_length_valid
            and focal_length_35mm_valid
        )
        self._ok_btn.setEnabled(is_valid)

    def get_value(self) -> ManualLensPreset:
        return ManualLensPreset(
            lens_make=self.lens_make_edit.text().strip(),
            lens_model=self.lens_model_edit.text().strip(),
            focal_length=self.focal_length_edit.text().strip(),
            focal_length_35mm=self.focal_length_35mm_edit.text().strip(),
        )


class ManualLensesEditor(QWidget):
    """Editor for MANUAL_LENSES presets."""

    value_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._presets: list[ManualLensPreset] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._list = QListWidget(self)
        self._list.currentRowChanged.connect(self._update_buttons)
        layout.addWidget(self._list)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)

        self._add_btn = QPushButton("Add", self)
        self._add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._add_btn.clicked.connect(self._on_add)
        buttons.addWidget(self._add_btn)

        self._edit_btn = QPushButton("Edit", self)
        self._edit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._edit_btn.clicked.connect(self._on_edit)
        buttons.addWidget(self._edit_btn)

        self._delete_btn = QPushButton("Delete", self)
        self._delete_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._delete_btn.clicked.connect(self._on_delete)
        buttons.addWidget(self._delete_btn)
        buttons.addStretch(1)

        layout.addLayout(buttons)
        self._update_buttons()

    def _selected_index(self) -> int | None:
        index = self._list.currentRow()
        if index < 0 or index >= len(self._presets):
            return None
        return index

    def _update_buttons(self, *_args) -> None:
        has_selection = self._selected_index() is not None
        self._edit_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)

    def _refresh_list(self) -> None:
        selected_index = self._selected_index()
        self._list.clear()
        for preset in self._presets:
            self._list.addItem(preset.lens_model)
        if selected_index is not None and selected_index < self._list.count():
            self._list.setCurrentRow(selected_index)
        self._update_buttons()

    def _existing_models(self) -> set[str]:
        return {preset.lens_model for preset in self._presets}

    def _on_add(self) -> None:
        dialog = _ManualLensPresetDialog(
            title="Add Lens Preset",
            existing_models=self._existing_models(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._presets.append(dialog.get_value())
        self._refresh_list()
        self._list.setCurrentRow(len(self._presets) - 1)
        self.value_changed.emit()

    def _on_edit(self) -> None:
        index = self._selected_index()
        if index is None:
            return

        current = self._presets[index]
        dialog = _ManualLensPresetDialog(
            title="Edit Lens Preset",
            existing_models=self._existing_models(),
            initial=current,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._presets[index] = dialog.get_value()
        self._refresh_list()
        self._list.setCurrentRow(index)
        self.value_changed.emit()

    def _on_delete(self) -> None:
        index = self._selected_index()
        if index is None:
            return

        del self._presets[index]
        self._refresh_list()
        if self._presets:
            self._list.setCurrentRow(min(index, len(self._presets) - 1))
        self.value_changed.emit()

    def is_valid(self) -> bool:
        seen_models: set[str] = set()
        for preset in self._presets:
            lens_make = str(preset.lens_make).strip()
            lens_model = str(preset.lens_model).strip()
            focal_length = str(preset.focal_length).strip()
            focal_length_35mm = str(preset.focal_length_35mm).strip()
            if not lens_make or not lens_model:
                return False
            if not _is_decimal_text(focal_length) or not _is_decimal_text(
                focal_length_35mm
            ):
                return False
            normalized = lens_model.casefold()
            if normalized in seen_models:
                return False
            seen_models.add(normalized)
        return True

    def set_value(self, value: list[ManualLensPreset] | None) -> None:
        self._presets = []
        for preset in value or []:
            self._presets.append(
                ManualLensPreset(
                    lens_make=str(preset.lens_make).strip(),
                    lens_model=str(preset.lens_model).strip(),
                    focal_length=str(preset.focal_length).strip(),
                    focal_length_35mm=str(preset.focal_length_35mm).strip(),
                )
            )
        self._refresh_list()

    def get_value(self) -> list[ManualLensPreset]:
        return list(self._presets)
