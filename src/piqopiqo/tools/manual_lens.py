"""Set manual lens info for selected or visible photos."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.save_workers import MetadataSaveWorker
from piqopiqo.model import ManualLensPreset
from piqopiqo.settings_state import UserSettingKey, get_user_setting

if TYPE_CHECKING:
    from piqopiqo.main_window import MainWindow

_CLEAR_LENS_INFO_DATA = "__clear_lens_info__"


def _as_manual_lens_preset(value: object) -> ManualLensPreset | None:
    if isinstance(value, ManualLensPreset):
        return ManualLensPreset(
            lens_make=str(value.lens_make).strip(),
            lens_model=str(value.lens_model).strip(),
            focal_length=str(value.focal_length).strip(),
            focal_length_35mm=str(value.focal_length_35mm).strip(),
        )
    if not isinstance(value, dict):
        return None
    return ManualLensPreset(
        lens_make=str(value.get("lens_make", "")).strip(),
        lens_model=str(value.get("lens_model", "")).strip(),
        focal_length=str(value.get("focal_length", "")).strip(),
        focal_length_35mm=str(value.get("focal_length_35mm", "")).strip(),
    )


def _load_manual_lens_presets() -> list[ManualLensPreset]:
    raw = get_user_setting(UserSettingKey.MANUAL_LENSES) or []
    presets: list[ManualLensPreset] = []
    for value in raw:
        preset = _as_manual_lens_preset(value)
        if preset is None:
            continue
        if not preset.lens_model:
            continue
        presets.append(preset)
    return presets


class LensSelectionDialog(QDialog):
    """Dialog for choosing one manual lens preset."""

    def __init__(self, presets: list[ManualLensPreset], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Lens Info")
        self.setModal(True)
        self.setMinimumWidth(520)

        self._presets = presets
        self._selected_preset: ManualLensPreset | None = None
        self._selected_clear = False

        layout = QVBoxLayout(self)

        description = QLabel(
            "Select a lens preset to apply to the target photos.",
            self,
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.combo = QComboBox(self)
        self.combo.addItem("Choose a lens...", None)
        self.combo.addItem("Clear lens info", _CLEAR_LENS_INFO_DATA)
        for preset in self._presets:
            self.combo.addItem(preset.lens_model, preset)
        self.combo.setCurrentIndex(0)
        self.combo.currentIndexChanged.connect(self._on_selection_changed)
        layout.addWidget(self.combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selected_preset(self) -> ManualLensPreset | None:
        return self._selected_preset

    @property
    def selected_clear(self) -> bool:
        return self._selected_clear

    def _on_selection_changed(self, _index: int) -> None:
        selected = self.combo.currentData()
        if isinstance(selected, ManualLensPreset):
            self._selected_preset = selected
            self._selected_clear = False
            self.ok_btn.setEnabled(True)
            return
        if selected == _CLEAR_LENS_INFO_DATA:
            self._selected_preset = None
            self._selected_clear = True
            self.ok_btn.setEnabled(True)
            return
        self._selected_preset = None
        self._selected_clear = False
        self.ok_btn.setEnabled(False)


def _normalize_decimal_text(value: object) -> str:
    return str(value).strip().replace(",", ".")


def _build_set_confirmation_text(preset: ManualLensPreset, image_count: int) -> str:
    focal = _normalize_decimal_text(preset.focal_length)
    focal_35mm = _normalize_decimal_text(preset.focal_length_35mm)
    return (
        "The following values will be set:\n\n"
        f"- Lens maker = {preset.lens_make}\n"
        f"- Lens model = {preset.lens_model}\n"
        f"- Focal length = {focal} mm\n"
        f"- Focal length (35mm) = {focal_35mm} mm\n\n"
        f"Apply to {image_count} image(s)?"
    )


def _build_clear_confirmation_text(image_count: int) -> str:
    return f"The lens information will be cleared.\n\nApply to {image_count} image(s)?"


def _save_manual_lens_for_item(
    window: MainWindow, *, file_path: str, metadata: dict
) -> None:
    db = window.db_manager.get_db_for_image(file_path)
    worker = MetadataSaveWorker(db, file_path, metadata.copy())
    window._label_save_pool.start(worker)


def launch_manual_lens(window: MainWindow) -> None:
    """Launch Set Lens Info workflow."""
    selected_items = window.photo_model.get_selected_photos()
    items = selected_items if selected_items else list(window.images_data)
    if not items:
        QMessageBox.warning(window, "Set Lens Info", "No photos available.")
        return

    presets = _load_manual_lens_presets()
    if not presets:
        QMessageBox.warning(
            window,
            "Set Lens Info",
            "No lens presets found. Add presets in Settings > External/Tools > "
            "Manual Lens.",
        )
        return

    picker = LensSelectionDialog(presets, parent=window)
    if picker.exec() != QDialog.DialogCode.Accepted:
        return

    selected_clear = bool(getattr(picker, "selected_clear", False))
    preset = getattr(picker, "selected_preset", None)
    if not selected_clear and preset is None:
        return

    if selected_clear:
        confirmation_text = _build_clear_confirmation_text(len(items))
    else:
        confirmation_text = _build_set_confirmation_text(preset, len(items))

    confirm = QMessageBox.question(
        window,
        "Set Lens Info",
        confirmation_text,
        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    if confirm != QMessageBox.StandardButton.Ok:
        return

    if not window.db_manager.ensure_items_metadata_ready(items):
        QApplication.beep()
        window.status_bar.showMessage("Reading...", 2000)
        return

    for item in items:
        if item.db_metadata is None:
            continue
        updated = item.db_metadata.copy()
        if selected_clear:
            updated[DBFields.MANUAL_LENS_MAKE] = None
            updated[DBFields.MANUAL_LENS_MODEL] = None
            updated[DBFields.MANUAL_FOCAL_LENGTH] = None
            updated[DBFields.MANUAL_FOCAL_LENGTH_35MM] = None
        else:
            updated[DBFields.MANUAL_LENS_MAKE] = preset.lens_make
            updated[DBFields.MANUAL_LENS_MODEL] = preset.lens_model
            updated[DBFields.MANUAL_FOCAL_LENGTH] = preset.focal_length
            updated[DBFields.MANUAL_FOCAL_LENGTH_35MM] = preset.focal_length_35mm
        item.db_metadata = updated
        _save_manual_lens_for_item(window, file_path=item.path, metadata=updated)

    window.sync_model_after_metadata_update(
        set(DBFields.MANUAL_LENS_FIELDS),
        source="manual_lens",
    )
