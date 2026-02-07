"""Copy photos from SD card to an external folder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum, auto
import logging
import os
import plistlib
import re
import shutil
import subprocess
import threading
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .config import Config

logger = logging.getLogger(__name__)


DATE_FMT = "%Y%m%d"
OUTPUT_DATE_FMT = DATE_FMT
PREFIX_SINCE = "since:"


@dataclass(frozen=True)
class PhotoVolume:
    name: str
    path: str


@dataclass(frozen=True)
class DateRange:
    start: date | None
    end: date | None


class MediaType(Enum):
    INTERNAL = auto()
    SD_CARD = auto()
    EXTERNAL = auto()
    UNKNOWN = auto()


def date_to_str(d):
    if isinstance(d, DateRange):
        s = []
        if d.start:
            s.append(d.start.isoformat() + " ")
        s.append("-")
        if d.end:
            s.append(" " + d.end.isoformat())
        return "".join(s)
    return d.isoformat()


def dirname_with_date(parent_folder, name, f_date):
    if isinstance(f_date, DateRange):
        # all the same anyway
        date_r = f_date
        if date_r.end:
            f_date = date_r.end
        elif date_r.start:
            f_date = date_r.start
        else:
            # today
            f_date = datetime.now().date()

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


def to_dates(date_s, volume: PhotoVolume):
    if date_s == "TD":
        return datetime.now().date()

    if date_s == "YD":
        return datetime.now().date() - timedelta(days=1)

    if date_s == "YD2":
        return datetime.now().date() - timedelta(days=2)

    if date_s == "YD3":
        return datetime.now().date() - timedelta(days=3)

    if date_s == "L":
        # L for latest
        return find_latest_date(volume.path)

    if date_s == "L2":
        return find_latest_date(volume.path, rank=1)

    if date_s == "L3":
        return find_latest_date(volume.path, rank=2)

    if "-" in date_s:
        return parse_date_range(date_s)

    # may return multiple dates
    if is_since(date_s):
        date_s = date_s[len(PREFIX_SINCE) :]
        if date_s == "last":
            folder_for_sd = volume.name
            dirs = find_date_folders(
                Config.BASE_EXTERNAL_FOLDER, subfolder=folder_for_sd
            )
            if dirs:
                # replace with last folder in order
                date_s = dirs[0]
                logger.info("last => %s", date_s)
            else:
                # no folder (new camera maybe?)
                # dummy date far in the past
                date_s = "10000101"
                logger.info("No existing folder: From the beginning")

        # only first 8 characters in case title copied
        date_s = date_s[:8]
        date_since = datetime.strptime(date_s, DATE_FMT).date()
        filtered = filter_after(find_all_dates(volume.path), date_since)
        if not filtered:
            logger.warning("No photo since last date.")
        return filtered

    return datetime.strptime(date_s, DATE_FMT).date()


def parse_date_range(date_range_str):
    dates = date_range_str.split("-")
    start_date = datetime.strptime(dates[0], DATE_FMT).date() if dates[0] else None
    end_date = (
        datetime.strptime(dates[1], DATE_FMT).date()
        if len(dates) > 1 and dates[1]
        else None
    )

    return DateRange(start_date, end_date)


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


def eject_volume(volume_name):
    subprocess.run(["diskutil", "eject", f"/Volumes/{volume_name}"])


def filter_relevant_image(filename):
    return filename.lower().endswith((".jpg", ".jpeg", ".raf", ".raw", ".m4a", ".avi"))


def filter_by_date(image_date, date_):
    if isinstance(date_, DateRange):
        if date_.start and image_date < date_.start:
            return False
        if date_.end and image_date > date_.end:
            return False
        return True
    return image_date == date_


def iter_files_for_date(volume: PhotoVolume, f_date):
    for root, _, filenames in os.walk(volume.path):
        for filename in filenames:
            if not filter_relevant_image(filename):
                continue
            file_path = os.path.join(root, filename)
            try:
                last_modified_date = datetime.fromtimestamp(os.path.getmtime(file_path))
            except OSError:
                continue
            if filter_by_date(last_modified_date.date(), f_date):
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
    finished = Signal(int, int, bool, int)  # copied, total, cancelled, error_count


class CopySdWorker(QRunnable):
    def __init__(
        self,
        volume: PhotoVolume,
        dates: list,
        output_folder_base: list[str],
        should_eject: bool,
    ):
        super().__init__()
        self._volume = volume
        self._dates = dates
        self._output_folder_base = output_folder_base
        self._should_eject = should_eject
        self._cancel_requested = threading.Event()
        self.signals = CopySdWorkerSignals()

    def request_cancel(self):
        self._cancel_requested.set()

    def _is_cancelled(self):
        return self._cancel_requested.is_set()

    def run(self):
        copied = 0
        total = 0
        error_count = 0
        tasks: list[tuple[str, str]] = []

        try:
            for f_date, folder_base in zip(
                self._dates, self._output_folder_base, strict=False
            ):
                if self._is_cancelled():
                    break
                logger.info(
                    "Copy to %s (date: %s) ...", folder_base, date_to_str(f_date)
                )
                os.makedirs(folder_base, exist_ok=True)
                output_folder = os.path.join(folder_base, self._volume.name)
                os.makedirs(output_folder, exist_ok=True)

                self.signals.status.emit(
                    f"Scanning for {date_to_str(f_date)} in {self._volume.name}..."
                )
                for file_path in iter_files_for_date(self._volume, f_date):
                    if self._is_cancelled():
                        break
                    tasks.append((file_path, output_folder))

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
                try:
                    shutil.copy2(file_path, output_folder)
                except Exception as exc:
                    error_count += 1
                    logger.exception("Error copying %s", file_path)
                    self.signals.error.emit(f"{file_path}: {exc}")
                    continue

                copied += 1
                if copied % 20 == 0:
                    logger.info("Copy #%s: %s", copied, file_path)
                self.signals.progress.emit(copied, total)

            cancelled = self._is_cancelled()
            if not cancelled and self._should_eject:
                self.signals.status.emit(f"Ejecting {self._volume.name} ...")
                try:
                    eject_volume(self._volume.name)
                except Exception as exc:
                    error_count += 1
                    logger.exception("Error ejecting %s", self._volume.name)
                    self.signals.error.emit(
                        f"Error ejecting {self._volume.name}: {exc}"
                    )

            self.signals.finished.emit(copied, total, cancelled, error_count)
        except Exception as exc:
            error_count += 1
            logger.exception("Copy from SD failed")
            self.signals.error.emit(str(exc))
            self.signals.finished.emit(copied, total, True, error_count)


class CopySdInputDialog(QDialog):
    def __init__(
        self,
        volume: PhotoVolume,
        parent=None,
        name="",
        date_spec="TD",
        should_eject=True,
    ):
        super().__init__(parent)
        self.setWindowTitle("Copy from SD")
        self.setModal(True)
        self._volume = volume

        layout = QVBoxLayout(self)

        info_label = QLabel(
            f"Detected volume: {volume.name} ({volume.path})\n"
            f"Destination base: {Config.BASE_EXTERNAL_FOLDER}"
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

        self.eject_checkbox = QCheckBox("Eject SD card after copy")
        self.eject_checkbox.setChecked(should_eject)
        layout.addWidget(self.eject_checkbox)

        help_label = QLabel(
            "Date spec examples: TD, YD, YYYYMMDD, YYYYMMDD-YYYYMMDD, "
            "since:YYYYMMDD, since:last, L/L2/L3."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

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
            self.eject_checkbox.isChecked(),
        )


class CopySdProgressDialog(QDialog):
    def __init__(
        self,
        volume: PhotoVolume,
        dates: list,
        output_folder_base: list[str],
        should_eject: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Copy from SD")
        self.setModal(True)
        self.setMinimumWidth(520)

        self._worker = CopySdWorker(volume, dates, output_folder_base, should_eject)
        self._finished = False
        self._error_count = 0

        layout = QVBoxLayout(self)

        self.status_label = QLabel("Preparing copy...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: red;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.cancel_btn)

        self.ok_btn = QPushButton("OK")
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.ok_btn)

        layout.addLayout(btn_layout)

        self._worker.signals.status.connect(self._on_status)
        self._worker.signals.plan_ready.connect(self._on_plan_ready)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.finished.connect(self._on_finished)

    def start(self):
        QThreadPool.globalInstance().start(self._worker)

    def _on_status(self, message: str):
        self.status_label.setText(message)

    def _on_plan_ready(self, total: int):
        if total <= 0:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("0/0")
            return
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"0/{total}")

    def _on_progress(self, completed: int, total: int):
        if total <= 0:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("0/0")
            return
        self.progress_bar.setValue(completed)
        self.progress_bar.setFormat(f"{completed}/{total}")

    def _on_error(self, message: str):
        self._error_count += 1
        self.error_label.setText(f"Errors: {self._error_count}")
        self.error_label.show()
        logger.error(message)

    def _on_finished(self, copied: int, total: int, cancelled: bool, error_count: int):
        self._finished = True
        if total == 0:
            status = "No images found for the selected date(s)."
        elif cancelled:
            status = f"Copy cancelled ({copied}/{total} file(s) copied)."
        else:
            status = f"Copy complete. {copied} file(s) copied."
        if error_count:
            status += f" {error_count} error(s)."
        self.status_label.setText(status)
        self.progress_bar.setValue(min(copied, total) if total else 0)
        self.cancel_btn.setEnabled(False)
        self.ok_btn.setEnabled(True)

    def _on_cancel(self):
        if self._finished:
            self.accept()
            return
        self.status_label.setText("Cancelling...")
        self.cancel_btn.setEnabled(False)
        self._worker.request_cancel()

    def closeEvent(self, event):
        if not self._finished:
            self._on_cancel()
            event.ignore()
            return
        super().closeEvent(event)


def _confirm_copy(
    parent, volume: PhotoVolume, dates: list, output_folder_base: list[str]
):
    text_folder = ", ".join(output_folder_base)
    text_date = ", ".join([date_to_str(d) for d in dates])
    confirm_text = (
        f"The images will be copied from : {volume.name} to {text_folder} "
        f"(dates: {text_date})\nConfirm?"
    )
    result = QMessageBox.question(
        parent,
        "Copy from SD",
        confirm_text,
        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
    )
    return result == QMessageBox.StandardButton.Ok


def launch_copy_sd(parent=None):
    if hasattr(Config, "SDCARD_NAMES"):
        volume = get_volume(Config.SDCARD_NAMES)
    else:
        volume = get_sd_volume()
    if not volume:
        QMessageBox.warning(
            parent, "Copy from SD", "No relevant SD card. Volume not renamed?"
        )
        return

    output_parent_folder = Config.BASE_EXTERNAL_FOLDER
    if not output_parent_folder:
        QMessageBox.critical(
            parent,
            "Copy from SD",
            "BASE_EXTERNAL_FOLDER is not configured.",
        )
        return

    try:
        os.makedirs(output_parent_folder, exist_ok=True)
    except OSError as exc:
        QMessageBox.critical(
            parent,
            "Copy from SD",
            f"Cannot access output folder: {output_parent_folder}\n{exc}",
        )
        return

    # TODO save last value in state after the copy
    name = Config.COPY_SD_DEFAULT_NAME
    date_spec = Config.COPY_SD_DATE_SPEC
    should_eject = True

    while True:
        dialog = CopySdInputDialog(
            volume,
            parent=parent,
            name=name,
            date_spec=date_spec,
            should_eject=should_eject,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        name, date_spec, should_eject = dialog.get_values()

        try:
            dates = to_dates(date_spec, volume)
        except ValueError:
            QMessageBox.warning(
                parent, "Copy from SD", "Invalid date spec. Please try again."
            )
            continue

        if not dates:
            QMessageBox.information(
                parent,
                "Copy from SD",
                "No image found: Is the SD card inserted and mounted?",
            )
            continue

        if not isinstance(dates, list):
            dates = [dates]
        dates = _sort_dates(dates)
        break

    output_folder_base = [
        dirname_with_date(output_parent_folder, name, f_date) for f_date in dates
    ]

    if not _confirm_copy(parent, volume, dates, output_folder_base):
        logger.warning("Aborted by user")
        return

    progress_dialog = CopySdProgressDialog(
        volume, dates, output_folder_base, should_eject, parent=parent
    )
    progress_dialog.start()
    progress_dialog.exec()
