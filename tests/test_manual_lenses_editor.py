"""Tests for manual lens settings editor widgets."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialog
import pytest

from piqopiqo.model import ManualLensPreset
from piqopiqo.settings_panel import manual_lenses_editor as mle


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_manual_lens_preset_dialog_requires_selection_and_valid_numbers(qapp):  # noqa: ARG001
    dialog = mle._ManualLensPresetDialog(
        title="Add Lens Preset",
        existing_models={"Samyang 12mm f/2.0 NCS CS"},
    )

    assert dialog._ok_btn.isEnabled() is False

    dialog.lens_make_edit.setText("Sigma")
    dialog.lens_model_edit.setText("Sigma 18-35mm F1.8")
    dialog.focal_length_edit.setText("24,5")
    dialog.focal_length_35mm_edit.setText("36")
    assert dialog._ok_btn.isEnabled() is True

    dialog.lens_model_edit.setText("Samyang 12mm f/2.0 NCS CS")
    assert dialog._ok_btn.isEnabled() is False

    dialog.lens_model_edit.setText("Sigma 18-35mm F1.8")
    dialog.focal_length_edit.setText("not-a-number")
    assert dialog._ok_btn.isEnabled() is False


def test_manual_lenses_editor_add_edit_delete(monkeypatch, qapp):  # noqa: ARG001
    editor = mle.ManualLensesEditor()

    responses = [
        (
            QDialog.DialogCode.Accepted,
            ManualLensPreset(
                lens_make="Samyang",
                lens_model="Samyang 12mm f/2.0 NCS CS",
                focal_length="12",
                focal_length_35mm="18",
            ),
        ),
        (
            QDialog.DialogCode.Accepted,
            ManualLensPreset(
                lens_make="Sigma",
                lens_model="Sigma 18-35mm F1.8",
                focal_length="24.5",
                focal_length_35mm="36",
            ),
        ),
    ]

    class _DialogStub:
        def __init__(self, **_kwargs):
            result, value = responses.pop(0)
            self._result = result
            self._value = value

        def exec(self):
            return self._result

        def get_value(self):
            return self._value

    monkeypatch.setattr(mle, "_ManualLensPresetDialog", _DialogStub)

    editor._on_add()
    assert [preset.lens_model for preset in editor.get_value()] == [
        "Samyang 12mm f/2.0 NCS CS"
    ]

    editor._list.setCurrentRow(0)
    editor._on_edit()
    assert [preset.lens_model for preset in editor.get_value()] == [
        "Sigma 18-35mm F1.8"
    ]

    editor._on_delete()
    assert editor.get_value() == []
