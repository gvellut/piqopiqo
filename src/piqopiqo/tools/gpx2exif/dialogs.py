"""Dialogs for GPX workflows."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto
import html
import os

from PySide6.QtCore import QThreadPool, Signal
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
    QPushButton,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.tools.tool_flow import (
    ToolButton,
    ToolFlowDialog,
    ToolScreen,
    ToolTaskHandle,
    ToolWorkflow,
    sync_dialog_size_to_content,
)

from .constants import (
    NOT_SET_TIME_SHIFT_LABEL,
)
from .gpx_processing import to_relative_folder
from .ocr_time_shift import get_time_shift_ocr_provider_display_name
from .service import ApplyGpxResult
from .time_shift import is_valid_time_shift

_INVALID_STYLE = "border: 1px solid red;"
_DETAILS_TEXT_HEIGHT = 140
_DETAILS_WARNING_STYLE = "color: #b00020;"


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
        sync_dialog_size_to_content(self, sizing="fixed")


class ExtractGpsTimeShiftProgressDialog(ToolFlowDialog):
    """Modal progress/result dialog for OCR time-shift extraction."""

    def __init__(self, parent=None):
        self._worker = None
        self._result_shift: str | None = None
        workflow = ToolWorkflow(
            initial_screen="running",
            screens={
                "running": ToolScreen(
                    id="running",
                    title="Extract GPS Time shift",
                    buttons=(
                        ToolButton("cancel", "Cancel"),
                        ToolButton("ok", "OK", enabled=False, visible=False),
                    ),
                    min_width=460,
                    show_progress=True,
                    show_progress_count=False,
                ),
                "result": ToolScreen(
                    id="result",
                    title="Extract GPS Time shift",
                    build=lambda dialog: dialog._build_body(),
                    buttons=(
                        ToolButton("cancel", "Cancel", visible=False),
                        ToolButton(
                            "ok", "OK", enabled=True, visible=True, default=True
                        ),
                    ),
                    min_width=460,
                ),
            },
            transitions={
                ("running", "cancel"): lambda dialog, event: dialog._on_cancel(),
                ("result", "ok"): lambda dialog, event: dialog.accept(),
                ("*", "worker_success"): lambda dialog, event: dialog._on_success(
                    *event.args
                ),
                ("*", "worker_error"): lambda dialog, event: dialog._on_error(
                    *event.args
                ),
            },
        )
        super().__init__(workflow, parent=parent)
        provider_name = get_time_shift_ocr_provider_display_name()
        self.set_status(f"Extracting clock time with {provider_name}...")
        self.progress_bar.setRange(0, 0)

    @property
    def result_shift(self) -> str | None:
        return self._result_shift

    def transition_to(self, screen_id: str) -> None:
        super().transition_to(screen_id)
        self.cancel_btn = self.button("cancel")
        self.ok_btn = self.button("ok")

    def _build_body(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)

        self.result_label = QLabel("", widget)
        self.result_label.setWordWrap(True)
        self.result_label.hide()
        layout.addWidget(self.result_label)

        return widget

    def start(self, worker) -> None:
        self._worker = worker
        self.start_task(
            "extract_time_shift",
            ToolTaskHandle.from_qrunnable(
                worker=worker,
                pool=QThreadPool.globalInstance(),
                signal_map={
                    worker.signals.finished: "worker_success",
                    worker.signals.error: "worker_error",
                },
            ),
        )

    def _on_success(self, extracted_clock: str, time_shift: str) -> None:
        self._result_shift = time_shift
        self.transition_to("result")
        self.result_label.setStyleSheet("")
        self.result_label.setText(
            f"Extracted clock: {extracted_clock}\nComputed time shift: {time_shift}"
        )
        self.result_label.show()
        self.ok_btn.setFocus()
        self.sync_size_to_content()

    def _on_error(self, message: str) -> None:
        self._result_shift = None
        self.transition_to("result")
        self.result_label.setStyleSheet("color: red;")
        self.result_label.setText(message)
        self.result_label.show()
        self.ok_btn.setFocus()
        self.sync_size_to_content()

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self.stop_task("extract_time_shift", cancel=True)
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
        initial_gpx_path: str,
        kml_folder: str,
        last_gpx_folder: str = "",
        on_browse_selected_folder: Callable[[str], None] | None = None,
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
        self._last_gpx_folder = str(last_gpx_folder).strip()
        self._on_browse_selected_folder = on_browse_selected_folder

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
        self.mode_combo.addItem("Update metadata", ApplyGpxMode.UPDATE_DB)
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
            self.kml_warning.show()
        else:
            self.kml_warning.hide()
        layout.addWidget(self.kml_warning)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.gpx_path_edit.setText(str(initial_gpx_path).strip())
        self._update_ok_enabled()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        sync_dialog_size_to_content(self, sizing="fixed")

    def _resolve_browse_start_dir(self) -> str:
        current_value = self.gpx_path_edit.text().strip()
        if current_value:
            return self._resolve_browse_folder(current_value)
        return self._resolve_browse_folder(self._last_gpx_folder)

    def _resolve_browse_folder(self, value: str) -> str:
        path = str(value).strip()
        if not path:
            return ""
        expanded = os.path.expanduser(path)
        if os.path.isdir(expanded):
            return expanded
        parent = os.path.dirname(expanded)
        if parent and os.path.isdir(parent):
            return parent
        return ""

    def _browse_gpx(self) -> None:
        start_dir = self._resolve_browse_start_dir()
        value, _ = QFileDialog.getOpenFileName(
            self,
            "Select GPX file",
            start_dir,
            "GPX Files (*.gpx);;All Files (*)",
        )
        if value:
            self.gpx_path_edit.setText(value)
            if self._on_browse_selected_folder is not None:
                self._on_browse_selected_folder(self._resolve_browse_folder(value))

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


class ApplyGpxProgressDialog(ToolFlowDialog):
    """Progress and completion dialog for Apply GPX."""

    cancel_requested = Signal()

    def __init__(self, *, total: int, parent=None):
        self._kml_paths: list[str] = []
        self._total = max(0, int(total))
        workflow = ToolWorkflow(
            initial_screen="main",
            screens={
                "main": ToolScreen(
                    id="main",
                    title="Apply GPX",
                    build=lambda dialog: dialog._build_body(),
                    buttons=(
                        ToolButton("cancel", "Cancel"),
                        ToolButton("show_finder", "Show in Finder", visible=False),
                        ToolButton("ok", "OK", enabled=False),
                    ),
                    min_width=620,
                    show_progress=True,
                    show_progress_count=False,
                ),
            },
            transitions={
                ("main", "cancel"): lambda dialog, event: dialog._on_cancel(),
                ("main", "show_finder"): lambda dialog, event: dialog._on_show_finder(),
                ("main", "ok"): lambda dialog, event: dialog.accept(),
            },
        )
        super().__init__(workflow, parent=parent)
        self.set_status("Applying GPX...")
        self.progress_bar.setRange(0, self._total)
        self.progress_bar.setValue(0)
        self.sync_size_to_content()

    def transition_to(self, screen_id: str) -> None:
        super().transition_to(screen_id)
        self.cancel_btn = self.button("cancel")
        self.show_finder_btn = self.button("show_finder")
        self.ok_btn = self.button("ok")

    def _build_body(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)

        self.no_match_warning_row = QWidget(widget)
        warning_layout = QHBoxLayout(self.no_match_warning_row)
        warning_layout.setContentsMargins(0, 0, 0, 0)
        warning_layout.setSpacing(8)

        self.no_match_warning_icon = QLabel(self.no_match_warning_row)
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        self.no_match_warning_icon.setPixmap(icon.pixmap(24, 24))
        warning_layout.addWidget(self.no_match_warning_icon)

        self.no_match_warning_label = QLabel(
            "The GPX did not match any image",
            self.no_match_warning_row,
        )
        self.no_match_warning_label.setWordWrap(True)
        warning_layout.addWidget(self.no_match_warning_label, 1)
        self.no_match_warning_row.hide()
        layout.addWidget(self.no_match_warning_row)

        self.folder_label = QLabel("", widget)
        self.folder_label.setWordWrap(True)
        self.folder_label.hide()
        layout.addWidget(self.folder_label)

        self.details_text = QTextEdit(widget)
        self.details_text.setReadOnly(True)
        self.details_text.hide()
        layout.addWidget(self.details_text)

        return widget

    def set_folder(self, relative_folder: str) -> None:
        text = str(relative_folder).strip()
        if not text:
            self.folder_label.clear()
            self.folder_label.hide()
            self.sync_size_to_content()
            return
        self.folder_label.setText(f"Folder: {text}")
        self.folder_label.show()
        self.sync_size_to_content()

    def set_progress(self, completed: int, total: int) -> None:
        self._total = max(0, int(total))
        super().set_progress(completed, total)

    def finish(self, result: ApplyGpxResult) -> None:
        self.cancel_btn.setEnabled(False)
        self._kml_paths = list(result.kml_paths)

        if not result.cancelled and result.matched <= 0 and not self._kml_paths:
            self.configure_progress(visible=False)
            self.folder_label.clear()
            self.folder_label.hide()
            self.details_text.clear()
            self.details_text.hide()
            self.no_match_warning_row.show()
            self.show_finder_btn.setVisible(False)
            self.show_finder_btn.setEnabled(False)
            self.ok_btn.setEnabled(True)
            self.ok_btn.setDefault(True)
            self.ok_btn.setFocus()
            self.sync_size_to_content()
            return

        self.no_match_warning_row.hide()
        summary = f"Processed {result.processed} photo(s)."
        if result.cancelled:
            summary = f"Cancelled. {result.processed} photo(s) processed."
        self.set_status(f"{summary}\nGeoreferenced: {result.matched} / {self._total}")
        self.progress_bar.hide()

        details_html = self._build_details_html(result)
        if details_html:
            self.details_text.setHtml(details_html)
            self.details_text.setFixedHeight(_DETAILS_TEXT_HEIGHT)
            self.details_text.show()

        if self._kml_paths:
            self.show_finder_btn.setVisible(True)
            self.show_finder_btn.setEnabled(True)

        self.ok_btn.setEnabled(True)
        self.ok_btn.setDefault(True)
        self.ok_btn.setFocus()
        self.sync_size_to_content()

    def _build_details_html(self, result: ApplyGpxResult) -> str:
        sections: list[str] = []
        if result.kml_paths:
            lines = ["KML output:", *result.kml_paths]
            sections.append(self._html_lines(lines))

        if result.errors:
            lines = ["Errors:", *result.errors]
            sections.append(self._html_lines(lines))

        if result.unmatched_photos:
            lines = ["Images without georeferencing:"]
            lines.extend(
                f"{photo.name} - {photo.datetime_display}"
                for photo in result.unmatched_photos
            )
            sections.append(
                f'<div style="{_DETAILS_WARNING_STYLE}">{self._html_lines(lines)}</div>'
            )

        return "<br/>".join(sections)

    def _html_lines(self, lines: list[str]) -> str:
        return "".join(
            f"<div>{html.escape(str(line)) if str(line) else '&nbsp;'}</div>"
            for line in lines
        )

    def show_error(self, message: str) -> None:
        self.cancel_btn.setEnabled(False)
        self.no_match_warning_row.hide()
        self.set_status("Apply GPX failed:")
        self.details_text.setPlainText(message)
        self.details_text.setFixedHeight(_DETAILS_TEXT_HEIGHT)
        self.details_text.show()
        self.ok_btn.setEnabled(True)
        self.ok_btn.setDefault(True)
        self.ok_btn.setFocus()
        self.sync_size_to_content()

    def _on_cancel(self) -> None:
        self.cancel_requested.emit()
        self.reject()

    def _on_show_finder(self) -> None:
        if not self._kml_paths:
            return
        import showinfm

        showinfm.show_in_file_manager(self._kml_paths)


class ClearGpsProgressDialog(ToolFlowDialog):
    """Progress dialog for clearing GPS coordinates."""

    cancel_requested = Signal()

    def __init__(self, *, total: int, parent=None):
        self._total = max(0, int(total))
        workflow = ToolWorkflow(
            initial_screen="main",
            screens={
                "main": ToolScreen(
                    id="main",
                    title="Clear GPS",
                    build=lambda dialog: dialog._build_body(),
                    buttons=(
                        ToolButton("cancel", "Cancel"),
                        ToolButton("ok", "OK", enabled=False),
                    ),
                    min_width=520,
                    show_progress=True,
                    show_progress_count=False,
                )
            },
            transitions={
                ("main", "cancel"): lambda dialog, event: dialog._on_cancel(),
                ("main", "ok"): lambda dialog, event: dialog.accept(),
            },
        )
        super().__init__(workflow, parent=parent)
        self.cancel_btn = self.button("cancel")
        self.ok_btn = self.button("ok")
        self.set_status("Clearing GPS coordinates...")
        self.progress_bar.setRange(0, self._total)
        self.progress_bar.setValue(0)
        self.sync_size_to_content()

    def _build_body(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        self.details_text = QTextEdit(widget)
        self.details_text.setReadOnly(True)
        self.details_text.hide()
        layout.addWidget(self.details_text)
        return widget

    def finish(self, *, processed: int, total: int, cancelled: bool) -> None:
        if cancelled:
            self.set_status(
                f"Clear GPS cancelled. {processed}/{total} photo(s) processed."
            )
        else:
            self.set_status(
                f"Clear GPS complete. {processed}/{total} photo(s) processed."
            )
        self.cancel_btn.setEnabled(False)
        self.ok_btn.setEnabled(True)
        self.ok_btn.setDefault(True)
        self.ok_btn.setFocus()
        self.sync_size_to_content()

    def show_error(self, message: str) -> None:
        self.set_status("Clear GPS failed:")
        self.details_text.setPlainText(message)
        self.details_text.setFixedHeight(140)
        self.details_text.show()
        self.cancel_btn.setEnabled(False)
        self.ok_btn.setEnabled(True)
        self.ok_btn.setDefault(True)
        self.ok_btn.setFocus()
        self.sync_size_to_content()

    def _on_cancel(self) -> None:
        self.cancel_requested.emit()
        self.reject()
