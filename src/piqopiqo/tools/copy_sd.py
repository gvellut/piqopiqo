"""Copy photos from SD card to an external folder."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from enum import Enum, auto
import logging
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any

from attrs import define
from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.dialogs.settings_redirect import (
    prompt_open_settings_for_missing_setting,
)
from piqopiqo.dialogs.storage_full_dialog import wait_for_storage_retry
from piqopiqo.dialogs.unsaved_changes_dialog import UnsavedChangesDialog
from piqopiqo.folder_watcher import WorkspaceWatcherController
from piqopiqo.qt_workers import PythonOwnedRunnable
from piqopiqo.ssf.settings_state import (
    RuntimeSettingKey,
    StateKey,
    UserSettingKey,
    get_runtime_setting,
    get_state,
    get_user_setting,
)
from piqopiqo.storage import (
    StorageFullError,
    StorageWriteFault,
    probe_storage_write,
    storage_full_fault_from_error,
)
from piqopiqo.tools.tool_flow import (
    ToolButton,
    ToolFlowDialog,
    ToolScreen,
    ToolTaskHandle,
    ToolWorkflow,
)

logger = logging.getLogger(__name__)


DATE_FMT = "%Y%m%d"
OUTPUT_DATE_FMT = DATE_FMT
PREFIX_SINCE = "since:"
PREFIX_BETWEEN = "between:"


@define(frozen=True)
class PhotoVolume:
    name: str
    path: str


class MediaType(Enum):
    INTERNAL = auto()
    SD_CARD = auto()
    EXTERNAL = auto()
    UNKNOWN = auto()


def date_to_str(d):
    return d.isoformat()


def dirname_with_date(parent_folder, name, f_date):
    date_s = f_date.strftime(OUTPUT_DATE_FMT)
    output_folder = os.path.join(parent_folder, f"{date_s}_{name}")

    return output_folder


def find_date_folders(folder, subfolder=None):
    if not folder or not os.path.isdir(folder):
        return []
    date_pattern = re.compile(r"^\d{8}_")
    date_folders: set[str] = set()

    for root, dirnames, _ in os.walk(folder):
        for dirname in dirnames:
            if not date_pattern.match(dirname):
                continue
            full_path = os.path.join(root, dirname)
            if subfolder and not os.path.isdir(os.path.join(full_path, subfolder)):
                continue
            date_folders.add(dirname)

    return sorted(date_folders, reverse=True)


def is_since(date_s):
    return date_s.startswith(PREFIX_SINCE)


def is_between(date_s):
    return date_s.startswith(PREFIX_BETWEEN)


def is_dynamic(date_s):
    return is_since(date_s) or is_between(date_s) or date_s in ("L", "L2", "L3")


def _normalize_prefix_synonyms(date_s: str) -> str:
    """Expand short synonyms: s: -> since:, b: -> between:."""
    if date_s.startswith("s:"):
        return PREFIX_SINCE + date_s[2:]
    if date_s.startswith("b:"):
        return PREFIX_BETWEEN + date_s[2:]
    return date_s


def _get_since_last_folder_dates(volume: PhotoVolume) -> list[str]:
    folder_for_sd = volume.name
    return find_date_folders(
        get_user_setting(UserSettingKey.COPY_SD_BASE_EXTERNAL_FOLDER),
        subfolder=folder_for_sd,
    )


def _get_since_last_copied_date_label(volume: PhotoVolume) -> str | None:
    dirs = _get_since_last_folder_dates(volume)
    if not dirs:
        return None
    date_token = str(dirs[0])[:8]
    try:
        return datetime.strptime(date_token, DATE_FMT).date().isoformat()
    except ValueError:
        return date_token or None


def _build_no_images_message(date_spec: str, volume: PhotoVolume) -> str:
    spec = str(date_spec).strip().lower()
    if spec == "since:last":
        last_date = _get_since_last_copied_date_label(volume)
        if last_date:
            return f"No new photo found since last copied date {last_date}."
        return "No photo found and no previous copied date exists for this volume."
    return "No image found for the selected date(s)."


def _resolve_last_copied_date(volume: PhotoVolume) -> str:
    """Return the last copied date token for the volume, or a far-past fallback."""
    dirs = _get_since_last_folder_dates(volume)
    if dirs:
        token = dirs[0]
        logger.info("last => %s", token)
        return token
    logger.info("No existing folder: From the beginning")
    return "10000101"


def to_fixed_dates(date_s):
    if date_s == "TD":
        return datetime.now().date()

    if date_s == "YD":
        return datetime.now().date() - timedelta(days=1)

    if date_s == "YD2":
        return datetime.now().date() - timedelta(days=2)

    if date_s == "YD3":
        return datetime.now().date() - timedelta(days=3)

    return datetime.strptime(date_s, DATE_FMT).date()


def to_dynamic_dates(date_s, volume: PhotoVolume):
    if date_s == "L":
        # L for latest
        return find_latest_date(volume.path)

    if date_s == "L2":
        return find_latest_date(volume.path, rank=1)

    if date_s == "L3":
        return find_latest_date(volume.path, rank=2)

    # may return multiple dates

    if is_between(date_s):
        return _resolve_between(date_s, volume)

    if is_since(date_s):
        return _resolve_since(date_s, volume)


def _resolve_last_copied_date_before(
    volume: PhotoVolume,
    before: date,
) -> str:
    """Return the last copied date token for the volume that is before *before*."""
    dirs = _get_since_last_folder_dates(volume)
    for d in dirs:
        token = str(d)[:8]
        try:
            folder_date = datetime.strptime(token, DATE_FMT).date()
        except ValueError:
            continue
        if folder_date < before:
            logger.info("last before %s => %s", before.isoformat(), token)
            return token
    logger.info("No existing folder before %s: From the beginning", before.isoformat())
    return "10000101"


def _resolve_since(date_s: str, volume: PhotoVolume) -> list[date]:
    date_s = date_s[len(PREFIX_SINCE) :]
    if date_s == "last":
        date_s = _resolve_last_copied_date(volume)

    # only first 8 characters in case title copied
    date_s = date_s[:8]
    date_since = datetime.strptime(date_s, DATE_FMT).date()
    filtered = filter_after(find_all_dates(volume.path), date_since)
    if not filtered:
        logger.warning("No photo since last date.")
    return filtered


def _resolve_between(date_s: str, volume: PhotoVolume) -> list[date]:
    """Resolve between:START-END spec (both sides exclusive).

    If START is missing, uses the last copied date before END for the volume.
    """
    inner = date_s[len(PREFIX_BETWEEN) :]
    parts = inner.split("-", 1)
    start_str = parts[0].strip() if parts[0].strip() else ""
    end_str = parts[1].strip() if len(parts) > 1 and parts[1].strip() else ""

    # Parse end first so we can use it to resolve a missing start
    if end_str:
        end_str = end_str[:8]
        end_date = datetime.strptime(end_str, DATE_FMT).date()
    else:
        end_date = None

    if not start_str:
        if end_date is not None:
            start_str = _resolve_last_copied_date_before(volume, end_date)
        else:
            start_str = _resolve_last_copied_date(volume)

    # only first 8 characters in case title copied
    start_str = start_str[:8]
    start_date = datetime.strptime(start_str, DATE_FMT).date()

    all_dates = find_all_dates(volume.path)
    filtered = [
        d for d in all_dates if d > start_date and (end_date is None or d < end_date)
    ]
    if not filtered:
        logger.warning("No photo between the specified dates.")
    return filtered


def find_latest_date(volume_path, rank=0):
    dates = find_all_dates(volume_path)
    if not dates:
        return None
    if rank >= len(dates):
        return None
    return dates[rank]


def find_all_dates(volume_path):
    dates = []
    for root, _, filenames in os.walk(volume_path):
        for filename in filenames:
            if not filter_relevant_image(filename):
                continue
            file_path = os.path.join(root, filename)
            try:
                last_modified_date = datetime.fromtimestamp(os.path.getmtime(file_path))
            except OSError:
                continue
            dates.append(last_modified_date.date())
    if not dates:
        return []
    dates = list(set(dates))
    return sorted(dates, reverse=True)


def filter_after(dates, date_after):
    return [d for d in dates if d > date_after]


def get_volume(media: list[str]):
    volumes_path = "/Volumes"
    try:
        volumes = os.listdir(volumes_path)
    except FileNotFoundError:
        return None

    for volume in volumes:
        if volume in media:
            return PhotoVolume(volume, os.path.join(volumes_path, volume))

    return None


def get_volume_info(volume_path: str) -> dict[str, Any] | None:
    """Get metadata for a volume using diskutil."""
    try:
        result = subprocess.run(
            ["diskutil", "info", "-plist", volume_path],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    try:
        return plistlib.loads(result.stdout)
    except plistlib.InvalidFileException:
        return None


def get_media_type(volume_path: str) -> MediaType:
    info = get_volume_info(volume_path)
    if not info:
        return MediaType.UNKNOWN

    protocol = info.get("BusProtocol", "") or ""

    if "SD" in protocol or "Secure Digital" in protocol:
        return MediaType.SD_CARD

    is_internal = info.get("Internal", False)
    if is_internal:
        return MediaType.INTERNAL

    return MediaType.EXTERNAL


def find_sd_card_volumes() -> list[PhotoVolume]:
    volumes_path = "/Volumes"
    try:
        volumes = os.listdir(volumes_path)
    except FileNotFoundError:
        return []

    sd_volumes: list[PhotoVolume] = []
    for volume in volumes:
        volume_path = os.path.join(volumes_path, volume)
        if not os.path.isdir(volume_path):
            continue
        if get_media_type(volume_path) == MediaType.SD_CARD:
            sd_volumes.append(PhotoVolume(volume, volume_path))

    return sd_volumes


def get_sd_volume() -> PhotoVolume | None:
    sd_volumes = find_sd_card_volumes()
    if not sd_volumes:
        return None
    if len(sd_volumes) > 1:
        logger.warning(
            "Multiple SD cards detected (%s). Using %s.",
            ", ".join([v.name for v in sd_volumes]),
            sd_volumes[0].name,
        )
    return sd_volumes[0]


class EjectVolumeError(RuntimeError):
    """Raised when macOS does not verify that a volume was ejected."""


def _process_output_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace").strip()
    return str(value).strip()


def _volume_is_mounted(volume_path: str) -> bool:
    return os.path.exists(volume_path) and os.path.ismount(volume_path)


def _wait_until_unmounted(
    volume_path: str,
    *,
    deadline: float,
    poll_interval_s: float,
) -> bool:
    while True:
        if not _volume_is_mounted(volume_path):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(max(0.01, poll_interval_s), remaining))


def _format_eject_failure(
    volume: PhotoVolume,
    *,
    result: subprocess.CompletedProcess | None,
    command_error: str,
    stdout: object = None,
    stderr: object = None,
) -> str:
    lines = [
        f"Could not eject {volume.name}.",
        f"The volume is still mounted at {volume.path}.",
    ]
    if command_error:
        lines.append(command_error)
    elif result is not None and result.returncode:
        lines.append(f"diskutil eject failed with exit code {result.returncode}.")
    else:
        lines.append("Timed out waiting for macOS to unmount the volume.")

    stdout_text = _process_output_text(
        stdout if stdout is not None else getattr(result, "stdout", "")
    )
    stderr_text = _process_output_text(
        stderr if stderr is not None else getattr(result, "stderr", "")
    )
    if stdout_text:
        lines.append(f"stdout: {stdout_text}")
    if stderr_text:
        lines.append(f"stderr: {stderr_text}")
    return "\n".join(lines)


def eject_volume(
    volume: PhotoVolume,
    *,
    timeout_s: float,
    poll_interval_s: float = 0.25,
) -> None:
    timeout_value = max(0.0, float(timeout_s))
    deadline = time.monotonic() + timeout_value
    result: subprocess.CompletedProcess | None = None
    command_error = ""
    stdout: object = None
    stderr: object = None

    if not _volume_is_mounted(volume.path):
        return

    try:
        result = subprocess.run(
            ["diskutil", "eject", volume.path],
            capture_output=True,
            text=True,
            timeout=max(0.1, timeout_value),
        )
    except FileNotFoundError as exc:
        command_error = f"diskutil was not found: {exc}"
    except subprocess.TimeoutExpired as exc:
        command_error = f"diskutil eject timed out after {timeout_value:g} second(s)."
        stdout = exc.stdout
        stderr = exc.stderr

    if _wait_until_unmounted(
        volume.path,
        deadline=deadline,
        poll_interval_s=poll_interval_s,
    ):
        return

    raise EjectVolumeError(
        _format_eject_failure(
            volume,
            result=result,
            command_error=command_error,
            stdout=stdout,
            stderr=stderr,
        )
    )


def filter_relevant_image(filename):
    return filename.lower().endswith((".jpg", ".jpeg", ".raf", ".raw", ".m4a", ".avi"))


def iter_files_for_date(volume: PhotoVolume, f_date):
    for root, _, filenames in os.walk(volume.path):
        for filename in filenames:
            if not filter_relevant_image(filename):
                continue
            file_path = os.path.join(root, filename)
            try:
                last_modified_date = datetime.fromtimestamp(os.path.getctime(file_path))
            except OSError:
                continue

            if last_modified_date.date() == f_date:
                yield file_path


def _sort_dates(dates):
    try:
        return sorted(dates)
    except TypeError:
        return list(dates)


class CopySdWorkerSignals(QObject):
    status = Signal(str)
    plan_ready = Signal(int)
    progress = Signal(int, int)  # completed, total
    error = Signal(str)
    storage_full = Signal(object)  # StorageWriteFault
    finished = Signal(int, int, bool, int)  # copied, total, cancelled, error_count


class CopySdWorker(PythonOwnedRunnable):
    def __init__(
        self,
        volume: PhotoVolume,
        dates: list,
        target_dirs: list[str],
    ):
        super().__init__()
        self._volume = volume
        self._dates = dates
        self._target_dirs = target_dirs
        self._cancel_requested = threading.Event()
        self._retry_requested = threading.Event()
        self.signals = CopySdWorkerSignals()

    def request_cancel(self):
        self._cancel_requested.set()
        self._retry_requested.set()

    def request_retry(self):
        self._retry_requested.set()

    def _is_cancelled(self):
        return self._cancel_requested.is_set()

    def _wait_for_storage_retry(self, fault: StorageWriteFault) -> bool:
        self._retry_requested.clear()
        self.signals.storage_full.emit(fault)
        while not self._is_cancelled():
            if self._retry_requested.wait(0.1):
                self._retry_requested.clear()
                return not self._is_cancelled()
        return False

    @staticmethod
    def _copy_file_atomically(file_path: str, output_folder: str) -> None:
        os.makedirs(output_folder, exist_ok=True)
        destination = Path(output_folder) / os.path.basename(file_path)
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".part",
            dir=output_folder,
        )
        os.close(temp_fd)
        temp_path = Path(temp_name)
        try:
            shutil.copy2(file_path, temp_path)
            os.replace(temp_path, destination)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def run(self):
        copied = 0
        total = 0
        error_count = 0
        tasks: list[tuple[str, str]] = []

        try:
            for f_date, target_dir in zip(self._dates, self._target_dirs, strict=False):
                if self._is_cancelled():
                    break
                logger.info(
                    "Copy to %s (date: %s) ...", target_dir, date_to_str(f_date)
                )

                self.signals.status.emit(
                    f"Scanning for {date_to_str(f_date)} in {self._volume.name}..."
                )
                for file_path in iter_files_for_date(self._volume, f_date):
                    if self._is_cancelled():
                        break
                    tasks.append((file_path, target_dir))

            total = len(tasks)
            self.signals.plan_ready.emit(total)
            self.signals.progress.emit(0, total)
            if total:
                self.signals.status.emit("Copying files...")

            if total == 0:
                self.signals.finished.emit(0, 0, False, 0)
                return

            for file_path, output_folder in tasks:
                if self._is_cancelled():
                    break

                copied_current = False
                while not self._is_cancelled():
                    try:
                        self._copy_file_atomically(file_path, output_folder)
                    except Exception as exc:
                        fault = storage_full_fault_from_error(
                            exc,
                            target_path=output_folder,
                            operation="copy_from_sd",
                        )
                        if fault is not None:
                            logger.warning(
                                "Copy from SD paused because storage is full: %s",
                                exc,
                            )
                            if self._wait_for_storage_retry(fault):
                                self.signals.status.emit("Retrying copy...")
                                continue
                            break

                        error_count += 1
                        logger.exception("Error copying %s", file_path)
                        self.signals.error.emit(f"{file_path}: {exc}")
                        break
                    else:
                        copied_current = True
                        break

                if self._is_cancelled():
                    break
                if not copied_current:
                    continue

                copied += 1
                if copied % 20 == 0:
                    logger.info("Copy #%s: %s", copied, file_path)
                self.signals.progress.emit(copied, total)

            cancelled = self._is_cancelled()
            self.signals.finished.emit(copied, total, cancelled, error_count)
        except Exception as exc:
            error_count += 1
            logger.exception("Copy from SD failed")
            self.signals.error.emit(str(exc))
            self.signals.finished.emit(copied, total, True, error_count)


class CopySdInputDialog(UnsavedChangesDialog):
    def __init__(
        self,
        volume: PhotoVolume,
        parent=None,
        name="",
        date_spec="TD",
    ):
        super().__init__(parent)
        self.setWindowTitle("Copy from SD")
        self.setModal(True)
        self._volume = volume

        layout = QVBoxLayout(self)

        info_label = QLabel(
            f"Detected volume: {volume.name} ({volume.path})\n"
            "Destination base: "
            f"{get_user_setting(UserSettingKey.COPY_SD_BASE_EXTERNAL_FOLDER)}"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        form_layout = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setText(name)
        self.name_edit.setPlaceholderText("Session name")
        form_layout.addRow("Folder name", self.name_edit)

        self.date_edit = QLineEdit()
        self.date_edit.setText(date_spec)
        self.date_edit.setPlaceholderText("TD")
        form_layout.addRow("Date spec", self.date_edit)

        layout.addLayout(form_layout)

        help_label = QLabel(
            "Date spec examples: TD, YD, YYYYMMDD, YYYYMMDD-YYYYMMDD, "
            "since:YYYYMMDD (s:), since:last, between:YYYYMMDD-YYYYMMDD (b:), "
            "L/L2/L3."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        self._set_unsaved_changes_state(
            lambda: (self.name_edit.text(), self.date_edit.text())
        )

    def _on_accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Copy from SD", "Folder name is required.")
            return
        self.accept()

    def get_values(self):
        return (
            self.name_edit.text().strip(),
            self.date_edit.text().strip(),
        )


class CopySdProgressDialog(ToolFlowDialog):
    _eject_done = Signal(str)  # empty string on success, error message on failure

    def __init__(
        self,
        volume: PhotoVolume,
        dates: list,
        target_dirs: list[str],
        should_eject: bool,
        parent=None,
        no_images_message: str | None = None,
    ):
        self._volume = volume
        self._worker = CopySdWorker(volume, dates, target_dirs)
        self._finished = False
        self._error_count = 0
        self._started = False
        self._copied_count = 0
        self._was_cancelled = False
        self._eject_checked = bool(should_eject)
        self._eject_error_message = ""
        self._ignore_eject_result = False
        self._exit_application_requested = False
        self._storage_full_fault: StorageWriteFault | None = None
        self._eject_thread: threading.Thread | None = None
        self._no_images_message = (
            no_images_message or "No images found for the selected date(s)."
        )
        self.status_warning_icon_label: QLabel | None = None
        self.eject_checkbox: QCheckBox | None = None

        workflow = ToolWorkflow(
            initial_screen="running",
            screens={
                "running": ToolScreen(
                    id="running",
                    title="Copy from SD",
                    build=lambda dialog: dialog._build_body(),
                    buttons=(
                        ToolButton("cancel", "Cancel"),
                        ToolButton("ok", "OK", enabled=False),
                    ),
                    min_width=520,
                    show_progress=True,
                ),
                "result": ToolScreen(
                    id="result",
                    title="Copy from SD",
                    build=lambda dialog: dialog._build_body(),
                    buttons=(
                        ToolButton("cancel", "Cancel"),
                        ToolButton("ok", "OK", enabled=True, default=True),
                    ),
                    min_width=520,
                    show_progress=True,
                ),
                "storage_full": ToolScreen(
                    id="storage_full",
                    title="Copy Destination Full",
                    build=lambda dialog: dialog._build_storage_full_body(),
                    buttons=(
                        ToolButton(
                            "exit_app",
                            "Exit PiqoPiqo",
                            left_aligned=True,
                        ),
                        ToolButton("retry", "Retry", default=True),
                    ),
                    min_width=560,
                    show_progress=False,
                    close_policy="ignore",
                ),
                "ejecting": ToolScreen(
                    id="ejecting",
                    title="Copy from SD",
                    build=lambda dialog: None,
                    buttons=(ToolButton("cancel", "Cancel"),),
                    min_width=520,
                    show_progress=True,
                    show_progress_count=False,
                ),
                "ejected": ToolScreen(
                    id="ejected",
                    title="Copy from SD",
                    build=lambda dialog: dialog._build_ejected_body(),
                    buttons=(ToolButton("ok", "OK", enabled=True, default=True),),
                    min_width=520,
                    show_progress=False,
                ),
                "eject_error": ToolScreen(
                    id="eject_error",
                    title="Copy from SD",
                    build=lambda dialog: dialog._build_eject_error_body(),
                    buttons=(ToolButton("ok", "OK", enabled=True, default=True),),
                    min_width=520,
                    show_progress=False,
                ),
            },
            transitions={
                ("running", "cancel"): lambda dialog, event: dialog._on_cancel(),
                ("running", "ok"): lambda dialog, event: dialog._on_ok(),
                ("result", "cancel"): lambda dialog, event: dialog._on_cancel(),
                ("result", "ok"): lambda dialog, event: dialog._on_ok(),
                ("storage_full", "exit_app"): (
                    lambda dialog, event: dialog._on_storage_full_exit()
                ),
                ("storage_full", "retry"): (
                    lambda dialog, event: dialog._on_storage_full_retry()
                ),
                ("ejecting", "cancel"): lambda dialog, event: dialog._on_cancel(),
                ("ejected", "ok"): lambda dialog, event: dialog.accept(),
                ("eject_error", "ok"): lambda dialog, event: dialog.accept(),
                ("*", "status"): lambda dialog, event: dialog._on_status(*event.args),
                ("*", "plan_ready"): lambda dialog, event: dialog._on_plan_ready(
                    *event.args
                ),
                ("*", "progress"): lambda dialog, event: dialog._on_progress(
                    *event.args
                ),
                ("*", "error"): lambda dialog, event: dialog._on_error(*event.args),
                ("*", "storage_full"): (
                    lambda dialog, event: dialog._on_storage_full(*event.args)
                ),
                ("*", "finished"): lambda dialog, event: dialog._on_finished(
                    *event.args
                ),
            },
        )
        super().__init__(workflow, parent=parent)
        self._setup_status_warning_icon()
        self._setup_eject_checkbox()
        self.progress_bar.setRange(0, 0)
        self.set_status("Preparing copy...")
        self._eject_done.connect(self._on_eject_done)

    @property
    def copied_count(self) -> int:
        return int(self._copied_count)

    @property
    def was_cancelled(self) -> bool:
        return bool(self._was_cancelled)

    @property
    def eject_requested(self) -> bool:
        return bool(self._eject_checked)

    def transition_to(self, screen_id: str) -> None:
        super().transition_to(screen_id)
        self.status_label = self.status_label
        self.progress_text_label = self.progress_count_label
        self.cancel_btn = self.button("cancel")
        self.ok_btn = self.button("ok")
        if self.eject_checkbox is not None:
            self.eject_checkbox.hide()
        if self.status_warning_icon_label is not None:
            self.status_warning_icon_label.hide()

    def _build_body(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)

        self.error_label = QLabel(widget)
        self.error_label.setStyleSheet("color: red;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        return widget

    def _setup_eject_checkbox(self) -> None:
        self.eject_checkbox = QCheckBox("Eject SD card", self)
        self.eject_checkbox.setChecked(self._eject_checked)
        self.eject_checkbox.toggled.connect(self._set_eject_checked)
        self.eject_checkbox.hide()
        layout = self.layout()
        if layout is not None:
            layout.insertWidget(layout.count() - 1, self.eject_checkbox)

    def _setup_status_warning_icon(self) -> None:
        self.status_warning_icon_label = QLabel(self.progress_row)
        self.status_warning_icon_label.setObjectName("copySdWarningIcon")
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        self.status_warning_icon_label.setPixmap(icon.pixmap(24, 24))
        self.status_warning_icon_label.hide()
        layout = self.progress_row.layout()
        if layout is not None:
            layout.insertWidget(0, self.status_warning_icon_label)

    def _set_status_warning_icon_visible(self, visible: bool) -> None:
        if self.status_warning_icon_label is None:
            return
        self.status_warning_icon_label.setVisible(visible)

    def _build_ejected_body(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        label = QLabel("You can remove the SD Card safely", widget)
        label.setWordWrap(True)
        layout.addWidget(label)
        return widget

    def _build_eject_error_body(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        message = "Could not eject the SD card."
        if self._eject_error_message:
            message = f"{message}\n\n{self._eject_error_message}"
        label = QLabel(message, widget)
        label.setWordWrap(True)
        label.setStyleSheet("color: red;")
        layout.addWidget(label)
        return widget

    def _build_storage_full_body(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)

        headline = QLabel(
            "PiqoPiqo cannot continue copying because the destination storage is full.",
            widget,
        )
        headline.setWordWrap(True)
        layout.addWidget(headline)

        fault = self._storage_full_fault
        if fault is not None:
            path_label = QLabel(
                f"Storage location:\n{fault.target_path}",
                widget,
            )
            path_label.setWordWrap(True)
            layout.addWidget(path_label)

            error_label = QLabel(
                f"Write error: {fault.error_message}",
                widget,
            )
            error_label.setWordWrap(True)
            error_label.setStyleSheet("color: #b00020;")
            layout.addWidget(error_label)

        instructions = QLabel(
            "Completed files have been kept and the incomplete file was removed. "
            "Free space, then choose Retry to continue with the same image. "
            "Exit PiqoPiqo stops the copy and does not eject the SD card.",
            widget,
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        return widget

    def _set_eject_checked(self, checked: bool) -> None:
        self._eject_checked = bool(checked)

    def start(self):
        if self._started:
            return
        self._started = True
        self.start_task(
            "copy_sd",
            ToolTaskHandle.from_qrunnable(
                worker=self._worker,
                pool=QThreadPool.globalInstance(),
                signal_map={
                    self._worker.signals.status: "status",
                    self._worker.signals.plan_ready: "plan_ready",
                    self._worker.signals.progress: "progress",
                    self._worker.signals.error: "error",
                    self._worker.signals.storage_full: "storage_full",
                    self._worker.signals.finished: "finished",
                },
            ),
        )

    def showEvent(self, event):
        super().showEvent(event)
        self.start()

    def _set_progress_counter(self, completed: int, total: int):
        self.progress_text_label.setText(
            f"{max(0, int(completed))}/{max(0, int(total))}"
        )

    def _on_status(self, message: str):
        self._set_status_warning_icon_visible(False)
        self.set_status(message)

    def _on_plan_ready(self, total: int):
        if total <= 0:
            self.set_progress(0, 0)
            return
        self.set_progress(0, total)

    def _on_progress(self, completed: int, total: int):
        self.set_progress(completed, total)

    def _on_error(self, message: str):
        self._error_count += 1
        self.error_label.setText(f"Errors: {self._error_count}")
        self.error_label.show()
        logger.error(message)

    def _on_storage_full(self, fault: object):
        if not isinstance(fault, StorageWriteFault):
            return
        self._storage_full_fault = fault
        self.transition_to("storage_full")

    def _on_storage_full_retry(self):
        self.transition_to("running")
        self.set_status("Retrying copy...")
        self._worker.request_retry()

    def _on_storage_full_exit(self):
        self._exit_application_requested = True
        self._eject_checked = False
        exit_button = self.button("exit_app")
        retry_button = self.button("retry")
        if exit_button is not None:
            exit_button.setEnabled(False)
        if retry_button is not None:
            retry_button.setEnabled(False)
        self._worker.request_cancel()

    def _on_finished(self, copied: int, total: int, cancelled: bool, error_count: int):
        self._finished = True
        self._copied_count = max(0, int(copied))
        self._was_cancelled = bool(cancelled)
        if self._exit_application_requested:
            self._eject_checked = False
            QDialog.reject(self)
            QTimer.singleShot(0, self._quit_application)
            return

        self.transition_to("result")
        if total == 0:
            status = self._no_images_message
            self._set_status_warning_icon_visible(True)
        elif cancelled:
            status = f"Copy cancelled ({copied}/{total} file(s) copied)."
            self._set_status_warning_icon_visible(False)
        else:
            status = f"Copy complete. {copied} file(s) copied."
            self._set_status_warning_icon_visible(False)
        if error_count:
            status += f" {error_count} error(s)."

        self.set_status(status)
        if total:
            self.set_progress(min(copied, total), total)
        else:
            self.progress_bar.hide()
            self.progress_count_label.clear()
            self.progress_count_label.hide()
            self.sync_size_to_content()
        self.cancel_btn.setEnabled(False)
        self.ok_btn.setEnabled(True)
        self.ok_btn.setDefault(True)
        self.ok_btn.setFocus()
        if not cancelled and self.eject_checkbox is not None:
            self.eject_checkbox.show()
            self._set_unsaved_changes_state(lambda: self.eject_checkbox.isChecked())
            self.sync_size_to_content()

    @staticmethod
    def _quit_application() -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _on_ok(self):
        if self.eject_checkbox is not None:
            self._set_eject_checked(self.eject_checkbox.isChecked())
        if (
            self.eject_checkbox is not None
            and self.eject_checkbox.isChecked()
            and not self.eject_checkbox.isHidden()
        ):
            self._start_eject()
            return
        self.accept()

    def _start_eject(self) -> None:
        self._ignore_eject_result = False
        self.transition_to("ejecting")
        self.set_status("Ejecting SD Card...")
        self.set_progress(0, 0)
        self._start_eject_thread()

    def _start_eject_thread(self) -> None:
        self._eject_thread = threading.Thread(
            target=self._eject_in_background,
            daemon=True,
        )
        self._eject_thread.start()

    def _eject_in_background(self):
        try:
            timeout_s = get_runtime_setting(RuntimeSettingKey.COPY_SD_EJECT_TIMEOUT_S)
            eject_volume(self._volume, timeout_s=timeout_s)
            self._eject_done.emit("")
        except Exception as exc:
            logger.exception("Error ejecting %s", self._volume.name)
            self._eject_done.emit(str(exc))

    def _on_eject_done(self, error: str):
        if self._ignore_eject_result or self.current_screen_id != "ejecting":
            return
        if error:
            self._eject_error_message = str(error)
            self.transition_to("eject_error")
        else:
            self.transition_to("ejected")
        if self.ok_btn is not None:
            self.ok_btn.setDefault(True)
            self.ok_btn.setFocus()

    def _on_cancel(self):
        if self.current_screen_id == "ejecting":
            self._ignore_eject_result = True
            self.reject()
            return
        if self._finished:
            self.accept()
            return
        self.set_status("Cancelling...")
        self.cancel_btn.setEnabled(False)
        self.stop_task("copy_sd", cancel=True)

    def reject(self) -> None:
        if self.current_screen_id == "storage_full":
            return
        if self.current_screen_id == "ejecting":
            self._ignore_eject_result = True
        super().reject()

    def closeEvent(self, event):
        if self.current_screen_id == "storage_full":
            event.ignore()
            return
        if self.current_screen_id == "ejecting":
            self._ignore_eject_result = True
            super().closeEvent(event)
            return
        if not self._finished:
            self._on_cancel()
            event.ignore()
            return
        super().closeEvent(event)


class _CopySdConfirmDialog(QDialog):
    def __init__(
        self,
        parent,
        volume: PhotoVolume,
        dates: list,
        base_name: str,
    ):
        super().__init__(parent)
        self.setWindowTitle("Copy from SD")
        self.setModal(True)

        layout = QVBoxLayout(self)

        summary_label = QLabel(
            f"The images will be copied from: {volume.name} to <date>_{base_name}.",
            self,
        )
        summary_label.setWordWrap(True)
        layout.addWidget(summary_label)

        layout.addWidget(QLabel("Dates:", self))

        self.dates_text = QTextEdit(self)
        self.dates_text.setObjectName("copySdConfirmDatesText")
        self.dates_text.setReadOnly(True)
        self.dates_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.dates_text.setPlainText("\n".join(date_to_str(d) for d in dates))
        palette = self.dates_text.palette()
        palette.setColor(
            QPalette.ColorRole.Base,
            palette.color(QPalette.ColorRole.AlternateBase),
        )
        self.dates_text.setPalette(palette)
        visible_lines = min(max(len(dates), 2), 8)
        text_height = self.dates_text.fontMetrics().lineSpacing() * visible_lines
        frame_height = self.dates_text.frameWidth() * 2
        self.dates_text.setFixedHeight(text_height + frame_height + 16)
        layout.addWidget(self.dates_text)

        confirm_label = QLabel("Confirm?", self)
        confirm_label.setWordWrap(True)
        layout.addWidget(confirm_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def _confirm_copy(
    parent,
    volume: PhotoVolume,
    dates: list,
    base_name: str,
):
    dialog = _CopySdConfirmDialog(parent, volume, dates, base_name)
    return dialog.exec() == QDialog.DialogCode.Accepted


class _ResolveDatesSignals(QObject):
    finished = Signal(object)  # dates result or None
    error = Signal(str)


class _ResolveDatesWorker(PythonOwnedRunnable):
    def __init__(self, date_spec: str, volume: PhotoVolume):
        super().__init__()
        self._date_spec = date_spec
        self._volume = volume
        self.signals = _ResolveDatesSignals()

    def run(self):
        try:
            dates = to_dynamic_dates(self._date_spec, self._volume)
            self.signals.finished.emit(dates)
        except ValueError:
            self.signals.error.emit("Invalid date spec. Please try again.")


def _resolve_dates_with_progress(parent, date_spec: str, volume: PhotoVolume):
    """Run to_dates in a background thread with a progress dialog.

    Returns dates on success, an error string on ValueError, or None if cancelled.
    """
    # Fast path: specs that don't scan the filesystem
    normalized = _normalize_prefix_synonyms(date_spec)
    if not is_dynamic(normalized):
        # No worker needed for fixed dates
        try:
            return to_fixed_dates(date_spec)
        except ValueError:
            return "Invalid date spec. Please try again."

    result_holder: list[object] = []
    error_holder: list[str] = []

    worker = _ResolveDatesWorker(normalized, volume)

    def on_finished(dates):
        result_holder.append(dates)
        wait_dialog.accept()

    def on_error(msg):
        error_holder.append(msg)
        wait_dialog.accept()

    worker.signals.finished.connect(on_finished)
    worker.signals.error.connect(on_error)

    wait_dialog = QDialog(parent)
    wait_dialog.setWindowTitle("Copy from SD")
    wait_dialog.setModal(True)
    layout = QVBoxLayout(wait_dialog)
    date_spec_text = str(date_spec).strip()
    if date_spec_text.lower() == "since:last":
        checking_text = f"Checking dates (since:last) on {volume.name}..."
    else:
        checking_text = f"Checking dates on {volume.name}..."
    layout.addWidget(QLabel(checking_text))
    progress = QProgressBar()
    progress.setRange(0, 0)  # indeterminate
    layout.addWidget(progress)
    cancel_btn = QPushButton("Cancel")
    cancel_btn.clicked.connect(wait_dialog.reject)
    layout.addWidget(cancel_btn)

    QThreadPool.globalInstance().start(worker)

    if wait_dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    if error_holder:
        return error_holder[0]

    return result_holder[0] if result_holder else None


def _prepare_copy_destination(output_parent_folder: str) -> StorageWriteFault | None:
    try:
        os.makedirs(output_parent_folder, exist_ok=True)
        probe_storage_write(
            output_parent_folder,
            operation="copy_from_sd_destination_probe",
        )
    except StorageFullError as exc:
        return exc.fault
    except OSError as exc:
        fault = storage_full_fault_from_error(
            exc,
            target_path=output_parent_folder,
            operation="prepare_copy_from_sd_destination",
        )
        if fault is not None:
            return fault
        raise
    return None


def launch_copy_sd(
    parent=None,
    *,
    watcher_control: WorkspaceWatcherController | None = None,
):
    sdcard_names = get_user_setting(UserSettingKey.SDCARD_NAMES)
    if sdcard_names:
        volume = get_volume(sdcard_names)
        cards = ", ".join(sdcard_names)
        error_txt = f"No relevant SD card found: {cards}. Volume not renamed?"
    else:
        volume = get_sd_volume()
        error_txt = "No SD card found."

    if not volume:
        QMessageBox.warning(parent, "Copy from SD", error_txt)
        return

    output_parent_folder = get_user_setting(UserSettingKey.COPY_SD_BASE_EXTERNAL_FOLDER)
    if not output_parent_folder:
        should_open_settings = prompt_open_settings_for_missing_setting(
            parent,
            title="Copy from SD",
            text="BASE_EXTERNAL_FOLDER is not configured.",
            icon=QMessageBox.Icon.Critical,
        )
        if should_open_settings:
            open_settings = getattr(parent, "open_settings_for_key", None)
            if callable(open_settings):
                open_settings(UserSettingKey.COPY_SD_BASE_EXTERNAL_FOLDER)
        return

    try:
        destination_fault = _prepare_copy_destination(output_parent_folder)
    except OSError as exc:
        QMessageBox.critical(
            parent,
            "Copy from SD",
            f"Cannot access output folder: {output_parent_folder}\n{exc}",
        )
        return
    if destination_fault is not None:
        recovered = wait_for_storage_retry(
            parent=parent,
            fault=destination_fault,
            retry=lambda: _prepare_copy_destination(output_parent_folder),
            title="Copy Destination Full",
            headline=(
                "PiqoPiqo cannot start copying because the destination storage is full."
            ),
            retry_description=(
                "Free space on the destination volume, then choose Retry. "
                "Exit PiqoPiqo closes the application safely."
            ),
        )
        if not recovered:
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return

    state = get_state()
    name = state.get(StateKey.COPY_SD_NAME_SUFFIX) or ""
    date_spec = state.get(StateKey.COPY_SD_DATE_SPEC) or ""

    while True:
        dialog = CopySdInputDialog(
            volume,
            parent=parent,
            name=name,
            date_spec=date_spec,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        name, date_spec = dialog.get_values()

        result = _resolve_dates_with_progress(parent, date_spec, volume)
        if result is None:
            # dialog was cancelled
            continue
        if isinstance(result, str):
            # error message
            QMessageBox.warning(parent, "Copy from SD", result)
            continue

        dates = result
        if not dates:
            progress_dialog = CopySdProgressDialog(
                volume,
                [],
                [],
                should_eject=state.get(StateKey.COPY_SD_EJECT),
                parent=parent,
                no_images_message=_build_no_images_message(date_spec, volume),
            )
            progress_dialog.exec()
            state.set(StateKey.COPY_SD_NAME_SUFFIX, name)
            state.set(StateKey.COPY_SD_DATE_SPEC, date_spec)
            state.set(StateKey.COPY_SD_EJECT, progress_dialog.eject_requested)
            return

        if not isinstance(dates, list):
            dates = [dates]
        dates = _sort_dates(dates)
        break

    target_dirs = [
        os.path.join(
            dirname_with_date(output_parent_folder, name, f_date),
            volume.name,
        )
        for f_date in dates
    ]

    if not _confirm_copy(parent, volume, dates, name):
        logger.warning("Aborted by user")
        return

    should_eject = state.get(StateKey.COPY_SD_EJECT)
    progress_dialog = CopySdProgressDialog(
        volume, dates, target_dirs, should_eject=should_eject, parent=parent
    )

    try:
        if watcher_control is not None:
            watcher_control.suspend()
        progress_dialog.exec()
    finally:
        if watcher_control is not None:
            watcher_control.resume_and_refresh()

    # Save user choices for next session
    state.set(StateKey.COPY_SD_NAME_SUFFIX, name)
    state.set(StateKey.COPY_SD_DATE_SPEC, date_spec)
    state.set(StateKey.COPY_SD_EJECT, progress_dialog.eject_requested)
