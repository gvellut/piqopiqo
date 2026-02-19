"""Dialogs for GPX workflows."""

from __future__ import annotations

from enum import Enum, auto
import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .constants import (
    NOT_SET_TIME_SHIFT_LABEL,
)
from .gpx_processing import to_relative_folder
from .service import ApplyGpxResult
from .time_shift import is_valid_time_shift

_INVALID_STYLE = "border: 1px solid red;"


class ApplyGpxMode(Enum):
    ONLY_KML = auto()
    UPDATE_DB = auto()


class _TimeShiftEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.textChanged.connect(self._validate)
        self._is_valid = True

    def _validate(self) -> None:
        text = self.text().strip()
        valid = (not text) or is_valid_time_shift(text)
        self._is_valid = valid
        self.setStyleSheet("" if valid else _INVALID_STYLE)

    def is_valid(self) -> bool:
        return self._is_valid


class ExtractGpsTimeShiftConfirmDialog(QDialog):
    def __init__(
        self,
        *,
        folder_label: str,
        existing_shift: str | None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Extract GPS Time shift")
        self.setModal(True)

        layout = QVBoxLayout(self)
        value = existing_shift or NOT_SET_TIME_SHIFT_LABEL
        warning = ""
        if existing_shift:
            warning = "\n\nWarning: existing time shift will be replaced."

        label = QLabel(
            f"Folder: {folder_label}\n"
            f"Current value: {value}"
            f"{warning}\n\n"
            "Extract time shift from the selected photo?"
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.setFixedSize(self.size())


class ExtractGpsTimeShiftProgressDialog(QDialog):
    """Modal progress/result dialog for OCR time-shift extraction."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Extract GPS Time shift")
        self.setModal(True)
        self.setMinimumWidth(460)

        self._worker = None
        self._result_shift: str | None = None

        layout = QVBoxLayout(self)

        self.status_label = QLabel("Extracting clock time with Google Cloud Vision...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.hide()
        layout.addWidget(self.result_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        buttons.addWidget(self.cancel_btn)

        self.ok_btn = QPushButton("OK")
        self.ok_btn.setEnabled(False)
        self.ok_btn.hide()
        self.ok_btn.clicked.connect(self.accept)
        buttons.addWidget(self.ok_btn)

        layout.addLayout(buttons)

    @property
    def result_shift(self) -> str | None:
        return self._result_shift

    def start(self, worker) -> None:
        self._worker = worker
        worker.signals.finished.connect(self._on_success)
        worker.signals.error.connect(self._on_error)

        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().start(worker)

    def _on_success(self, time_shift: str) -> None:
        self._result_shift = time_shift
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.status_label.setText("Computed time shift:")
        self.result_label.setStyleSheet("")
        self.result_label.setText(time_shift)
        self.result_label.show()
        self.cancel_btn.hide()
        self.ok_btn.setEnabled(True)
        self.ok_btn.show()
        self.ok_btn.setFocus()
        self.adjustSize()

    def _on_error(self, message: str) -> None:
        self._result_shift = None
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.status_label.setText("Extraction failed:")
        self.result_label.setStyleSheet("color: red;")
        self.result_label.setText(message)
        self.result_label.show()
        self.cancel_btn.hide()
        self.ok_btn.setEnabled(True)
        self.ok_btn.show()
        self.ok_btn.setFocus()
        self.adjustSize()

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()
        self.reject()


class ApplyGpxDialog(QDialog):
    """Input dialog for GPX application settings."""

    def __init__(
        self,
        *,
        root_folder: str,
        source_folders: list[str],
        initial_time_shifts: dict[str, str],
        previous_time_shift_folders: set[str],
        kml_folder: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Apply GPX")
        self.setModal(True)
        self.setMinimumWidth(640)

        self._root_folder = root_folder
        self._source_folders = sorted(source_folders)
        self._initial_time_shifts = initial_time_shifts
        self._previous_time_shift_folders = previous_time_shift_folders
        self._time_shift_edits: dict[str, _TimeShiftEdit] = {}
        self._previous_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)

        shifts_group = QGroupBox("Folder time shifts")
        shifts_layout = QGridLayout(shifts_group)
        shifts_layout.setColumnStretch(0, 3)
        shifts_layout.setColumnStretch(1, 2)
        shifts_layout.addWidget(QLabel("Folder"), 0, 0)
        shifts_layout.addWidget(QLabel("Time shift"), 0, 1)
        shifts_layout.addWidget(QLabel(""), 0, 2)

        for row, folder in enumerate(self._source_folders, start=1):
            relative = to_relative_folder(self._root_folder, folder)
            shifts_layout.addWidget(QLabel(relative), row, 0)

            edit = _TimeShiftEdit(self)
            edit.setText(str(self._initial_time_shifts.get(folder, "")).strip())
            edit.textChanged.connect(self._update_ok_enabled)
            self._time_shift_edits[folder] = edit
            shifts_layout.addWidget(edit, row, 1)

            previous_label = QLabel("Previous", self)
            previous_label.setStyleSheet("color: red; font-size: 10px;")
            previous_label.setVisible(
                folder in self._previous_time_shift_folders
                and bool(edit.text().strip())
            )
            self._previous_labels[folder] = previous_label
            shifts_layout.addWidget(previous_label, row, 2)

        layout.addWidget(shifts_group)

        path_row = QWidget(self)
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(8)
        path_layout.addWidget(QLabel("GPX file", self))

        self.gpx_path_edit = QLineEdit(self)
        self.gpx_path_edit.textChanged.connect(self._update_ok_enabled)
        path_layout.addWidget(self.gpx_path_edit, 1)

        browse_btn = QPushButton("Browse", self)
        browse_btn.clicked.connect(self._browse_gpx)
        path_layout.addWidget(browse_btn)
        layout.addWidget(path_row)

        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("Only generate KML", ApplyGpxMode.ONLY_KML)
        self.mode_combo.addItem("Update images", ApplyGpxMode.UPDATE_DB)
        mode_row = QWidget(self)
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(8)
        mode_layout.addWidget(QLabel("Mode", self))
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch(1)
        layout.addWidget(mode_row)

        self.kml_warning = QLabel("")
        self.kml_warning.setWordWrap(True)
        if not kml_folder.strip():
            self.kml_warning.setStyleSheet("color: #aa5500;")
            self.kml_warning.setText(
                "KML folder is not set in Settings. KML will be written to the "
                "loaded photo root folder."
            )
        layout.addWidget(self.kml_warning)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_ok_enabled()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.setFixedSize(self.size())

    def _browse_gpx(self) -> None:
        value, _ = QFileDialog.getOpenFileName(
            self,
            "Select GPX file",
            self.gpx_path_edit.text().strip(),
            "GPX Files (*.gpx);;All Files (*)",
        )
        if value:
            self.gpx_path_edit.setText(value)

    def _update_ok_enabled(self) -> None:
        path = self.gpx_path_edit.text().strip()
        has_valid_path = bool(path) and os.path.isfile(path)
        has_valid_shifts = all(
            edit.is_valid() for edit in self._time_shift_edits.values()
        )
        self._ok_btn.setEnabled(has_valid_path and has_valid_shifts)

    def _on_accept(self) -> None:
        path = self.gpx_path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Apply GPX", "Select a GPX file.")
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Apply GPX", "GPX file does not exist.")
            return
        if not all(edit.is_valid() for edit in self._time_shift_edits.values()):
            QMessageBox.warning(
                self,
                "Apply GPX",
                "One or more time shifts are invalid.",
            )
            return
        self.accept()

    def get_values(self) -> tuple[str, ApplyGpxMode, dict[str, str]]:
        folder_shifts = {
            folder: edit.text().strip()
            for folder, edit in self._time_shift_edits.items()
        }
        return (
            self.gpx_path_edit.text().strip(),
            self.mode_combo.currentData(),
            folder_shifts,
        )


class ApplyGpxProgressDialog(QDialog):
    """Progress and completion dialog for Apply GPX."""

    cancel_requested = Signal()

    def __init__(self, *, total: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Apply GPX")
        self.setModal(True)
        self.setMinimumSize(620, 300)

        self._kml_paths: list[str] = []

        layout = QVBoxLayout(self)

        self.status_label = QLabel("Applying GPX...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.folder_label = QLabel("Folder: -")
        self.folder_label.setWordWrap(True)
        layout.addWidget(self.folder_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, max(0, int(total)))
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.hide()
        layout.addWidget(self.details_text, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        button_row.addWidget(self.cancel_btn)

        self.show_finder_btn = QPushButton("Show in Finder")
        self.show_finder_btn.clicked.connect(self._on_show_finder)
        self.show_finder_btn.hide()
        button_row.addWidget(self.show_finder_btn)

        self.ok_btn = QPushButton("OK")
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self.accept)
        button_row.addWidget(self.ok_btn)

        layout.addLayout(button_row)
        self.setFixedSize(620, 300)

    def set_folder(self, relative_folder: str) -> None:
        self.folder_label.setText(f"Folder: {relative_folder}")

    def set_progress(self, completed: int, total: int) -> None:
        self.progress_bar.setRange(0, max(0, int(total)))
        self.progress_bar.setValue(max(0, int(completed)))
        self.progress_bar.setFormat(f"{completed}/{total}")

    def finish(self, result: ApplyGpxResult) -> None:
        self.cancel_btn.setEnabled(False)

        summary = f"Processed {result.processed} photo(s)."
        if result.cancelled:
            summary = f"Cancelled. {result.processed} photo(s) processed."
        self.status_label.setText(summary)

        self._kml_paths = list(result.kml_paths)
        details_lines = []
        if result.kml_paths:
            details_lines.append("KML output:")
            details_lines.extend(result.kml_paths)
        if result.errors:
            details_lines.append("")
            details_lines.append("Errors:")
            details_lines.extend(result.errors)

        if details_lines:
            self.details_text.setPlainText("\n".join(details_lines))
            self.details_text.show()

        if self._kml_paths:
            self.show_finder_btn.show()
            self.show_finder_btn.setEnabled(True)

        self.ok_btn.setEnabled(True)
        self.ok_btn.setFocus()

    def show_error(self, message: str) -> None:
        self.cancel_btn.setEnabled(False)
        self.status_label.setText("Apply GPX failed:")
        self.details_text.setPlainText(message)
        self.details_text.show()
        self.ok_btn.setEnabled(True)
        self.ok_btn.setFocus()

    def _on_cancel(self) -> None:
        self.cancel_requested.emit()
        self.reject()

    def _on_show_finder(self) -> None:
        if not self._kml_paths:
            return
        import showinfm

        showinfm.show_in_file_manager(self._kml_paths)
