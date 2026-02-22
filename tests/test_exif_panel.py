"""Tests for EXIF panel display formatting and row composition."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.model import ExifField, ImageItem
from piqopiqo.panels.exif_panel import ExifPanel, format_exif_display_value
from piqopiqo.settings_state import (
    UserSettingKey,
    init_qsettings_store,
    set_user_setting,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _init_dyn_settings(monkeypatch, *, exif_auto_format: bool = True) -> None:
    monkeypatch.setenv("PIQO_EXIF_AUTO_FORMAT", "true" if exif_auto_format else "false")
    init_qsettings_store(dyn=True)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.008", "1/125 s"),
        ("0.0078125", "1/128 s"),
        ("2", "2 s"),
        ("1.3", "1.3 s"),
        ("abc", "abc"),
    ],
)
def test_shutter_speed_display_formatter(value: str, expected: str):
    field = ExifField("Composite:ShutterSpeed", format="shutter_speed")
    assert format_exif_display_value(field, value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("50", "50 mm"),
        ("35.0", "35 mm"),
        ("35.56", "35.6 mm"),
        ("abc", "abc"),
    ],
)
def test_focal_length_display_formatter(value: str, expected: str):
    field = ExifField("EXIF:FocalLength", format="focal_mm")
    assert format_exif_display_value(field, value) == expected


def test_exif_panel_uses_formatters_in_display(qapp, monkeypatch):
    _init_dyn_settings(monkeypatch, exif_auto_format=True)
    panel = ExifPanel()

    item = ImageItem(path="/tmp/a.jpg", name="a.jpg", created="2025-01-01")
    item.exif_data = {
        "EXIF:FocalLength": "35.56",
        "EXIF:FocalLengthIn35mmFormat": "50",
        "Composite:ShutterSpeed": "0.008",
        "EXIF:FNumber": "4",
        "EXIF:ISO": "200",
        "File:FileName": "a.jpg",
    }

    panel.update_exif([item])

    keys = [label.toolTip() for label in panel.field_labels]
    values_by_key = {
        key: panel.value_labels[i]._full_text  # type: ignore[attr-defined]
        for i, key in enumerate(keys)
    }

    assert values_by_key["EXIF:FocalLength"] == "35.6 mm"
    assert values_by_key["EXIF:FocalLengthIn35mmFormat"] == "50 mm"
    assert values_by_key["Composite:ShutterSpeed"] == "1/125 s"


def test_exif_panel_custom_fields_are_appended_and_deduped(qapp, monkeypatch):
    _init_dyn_settings(monkeypatch, exif_auto_format=True)
    set_user_setting(
        UserSettingKey.CUSTOM_EXIF_FIELDS,
        ["EXIF:ISO", "File:FileSize", "EXIF:LensModel", "File:FileSize"],
    )

    panel = ExifPanel()

    keys = [label.toolTip() for label in panel.field_labels]
    assert keys == [
        "EXIF:FocalLength",
        "EXIF:FocalLengthIn35mmFormat",
        "Composite:ShutterSpeed",
        "EXIF:FNumber",
        "EXIF:ISO",
        "File:FileName",
        "File:FileSize",
        "EXIF:LensModel",
    ]

    labels_by_key = {
        label.toolTip(): label._full_text  # type: ignore[attr-defined]
        for label in panel.field_labels
    }
    assert labels_by_key["File:FileSize"] == "File Size"
    assert labels_by_key["EXIF:LensModel"] == "Lens Model"


def test_exif_panel_custom_field_labels_can_skip_auto_format(qapp, monkeypatch):
    _init_dyn_settings(monkeypatch, exif_auto_format=False)
    set_user_setting(UserSettingKey.CUSTOM_EXIF_FIELDS, ["File:FileSize"])

    panel = ExifPanel()

    labels_by_key = {
        label.toolTip(): label._full_text  # type: ignore[attr-defined]
        for label in panel.field_labels
    }
    assert labels_by_key["File:FileSize"] == "File:FileSize"
