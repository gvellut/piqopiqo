"""Archive workflow for moving the current root folder to a configured location."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.cache_paths import (
    clear_metadata_cache_for_folders,
    clear_thumb_cache_for_folders,
)
from piqopiqo.dialogs.settings_redirect import (
    prompt_open_settings_for_missing_setting,
)
from piqopiqo.metadata.exif_write import build_exif_tags
from piqopiqo.model import ImageItem
from piqopiqo.qt_workers import PythonOwnedRunnable
from piqopiqo.ssf.settings_state import (
    StateKey,
    UserSettingKey,
    get_state,
    get_state_value,
    get_user_setting,
)
from piqopiqo.tools.tool_flow import (
    ToolButton,
    ToolFlowDialog,
    ToolScreen,
    ToolTaskHandle,
    ToolWorkflow,
)

if TYPE_CHECKING:
    from piqopiqo.folder_watcher import WorkspaceWatcherController
    from piqopiqo.main_window import MainWindow


@dataclass(frozen=True)
class ArchiveDestinationValidation:
    archive_path: str | None = None
    settings_message: str | None = None
    conflict_message: str | None = None


@dataclass(frozen=True)
class ArchiveMoveResult:
    success: bool
    archive_path: str
    move_error: str = ""
    cleanup_error: str = ""
    source_exists_after_failure: bool = False


class ArchiveMoveWorkerSignals(QObject):
    finished = Signal(object)  # ArchiveMoveResult


class ArchiveMoveWorker(PythonOwnedRunnable):
    def __init__(
        self,
        *,
        root_folder: str,
        archive_path: str,
        source_folders: list[str],
    ) -> None:
        super().__init__()
        self._root_folder = str(root_folder)
        self._archive_path = str(archive_path)
        self._source_folders = list(source_folders)
        self.signals = ArchiveMoveWorkerSignals()

    def run(self) -> None:
        cleanup_error = ""
        try:
            shutil.move(self._root_folder, self._archive_path)
        except Exception as exc:
            self.signals.finished.emit(
                ArchiveMoveResult(
                    success=False,
                    archive_path=self._archive_path,
                    move_error=str(exc),
                    source_exists_after_failure=os.path.isdir(self._root_folder),
                )
            )
            return

        try:
            clear_metadata_cache_for_folders(self._source_folders)
            clear_thumb_cache_for_folders(self._source_folders)
        except Exception as exc:
            cleanup_error = str(exc)

        self.signals.finished.emit(
            ArchiveMoveResult(
                success=True,
                archive_path=self._archive_path,
                cleanup_error=cleanup_error,
            )
        )


def validate_archive_destination(
    root_folder: str,
    destination: str,
) -> ArchiveDestinationValidation:
    root_path = os.path.realpath(os.path.abspath(str(root_folder).strip()))
    destination_text = str(destination or "").strip()
    if not destination_text:
        return ArchiveDestinationValidation(
            settings_message=(
                "Archive destination is not configured. Set it in "
                "Settings > External/Tools > Archive."
            )
        )

    destination_path = os.path.realpath(
        os.path.abspath(os.path.expanduser(destination_text))
    )
    if not os.path.isdir(destination_path):
        return ArchiveDestinationValidation(
            settings_message=(
                "Archive destination is not available.\n\n"
                f"{destination_path}\n\n"
                "Update it in Settings > External/Tools > Archive."
            )
        )

    if destination_path == root_path:
        return ArchiveDestinationValidation(
            settings_message=(
                "Archive destination must be different from the current folder.\n\n"
                "Update it in Settings > External/Tools > Archive."
            )
        )

    try:
        common_path = os.path.commonpath([destination_path, root_path])
    except ValueError:
        common_path = ""

    if common_path == root_path:
        return ArchiveDestinationValidation(
            settings_message=(
                "Archive destination must be outside the current folder.\n\n"
                "Update it in Settings > External/Tools > Archive."
            )
        )

    root_name = Path(root_path).name
    archive_path = os.path.join(destination_path, root_name)
    if os.path.exists(archive_path):
        return ArchiveDestinationValidation(
            conflict_message=(
                "Archive destination already contains a folder with the same name.\n\n"
                f"{archive_path}"
            )
        )

    return ArchiveDestinationValidation(archive_path=archive_path)


def launch_archive(window: MainWindow) -> None:
    root_folder = str(window.root_folder or "").strip()
    if not root_folder:
        QMessageBox.information(
            window,
            "Archive",
            "No folder is currently loaded.",
        )
        return

    if not os.path.isdir(root_folder):
        QMessageBox.warning(
            window,
            "Archive",
            "The current folder is no longer available.",
        )
        return

    validation = validate_archive_destination(
        root_folder,
        str(get_user_setting(UserSettingKey.ARCHIVE_DESTINATION) or ""),
    )
    if validation.settings_message:
        should_open_settings = prompt_open_settings_for_missing_setting(
            window,
            title="Archive",
            text=validation.settings_message,
        )
        if should_open_settings:
            window.open_settings_for_key(UserSettingKey.ARCHIVE_DESTINATION)
        return

    if validation.conflict_message:
        QMessageBox.warning(window, "Archive", validation.conflict_message)
        return

    archive_path = str(validation.archive_path or "").strip()
    if not archive_path:
        QMessageBox.warning(window, "Archive", "Could not resolve the archive path.")
        return

    dialog = ArchiveDialog(
        window,
        root_folder=root_folder,
        archive_path=archive_path,
        items=list(window.photo_model.all_photos),
        source_folders=list(window.photo_model.source_folders),
        watcher_control=window.workspace_watcher_control,
        parent=window,
    )
    dialog.exec()


class ArchiveDialog(ToolFlowDialog):
    """Confirmation and progress dialog for archiving the current folder."""

    def __init__(
        self,
        window: MainWindow,
        *,
        root_folder: str,
        archive_path: str,
        items: list[ImageItem],
        source_folders: list[str],
        watcher_control: WorkspaceWatcherController | None = None,
        parent=None,
    ) -> None:
        self._window = window
        self._root_folder = str(root_folder)
        self._archive_path = str(archive_path)
        self._items = list(items)
        self._source_folders = list(source_folders)
        self._watcher_control = watcher_control
        self._watcher_suspended = False
        self._media_manager = window.media_manager
        self._move_worker: ArchiveMoveWorker | None = None
        self._running = False
        self._running_stage: str | None = None
        self._finished = False
        self._write_error_count = 0
        self._write_errors: list[str] = []

        workflow = ToolWorkflow(
            initial_screen="confirm",
            screens={
                "confirm": ToolScreen(
                    id="confirm",
                    title="Archive",
                    build=lambda dialog: dialog._build_body(),
                    buttons=(
                        ToolButton("cancel", "Cancel"),
                        ToolButton("ok", "OK", default=True),
                    ),
                    min_width=560,
                    preserve_width=True,
                ),
                "exif": ToolScreen(
                    id="exif",
                    title="Archive",
                    build=lambda dialog: dialog._build_body(),
                    buttons=(
                        ToolButton("cancel", "Cancel", visible=False),
                        ToolButton("ok", "Cancel", default=True),
                    ),
                    min_width=560,
                    preserve_width=True,
                    show_progress=True,
                ),
                "move": ToolScreen(
                    id="move",
                    title="Archive",
                    build=lambda dialog: dialog._build_body(),
                    buttons=(
                        ToolButton("cancel", "Cancel", visible=False),
                        ToolButton("ok", "OK", enabled=False, default=True),
                    ),
                    min_width=560,
                    preserve_width=True,
                    show_progress=True,
                    show_progress_count=False,
                ),
                "result": ToolScreen(
                    id="result",
                    title="Archive",
                    build=lambda dialog: dialog._build_body(),
                    buttons=(
                        ToolButton("cancel", "Cancel", visible=False),
                        ToolButton("ok", "OK", default=True),
                    ),
                    min_width=560,
                    preserve_width=True,
                ),
            },
            transitions={
                ("confirm", "ok"): lambda dialog, event: dialog._on_ok_clicked(),
                ("confirm", "cancel"): lambda dialog, event: dialog.reject(),
                ("exif", "ok"): lambda dialog, event: dialog._on_ok_clicked(),
                ("move", "ok"): lambda dialog, event: dialog._on_ok_clicked(),
                ("result", "ok"): lambda dialog, event: dialog._on_ok_clicked(),
                ("*", "write_progress"): lambda dialog, event: (
                    dialog._on_write_progress(*event.args)
                ),
                ("*", "write_file_completed"): (
                    lambda dialog, event: dialog._on_write_file_completed(*event.args)
                ),
                ("*", "write_all_completed"): (
                    lambda dialog, event: dialog._on_write_all_completed()
                ),
                ("*", "move_finished"): lambda dialog, event: dialog._on_move_finished(
                    *event.args
                ),
            },
        )
        super().__init__(workflow, parent=parent)
        self._update_confirmation_text()
        self.sync_size_to_content()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._focus_ok_button)

    def transition_to(self, screen_id: str) -> None:
        super().transition_to(screen_id)
        self.progress_header_widget = self.progress_row
        self.progress_stage_label = self.status_label
        self.cancel_btn = self.button("cancel")
        self.ok_btn = self.button("ok")

    def _build_body(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)

        self.summary_label = QLabel(widget)
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.summary_label)

        self.save_exif_checkbox = QCheckBox("Save EXIF before archive", widget)
        self.save_exif_checkbox.setChecked(
            bool(get_state_value(StateKey.ARCHIVE_SAVE_EXIF))
        )
        layout.addWidget(self.save_exif_checkbox)

        self.error_label = QLabel(widget)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: red;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.details_text = QTextEdit(widget)
        self.details_text.setReadOnly(True)
        self.details_text.hide()
        layout.addWidget(self.details_text)

        return widget

    def _focus_ok_button(self) -> None:
        if not self.ok_btn.isEnabled() or not self.ok_btn.isVisible():
            return
        self.ok_btn.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.ok_btn.setDefault(True)

    def _update_confirmation_text(self) -> None:
        item_count = len(self._items)
        # archive path contains also the name of the current folder
        destination_folder = str(Path(self._archive_path).parent)
        self.summary_label.setText(
            "This will move the loaded root folder and all of its contents.\n\n"
            f"Folder:\n{self._root_folder}\n\n"
            f"Destination:\n{destination_folder}\n\n"
            f"Photo count: {item_count}\n\n"
            "Thumbnail cache and metadata DB cache for the loaded folders will be "
            "deleted after the move."
        )

    def _on_ok_clicked(self) -> None:
        if self._running:
            if self._running_stage == "exif":
                self._cancel_exif_stage()
            return
        if self._finished:
            self.accept()
            return
        self._start_archive()

    def _start_archive(self) -> None:
        save_exif = bool(self.save_exif_checkbox.isChecked())
        get_state().set(StateKey.ARCHIVE_SAVE_EXIF, save_exif)

        if save_exif and self._items:
            if not self._window.db_manager.ensure_items_metadata_ready(self._items):
                QMessageBox.warning(
                    self,
                    "Archive",
                    "Metadata is still loading. Wait for loading to finish before "
                    "saving EXIF and archiving.",
                )
                return

            items_with_tags = [
                (item.path, build_exif_tags(item.db_metadata))
                for item in self._items
                if item.db_metadata
            ]
            if items_with_tags:
                self._start_exif_stage(items_with_tags)
                return

        self._start_move_stage()

    def _set_running_ui(self, *, text: str) -> None:
        self._running = True
        self._running_stage = "move"
        self.transition_to("move")
        self.error_label.hide()
        self.details_text.hide()
        self.details_text.clear()
        self.summary_label.hide()
        self.progress_stage_label.setText(text)
        self.progress_count_label.hide()
        self.progress_count_label.clear()
        self.save_exif_checkbox.setEnabled(False)
        self.save_exif_checkbox.hide()
        self.ok_btn.setEnabled(False)
        self.progress_bar.show()
        self.sync_size_to_content()

    def _set_exif_running_ui(self, total: int) -> None:
        self._running = True
        self._running_stage = "exif"
        self.transition_to("exif")
        self.error_label.hide()
        self.details_text.hide()
        self.details_text.clear()
        self.summary_label.hide()
        self.progress_stage_label.setText("Saving EXIF metadata before archive...")
        self.save_exif_checkbox.setEnabled(False)
        self.save_exif_checkbox.hide()
        self.ok_btn.setEnabled(True)
        self.ok_btn.setDefault(True)
        self._update_progress_count(0, total)
        self.sync_size_to_content()

    def _update_progress_count(self, completed: int, total: int) -> None:
        total_value = max(0, int(total))
        completed_value = max(0, min(int(completed), total_value))
        if total_value <= 0:
            self.progress_count_label.clear()
            self.progress_count_label.hide()
            return
        self.progress_count_label.setText(f"{completed_value}/{total_value}")
        self.progress_count_label.show()

    def _suspend_watcher_for_exif(self) -> None:
        if self._watcher_control is None or self._watcher_suspended:
            return
        self._watcher_control.suspend()
        self._watcher_suspended = True

    def _resume_watcher_after_exif_stop(self) -> None:
        if self._watcher_control is None or not self._watcher_suspended:
            return
        self._watcher_control.resume_and_refresh()
        self._watcher_suspended = False

    def _start_exif_stage(self, items_with_tags: list[tuple[str, dict]]) -> None:
        self._write_error_count = 0
        self._write_errors = []
        self._suspend_watcher_for_exif()
        self._set_exif_running_ui(len(items_with_tags))
        self.set_progress(0, len(items_with_tags))
        self.start_task(
            "archive_write_exif",
            ToolTaskHandle.from_signals(
                start_fn=lambda: self._media_manager.write_exif(items_with_tags),
                cancel_fn=self._media_manager.stop_write,
                signal_map={
                    self._media_manager.write_progress: "write_progress",
                    self._media_manager.write_file_completed: "write_file_completed",
                    self._media_manager.write_all_completed: "write_all_completed",
                },
            ),
        )

    def _disconnect_write_signals(self) -> None:
        self.stop_task("archive_write_exif", cancel=False)

    def _on_write_progress(self, completed: int, total: int) -> None:
        self.set_progress(completed, total)
        self._update_progress_count(completed, total)

    def _on_write_file_completed(
        self,
        file_path: str,
        success: bool,
        error_message: str,
    ) -> None:
        if success:
            return
        self._write_error_count += 1
        filename = os.path.basename(file_path)
        self._write_errors.append(f"{filename}: {error_message}")

    def _on_write_all_completed(self) -> None:
        self._disconnect_write_signals()
        if self._write_error_count > 0:
            self._resume_watcher_after_exif_stop()
            self._show_finished_result(
                text=(
                    "Archive stopped because saving EXIF failed. "
                    "The folder was not moved."
                ),
                error_text=f"EXIF save failed for {self._write_error_count} file(s).",
                details=self._write_errors,
            )
            return

        self._start_move_stage()

    def _cancel_exif_stage(self) -> None:
        if not self._running or self._running_stage != "exif":
            return
        self.stop_task("archive_write_exif", cancel=True)
        self._resume_watcher_after_exif_stop()
        self._show_finished_result(
            text="Archive cancelled. The folder was not moved.",
        )

    def _start_move_stage(self) -> None:
        try:
            self._window._prepare_workspace_for_archive_move()
        except Exception as exc:
            self._resume_watcher_after_exif_stop()
            self._show_finished_result(
                text="Archive could not start.",
                error_text=str(exc),
            )
            return

        self._watcher_suspended = False
        self._set_running_ui(text="Archiving folder...")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("")

        worker = ArchiveMoveWorker(
            root_folder=self._root_folder,
            archive_path=self._archive_path,
            source_folders=self._source_folders,
        )
        self._move_worker = worker
        self.start_task(
            "archive_move",
            ToolTaskHandle.from_qrunnable(
                worker=worker,
                pool=QThreadPool.globalInstance(),
                signal_map={worker.signals.finished: "move_finished"},
            ),
        )

    def _on_move_finished(self, result: object) -> None:
        if not isinstance(result, ArchiveMoveResult):
            self._show_finished_result(
                text="Archive failed.",
                error_text="Unexpected archive result.",
            )
            return

        if result.success:
            self._window._remove_recent_folder_from_history(self._root_folder)
            self._window._unload_workspace(clear_last_folder=True)
            error_text = ""
            details: list[str] | None = None
            if result.cleanup_error:
                error_text = "Archive completed with a cache cleanup warning."
                details = [result.cleanup_error]
            self._show_finished_result(
                text=f"Archive complete.\nMoved to:\n{result.archive_path}",
                error_text=error_text,
                details=details,
            )
            return

        if result.source_exists_after_failure:
            self._window._resume_workspace_after_archive_failure()

        details = None
        if result.move_error:
            details = [result.move_error]
        self._show_finished_result(
            text="Archive failed. The folder was not moved.",
            error_text=result.move_error or "Unknown archive error.",
            details=details,
        )

    def _show_finished_result(
        self,
        *,
        text: str,
        error_text: str = "",
        details: list[str] | None = None,
    ) -> None:
        self._running = False
        self._running_stage = None
        self._finished = True
        self.transition_to("result")
        self.summary_label.setText(text)
        self.summary_label.show()
        self.progress_header_widget.hide()
        self.progress_count_label.clear()
        self.progress_count_label.hide()
        self.progress_bar.hide()
        self.ok_btn.setEnabled(True)
        self.ok_btn.setFocus(Qt.FocusReason.OtherFocusReason)
        self.ok_btn.setDefault(True)
        self.save_exif_checkbox.hide()

        detail_lines = [line for line in (details or []) if str(line).strip()]
        if error_text.strip():
            self.error_label.setText(error_text.strip())
            self.error_label.show()
        else:
            self.error_label.hide()

        if detail_lines:
            self.details_text.setPlainText("\n".join(detail_lines))
            self.details_text.setFixedHeight(140)
            self.details_text.show()
        else:
            self.details_text.hide()

        self.sync_size_to_content()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._running:
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self) -> None:
        if self._running:
            return
        super().reject()
