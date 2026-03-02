"""Tests for copy-from-SD dialog helpers and progress UI."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.tools.copy_sd import (
    CopySdProgressDialog,
    PhotoVolume,
    _build_no_images_message,
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
