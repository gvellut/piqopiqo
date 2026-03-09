"""Tests for copy-from-SD dialog helpers and progress UI."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QMessageBox
import pytest

from piqopiqo.ssf.settings_state import UserSettingKey
from piqopiqo.tools.copy_sd import (
    CopySdProgressDialog,
    PhotoVolume,
    _build_no_images_message,
    launch_copy_sd,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_no_images_message_since_last_with_previous_date(monkeypatch):
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd._get_since_last_copied_date_label",
        lambda _volume: "2026-02-01",
    )

    msg = _build_no_images_message("since:last", PhotoVolume("CARD", "/Volumes/CARD"))

    assert msg == "No new photo found since last copied date 2026-02-01."


def test_no_images_message_since_last_without_previous_date(monkeypatch):
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd._get_since_last_copied_date_label",
        lambda _volume: None,
    )

    msg = _build_no_images_message("since:last", PhotoVolume("CARD", "/Volumes/CARD"))

    assert msg == "No photo found and no previous copied date exists for this volume."


def test_no_images_message_generic_spec():
    msg = _build_no_images_message("20260201", PhotoVolume("CARD", "/Volumes/CARD"))
    assert msg == "No image found for the selected date(s)."


def test_copy_progress_counter_label_updates(qapp):  # noqa: ARG001
    dialog = CopySdProgressDialog(
        volume=PhotoVolume("CARD", "/Volumes/CARD"),
        dates=[],
        output_folder_base=[],
        should_eject=False,
    )

    dialog._on_plan_ready(5)
    assert dialog.progress_text_label.text() == "0/5"

    dialog._on_progress(2, 5)
    assert dialog.progress_text_label.text() == "2/5"

    dialog._on_finished(5, 5, False, 0)
    assert dialog.progress_text_label.text() == "5/5"


def test_launch_copy_sd_missing_base_folder_opens_settings(monkeypatch):
    parent = SimpleNamespace(open_settings_calls=[])

    def _open_settings_for_key(key: UserSettingKey) -> None:
        parent.open_settings_calls.append(key)

    parent.open_settings_for_key = _open_settings_for_key

    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.get_sd_volume",
        lambda: PhotoVolume("CARD", "/Volumes/CARD"),
    )
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.get_user_setting",
        lambda key: [] if key == UserSettingKey.SDCARD_NAMES else "",
    )

    prompt_calls: list[tuple[str, str, QMessageBox.Icon]] = []
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.prompt_open_settings_for_missing_setting",
        lambda _parent, *, title, text, icon=QMessageBox.Icon.Warning: (
            prompt_calls.append((title, text, icon)) or True
        ),
    )

    launch_copy_sd(parent)

    assert prompt_calls == [
        (
            "Copy from SD",
            "BASE_EXTERNAL_FOLDER is not configured.",
            QMessageBox.Icon.Critical,
        )
    ]
    assert parent.open_settings_calls == [UserSettingKey.COPY_SD_BASE_EXTERNAL_FOLDER]
