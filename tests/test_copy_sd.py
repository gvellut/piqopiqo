"""Tests for copy-from-SD dialog helpers and progress UI."""

from __future__ import annotations

from datetime import date
import errno
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QTextEdit
import pytest

from piqopiqo.ssf.settings_state import StateKey, UserSettingKey
from piqopiqo.storage import StorageWriteFault
from piqopiqo.tools.copy_sd import (
    CopySdProgressDialog,
    CopySdWorker,
    EjectVolumeError,
    PhotoVolume,
    _build_no_images_message,
    _CopySdConfirmDialog,
    _resolve_dates_with_progress,
    eject_volume,
    launch_copy_sd,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_copy_confirm_dialog_shows_dates_in_read_only_text_edit(qapp):  # noqa: ARG001
    dialog = _CopySdConfirmDialog(
        None,
        PhotoVolume("CARD", "/Volumes/CARD"),
        [date(2026, 3, 1), date(2026, 3, 2)],
        "annecy",
    )

    dates_text = dialog.findChild(QTextEdit, "copySdConfirmDatesText")

    assert dates_text is not None
    assert dates_text.isReadOnly() is True
    lines = dates_text.toPlainText().splitlines()
    assert lines == ["2026-03-01", "2026-03-02"]
    assert all(not line.startswith("- ") for line in lines)


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


def test_resolve_dates_fixed_spec_uses_fast_path_without_volume_arg():
    result = _resolve_dates_with_progress(
        None,
        "20260201",
        PhotoVolume("CARD", "/Volumes/CARD"),
    )

    assert result == date(2026, 2, 1)


def test_copy_worker_does_not_create_target_dir_when_no_images(monkeypatch):
    makedirs_calls: list[str] = []
    finished: list[tuple[int, int, bool, int]] = []

    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.iter_files_for_date",
        lambda _volume, _f_date: iter(()),
    )
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.os.makedirs",
        lambda path, exist_ok=False: makedirs_calls.append(path),
    )

    worker = CopySdWorker(
        PhotoVolume("CARD", "/Volumes/CARD"),
        [date(2026, 2, 1)],
        ["/exports/20260201_trip/CARD"],
    )
    worker.signals.finished.connect(lambda *args: finished.append(args))

    worker.run()

    assert makedirs_calls == []
    assert finished == [(0, 0, False, 0)]


def test_copy_worker_atomically_copies_image(monkeypatch, tmp_path):
    source = tmp_path / "CARD" / "DCIM" / "a.jpg"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"photo")
    target_dir = tmp_path / "exports" / "20260201_trip" / "CARD"
    finished: list[tuple[int, int, bool, int]] = []

    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.iter_files_for_date",
        lambda _volume, _f_date: iter((str(source),)),
    )

    worker = CopySdWorker(
        PhotoVolume("CARD", "/Volumes/CARD"),
        [date(2026, 2, 1)],
        [str(target_dir)],
    )
    worker.signals.finished.connect(lambda *args: finished.append(args))

    worker.run()

    assert (target_dir / "a.jpg").read_bytes() == b"photo"
    assert not list(target_dir.glob("*.part"))
    assert not list(target_dir.glob(".*.part"))
    assert finished == [(1, 1, False, 0)]


def test_atomic_copy_failure_preserves_destination_and_removes_partial(
    monkeypatch, tmp_path
):
    source = tmp_path / "a.jpg"
    source.write_bytes(b"new")
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    destination = target_dir / "a.jpg"
    destination.write_bytes(b"old")

    def _partial_copy(_source, temp_path):
        Path(temp_path).write_bytes(b"partial")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr("piqopiqo.tools.copy_sd.shutil.copy2", _partial_copy)

    with pytest.raises(OSError, match="No space left"):
        CopySdWorker._copy_file_atomically(str(source), str(target_dir))

    assert destination.read_bytes() == b"old"
    assert not list(target_dir.glob("*.part"))
    assert not list(target_dir.glob(".*.part"))


def test_copy_worker_pauses_and_retries_same_file_on_storage_full(monkeypatch):
    files = ["/card/a.jpg", "/card/b.jpg", "/card/c.jpg"]
    worker = CopySdWorker(
        PhotoVolume("CARD", "/Volumes/CARD"),
        [date(2026, 2, 1)],
        ["/exports"],
    )
    attempts: list[str] = []
    full_seen = threading.Event()
    finished: list[tuple[int, int, bool, int]] = []
    failed_once = {"value": False}

    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.iter_files_for_date",
        lambda _volume, _date: iter(files),
    )

    def _copy(file_path, _output_folder):
        attempts.append(file_path)
        if file_path == "/card/b.jpg" and not failed_once["value"]:
            failed_once["value"] = True
            raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(worker, "_copy_file_atomically", _copy)
    worker.signals.storage_full.connect(
        lambda _fault: full_seen.set(),
        Qt.ConnectionType.DirectConnection,
    )
    worker.signals.finished.connect(
        lambda *args: finished.append(args),
        Qt.ConnectionType.DirectConnection,
    )

    thread = threading.Thread(target=worker.run)
    thread.start()
    assert full_seen.wait(2)
    assert attempts == ["/card/a.jpg", "/card/b.jpg"]

    worker.request_retry()
    thread.join(2)

    assert thread.is_alive() is False
    assert attempts == [
        "/card/a.jpg",
        "/card/b.jpg",
        "/card/b.jpg",
        "/card/c.jpg",
    ]
    assert finished == [(3, 3, False, 0)]


def test_copy_worker_exit_wakes_storage_wait_and_cancels(monkeypatch):
    worker = CopySdWorker(
        PhotoVolume("CARD", "/Volumes/CARD"),
        [date(2026, 2, 1)],
        ["/exports"],
    )
    full_seen = threading.Event()
    finished: list[tuple[int, int, bool, int]] = []
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.iter_files_for_date",
        lambda _volume, _date: iter(("/card/a.jpg", "/card/b.jpg")),
    )
    monkeypatch.setattr(
        worker,
        "_copy_file_atomically",
        lambda *_args: (_ for _ in ()).throw(
            OSError(errno.ENOSPC, "No space left on device")
        ),
    )
    worker.signals.storage_full.connect(
        lambda _fault: full_seen.set(),
        Qt.ConnectionType.DirectConnection,
    )
    worker.signals.finished.connect(
        lambda *args: finished.append(args),
        Qt.ConnectionType.DirectConnection,
    )

    thread = threading.Thread(target=worker.run)
    thread.start()
    assert full_seen.wait(2)
    worker.request_cancel()
    thread.join(2)

    assert thread.is_alive() is False
    assert finished == [(0, 2, True, 0)]


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


def test_copy_storage_full_screen_places_exit_left_and_retry_right(qapp, tmp_path):  # noqa: ARG001
    dialog = CopySdProgressDialog(
        volume=PhotoVolume("CARD", "/Volumes/CARD"),
        dates=[],
        target_dirs=[],
        should_eject=True,
    )
    fault = StorageWriteFault(
        target_path=str(tmp_path),
        operation="copy_from_sd",
        error_message="No space left on device",
    )

    dialog._on_storage_full(fault)

    assert dialog.current_screen_id == "storage_full"
    assert dialog._button_row.itemAt(0).widget() is dialog.button("exit_app")
    assert dialog._button_row.itemAt(1).spacerItem() is not None
    assert dialog._button_row.itemAt(2).widget() is dialog.button("retry")
    assert dialog.button("retry").isDefault() is True


def test_copy_storage_full_retry_resumes_waiting_worker(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    dialog = CopySdProgressDialog(
        volume=PhotoVolume("CARD", "/Volumes/CARD"),
        dates=[],
        target_dirs=[],
        should_eject=False,
    )
    fault = StorageWriteFault(
        target_path=str(tmp_path),
        operation="copy_from_sd",
        error_message="No space left on device",
    )
    retry_calls: list[bool] = []
    monkeypatch.setattr(
        dialog._worker,
        "request_retry",
        lambda: retry_calls.append(True),
    )
    dialog._on_storage_full(fault)

    dialog._on_storage_full_retry()

    assert retry_calls == [True]
    assert dialog.current_screen_id == "running"
    assert dialog.status_label.text() == "Retrying copy..."


def test_copy_storage_full_exit_quits_without_eject(qapp, tmp_path, monkeypatch):
    dialog = CopySdProgressDialog(
        volume=PhotoVolume("CARD", "/Volumes/CARD"),
        dates=[],
        target_dirs=[],
        should_eject=True,
    )
    fault = StorageWriteFault(
        target_path=str(tmp_path),
        operation="copy_from_sd",
        error_message="No space left on device",
    )
    cancel_calls: list[bool] = []
    quit_calls: list[bool] = []
    monkeypatch.setattr(
        dialog._worker,
        "request_cancel",
        lambda: cancel_calls.append(True),
    )
    monkeypatch.setattr(
        CopySdProgressDialog,
        "_quit_application",
        staticmethod(lambda: quit_calls.append(True)),
    )
    dialog._on_storage_full(fault)

    dialog._on_storage_full_exit()
    dialog._on_finished(2, 5, True, 0)
    qapp.processEvents()

    assert cancel_calls == [True]
    assert quit_calls == [True]
    assert dialog.eject_requested is False
    assert dialog.was_cancelled is True


def test_copy_result_ok_without_eject_accepts(qapp):  # noqa: ARG001
    dialog = CopySdProgressDialog(
        volume=PhotoVolume("CARD", "/Volumes/CARD"),
        dates=[],
        target_dirs=[],
        should_eject=True,
    )
    dialog._on_finished(1, 1, False, 0)
    assert dialog.eject_checkbox is not None
    assert dialog._has_unsaved_changes() is False
    dialog.eject_checkbox.setChecked(False)
    assert dialog._has_unsaved_changes() is True

    dialog._on_ok()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.eject_requested is False


def test_copy_complete_result_places_eject_checkbox_at_bottom(qapp):  # noqa: ARG001
    dialog = CopySdProgressDialog(
        volume=PhotoVolume("CARD", "/Volumes/CARD"),
        dates=[],
        target_dirs=[],
        should_eject=True,
    )

    dialog._on_finished(1, 1, False, 0)

    assert dialog.eject_checkbox is not None
    layout = dialog.layout()
    progress_index = layout.indexOf(dialog.progress_bar)
    checkbox_index = layout.indexOf(dialog.eject_checkbox)
    assert checkbox_index == progress_index + 1
    assert dialog.eject_checkbox.isHidden() is False


def test_copy_result_ok_with_eject_shows_ejecting_screen(qapp, monkeypatch):  # noqa: ARG001
    started: list[bool] = []
    monkeypatch.setattr(
        CopySdProgressDialog,
        "_start_eject_thread",
        lambda _dialog: started.append(True),
    )
    dialog = CopySdProgressDialog(
        volume=PhotoVolume("CARD", "/Volumes/CARD"),
        dates=[],
        target_dirs=[],
        should_eject=True,
    )
    dialog._on_finished(1, 1, False, 0)
    assert dialog.eject_checkbox is not None
    dialog.eject_checkbox.setChecked(True)

    dialog._on_ok()

    assert started == [True]
    assert dialog.current_screen_id == "ejecting"
    assert dialog.status_label.text() == "Ejecting SD Card..."
    assert dialog.progress_bar.minimum() == 0
    assert dialog.progress_bar.maximum() == 0
    assert dialog.progress_count_label.isHidden() is True


def test_copy_no_images_result_shows_eject_checkbox(qapp):  # noqa: ARG001
    dialog = CopySdProgressDialog(
        volume=PhotoVolume("CARD", "/Volumes/CARD"),
        dates=[],
        target_dirs=[],
        should_eject=True,
    )

    dialog._on_finished(0, 0, False, 0)

    assert dialog.current_screen_id == "result"
    assert dialog.status_label.text() == "No images found for the selected date(s)."
    assert dialog.status_warning_icon_label is not None
    assert dialog.status_warning_icon_label.isHidden() is False
    assert dialog.status_warning_icon_label.pixmap() is not None
    assert dialog.status_warning_icon_label.pixmap().isNull() is False
    assert dialog.eject_checkbox is not None
    assert dialog.eject_checkbox.isHidden() is False
    assert dialog.progress_bar.isHidden() is True
    assert dialog.progress_count_label.isHidden() is True
    layout = dialog.layout()
    assert layout.indexOf(dialog.eject_checkbox) == (
        layout.indexOf(dialog.progress_bar) + 1
    )


def test_copy_no_images_result_uses_custom_message(qapp):  # noqa: ARG001
    dialog = CopySdProgressDialog(
        volume=PhotoVolume("CARD", "/Volumes/CARD"),
        dates=[],
        target_dirs=[],
        should_eject=True,
        no_images_message="No new photo found since last copied date 2026-02-01.",
    )

    dialog._on_finished(0, 0, False, 0)

    assert (
        dialog.status_label.text()
        == "No new photo found since last copied date 2026-02-01."
    )


def test_copy_eject_success_shows_safe_remove_screen(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(
        CopySdProgressDialog, "_start_eject_thread", lambda _dialog: None
    )
    dialog = CopySdProgressDialog(
        volume=PhotoVolume("CARD", "/Volumes/CARD"),
        dates=[],
        target_dirs=[],
        should_eject=True,
    )
    dialog._started = True
    dialog.show()
    qapp.processEvents()

    dialog._on_finished(1, 1, False, 0)
    dialog._on_ok()
    qapp.processEvents()
    ejecting_height = dialog.height()

    dialog._on_eject_done("")
    qapp.processEvents()

    assert dialog.current_screen_id == "ejected"
    assert dialog.progress_row.isHidden() is True
    assert dialog.progress_bar.isHidden() is True
    assert dialog.height() < ejecting_height
    assert dialog.minimumHeight() == dialog.maximumHeight() == dialog.height()
    assert any(
        label.text() == "You can remove the SD Card safely"
        for label in dialog.findChildren(QLabel)
    )


def test_copy_eject_failure_shows_error_screen(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(
        CopySdProgressDialog, "_start_eject_thread", lambda _dialog: None
    )
    dialog = CopySdProgressDialog(
        volume=PhotoVolume("CARD", "/Volumes/CARD"),
        dates=[],
        target_dirs=[],
        should_eject=True,
    )
    dialog._on_finished(1, 1, False, 0)
    dialog._on_ok()

    dialog._on_eject_done("The volume is still mounted.")

    assert dialog.current_screen_id == "eject_error"
    assert dialog.progress_bar.isHidden() is True
    label_text = "\n".join(label.text() for label in dialog.findChildren(QLabel))
    assert "Could not eject the SD card." in label_text
    assert "The volume is still mounted." in label_text


def test_copy_eject_cancel_closes_and_ignores_late_completion(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(
        CopySdProgressDialog, "_start_eject_thread", lambda _dialog: None
    )
    dialog = CopySdProgressDialog(
        volume=PhotoVolume("CARD", "/Volumes/CARD"),
        dates=[],
        target_dirs=[],
        should_eject=True,
    )
    dialog._on_finished(1, 1, False, 0)
    dialog._on_ok()

    dialog._on_cancel()
    dialog._on_eject_done("")

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.current_screen_id == "ejecting"


def test_eject_volume_accepts_command_failure_when_volume_unmounts(monkeypatch):
    calls: list[list[str]] = []
    mount_states = iter([True, False])

    def _fake_run(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, stdout="failed", stderr="busy")

    monkeypatch.setattr("piqopiqo.tools.copy_sd.subprocess.run", _fake_run)
    monkeypatch.setattr("piqopiqo.tools.copy_sd.os.path.exists", lambda _path: True)
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.os.path.ismount",
        lambda _path: next(mount_states),
    )

    eject_volume(PhotoVolume("CARD", "/Volumes/CARD"), timeout_s=0)

    assert calls == [["diskutil", "eject", "/Volumes/CARD"]]


def test_eject_volume_raises_when_volume_stays_mounted(monkeypatch):
    def _fake_run(args, **_kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="out", stderr="err")

    monkeypatch.setattr("piqopiqo.tools.copy_sd.subprocess.run", _fake_run)
    monkeypatch.setattr("piqopiqo.tools.copy_sd.os.path.exists", lambda _path: True)
    monkeypatch.setattr("piqopiqo.tools.copy_sd.os.path.ismount", lambda _path: True)

    with pytest.raises(EjectVolumeError) as exc_info:
        eject_volume(PhotoVolume("CARD", "/Volumes/CARD"), timeout_s=0)

    message = str(exc_info.value)
    assert "The volume is still mounted at /Volumes/CARD." in message
    assert "diskutil eject failed with exit code 1." in message
    assert "stdout: out" in message
    assert "stderr: err" in message


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


class _WatcherControlSpy:
    def __init__(self) -> None:
        self.suspend_calls = 0
        self.resume_calls = 0

    def suspend(self) -> None:
        self.suspend_calls += 1

    def resume_and_refresh(self) -> None:
        self.resume_calls += 1


def test_launch_copy_sd_empty_resolved_dates_uses_result_eject_dialog(
    monkeypatch, tmp_path
):
    output_root = tmp_path / "exports"
    output_root.mkdir()
    state = _FakeState()
    state.values[StateKey.COPY_SD_EJECT] = True
    volume = PhotoVolume("CARD", "/Volumes/CARD")
    parent = SimpleNamespace()
    captured: dict[str, object] = {}
    information_calls: list[tuple[object, ...]] = []
    confirm_calls: list[tuple[object, ...]] = []

    class _FakeInputDialog:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ARG002
            return None

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

        def get_values(self):
            return ("annecy", "since:last")

    class _FakeProgressDialog:
        def __init__(
            self,
            volume,
            dates,
            target_dirs,
            should_eject,
            parent=None,
            no_images_message=None,
        ) -> None:
            captured["volume"] = volume
            captured["dates"] = list(dates)
            captured["target_dirs"] = list(target_dirs)
            captured["should_eject"] = should_eject
            captured["parent"] = parent
            captured["no_images_message"] = no_images_message
            self.eject_requested = False

        def exec(self) -> int:
            captured["exec_called"] = True
            return QDialog.DialogCode.Accepted

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
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd._get_since_last_copied_date_label",
        lambda _volume: "2026-02-01",
    )
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd._confirm_copy",
        lambda *args, **_kwargs: confirm_calls.append(args) or True,
    )
    monkeypatch.setattr(
        "piqopiqo.tools.copy_sd.CopySdProgressDialog",
        _FakeProgressDialog,
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **_kwargs: information_calls.append(args),
    )

    launch_copy_sd(parent)

    assert captured == {
        "volume": volume,
        "dates": [],
        "target_dirs": [],
        "should_eject": True,
        "parent": parent,
        "no_images_message": "No new photo found since last copied date 2026-02-01.",
        "exec_called": True,
    }
    assert information_calls == []
    assert confirm_calls == []
    assert state.values[StateKey.COPY_SD_NAME_SUFFIX] == "annecy"
    assert state.values[StateKey.COPY_SD_DATE_SPEC] == "since:last"
    assert state.values[StateKey.COPY_SD_EJECT] is False


def test_launch_copy_sd_suspends_and_resumes_watcher_control(monkeypatch, tmp_path):
    output_root = tmp_path / "exports"
    output_root.mkdir()
    state = _FakeState()
    volume = PhotoVolume("CARD", "/Volumes/CARD")
    watcher_control = _WatcherControlSpy()

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
            self.eject_requested = should_eject
            self.eject_checkbox = _FakeCheckbox(should_eject)

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

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
        SimpleNamespace(),
        watcher_control=watcher_control,
    )

    assert watcher_control.suspend_calls == 1
    assert watcher_control.resume_calls == 1


def test_launch_copy_sd_resumes_watcher_control_for_partial_cancel(
    monkeypatch, tmp_path
):
    output_root = tmp_path / "exports"
    output_root.mkdir()
    state = _FakeState()
    volume = PhotoVolume("CARD", "/Volumes/CARD")
    watcher_control = _WatcherControlSpy()

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
            self.eject_requested = should_eject
            self.eject_checkbox = _FakeCheckbox(should_eject)

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

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

    launch_copy_sd(SimpleNamespace(), watcher_control=watcher_control)

    assert watcher_control.suspend_calls == 1
    assert watcher_control.resume_calls == 1
