"""Tests for copy-from-SD dialog helpers and progress UI."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
import pytest

from piqopiqo.ssf.settings_state import StateKey
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
        target_dirs=[],
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


class _FakeState:
    def __init__(self) -> None:
        self.values = {
            StateKey.COPY_SD_NAME_SUFFIX: "",
            StateKey.COPY_SD_DATE_SPEC: "",
            StateKey.COPY_SD_EJECT: False,
        }

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value) -> None:
        self.values[key] = value


class _FakeCheckbox:
    def __init__(self, checked: bool) -> None:
        self._checked = bool(checked)

    def isChecked(self) -> bool:
        return self._checked


def test_launch_copy_sd_notifies_parent_callbacks_with_target_dirs(monkeypatch, tmp_path):
    output_root = tmp_path / "exports"
    output_root.mkdir()
    state = _FakeState()
    volume = PhotoVolume("CARD", "/Volumes/CARD")

    class _FakeInputDialog:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ARG002
            return None

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

        def get_values(self):
            return ("annecy", "20260301")

    class _FakeProgressDialog:
        def __init__(
            self,
            volume,
            dates,
            target_dirs,
            should_eject,
            parent=None,
        ) -> None:
            self.volume = volume
            self.dates = list(dates)
            self.target_dirs = list(target_dirs)
            self.should_eject = should_eject
            self.parent = parent
            self.copied_count = 3
            self.was_cancelled = False
            self.eject_checkbox = _FakeCheckbox(should_eject)

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

    parent = SimpleNamespace()

    def _on_started(target_dirs: list[str]) -> None:
        start_calls.append(list(target_dirs))

    def _on_finished(target_dirs: list[str], copied_count: int) -> None:
        finish_calls.append((list(target_dirs), copied_count))

    start_calls: list[list[str]] = []
    finish_calls: list[tuple[list[str], int]] = []

    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.get_sd_volume",
        lambda: volume,
    )
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.get_user_setting",
        lambda key: [] if key == UserSettingKey.SDCARD_NAMES else str(output_root),
    )
    monkeypatch.setattr("piqopiqo.tools.copy_sd.get_state", lambda: state)
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.CopySdInputDialog",
        _FakeInputDialog,
    )
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd._resolve_dates_with_progress",
        lambda *_args, **_kwargs: [date(2026, 3, 1), date(2026, 3, 2)],
    )
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd._confirm_copy",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.CopySdProgressDialog",
        _FakeProgressDialog,
    )

    launch_copy_sd(
        parent,
        on_bulk_copy_started=_on_started,
        on_bulk_copy_finished=_on_finished,
    )

    expected_target_dirs = [
        str(output_root / "20260301_annecy" / volume.name),
        str(output_root / "20260302_annecy" / volume.name),
    ]
    assert start_calls == [expected_target_dirs]
    assert finish_calls == [(expected_target_dirs, 3)]


def test_launch_copy_sd_notifies_finish_callback_for_partial_cancel(
    monkeypatch, tmp_path
):
    output_root = tmp_path / "exports"
    output_root.mkdir()
    state = _FakeState()
    volume = PhotoVolume("CARD", "/Volumes/CARD")

    class _FakeInputDialog:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ARG002
            return None

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

        def get_values(self):
            return ("trip", "20260303")

    class _FakeProgressDialog:
        def __init__(
            self,
            volume,
            dates,
            target_dirs,
            should_eject,
            parent=None,
        ) -> None:
            self.volume = volume
            self.dates = list(dates)
            self.target_dirs = list(target_dirs)
            self.should_eject = should_eject
            self.parent = parent
            self.copied_count = 2
            self.was_cancelled = True
            self.eject_checkbox = _FakeCheckbox(should_eject)

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

    parent = SimpleNamespace()

    finish_calls: list[tuple[list[str], int]] = []

    def _on_finished(target_dirs: list[str], copied_count: int) -> None:
        finish_calls.append((list(target_dirs), copied_count))

    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.get_sd_volume",
        lambda: volume,
    )
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.get_user_setting",
        lambda key: [] if key == UserSettingKey.SDCARD_NAMES else str(output_root),
    )
    monkeypatch.setattr("piqopiqo.tools.copy_sd.get_state", lambda: state)
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.CopySdInputDialog",
        _FakeInputDialog,
    )
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd._resolve_dates_with_progress",
        lambda *_args, **_kwargs: [date(2026, 3, 3)],
    )
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd._confirm_copy",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.CopySdProgressDialog",
        _FakeProgressDialog,
    )

    launch_copy_sd(parent, on_bulk_copy_finished=_on_finished)

    expected_target_dirs = [str(output_root / "20260303_trip" / volume.name)]
    assert finish_calls == [(expected_target_dirs, 2)]
