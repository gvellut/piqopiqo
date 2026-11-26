"""Discover image-folder caches and delete only selected cache directories."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
from typing import TYPE_CHECKING

from attrs import define, field
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.cache_paths import (
    FOLDER_METADATA_SOURCE_PATH,
    get_cache_base_dir,
    get_cache_dir_for_folder,
)
from piqopiqo.components.ellided_label import EllidedLabel
from piqopiqo.components.summary_text_edit import SummaryTextEdit
from piqopiqo.dialogs.modal import managed_modal_dialog
from piqopiqo.qt_workers import PythonOwnedRunnable
from piqopiqo.ssf.settings_state import (
    RuntimeSettingKey,
    UserSettingKey,
    get_runtime_setting,
    get_user_setting,
)
from piqopiqo.tools.tool_flow import (
    ToolButton,
    ToolFlowDialog,
    ToolScreen,
    ToolTaskHandle,
    ToolWorkflow,
    sync_dialog_size_to_content,
)

if TYPE_CHECKING:
    from piqopiqo.main_window import MainWindow


@define(frozen=True)
class CacheFolder:
    source_folder: str
    cache_dirs: tuple[Path, ...]
    ignored: bool = False
    missing: bool = False


@define
class CacheScanResult:
    folders: list[CacheFolder] = field(factory=list)
    unidentified_count: int = 0
    error: str = ""


@define
class CacheCleanupResult:
    cleaned_folders: int = 0
    deleted_files: int = 0
    remaining_folders: int = 0
    errors: list[str] = field(factory=list)


def _cache_directories(cache_base: Path) -> list[Path]:
    """Exclude service data, such as Flickr credentials, and directory links."""
    if not cache_base.exists():
        return []
    with os.scandir(cache_base) as entries:
        return [
            Path(entry.path)
            for entry in entries
            if entry.is_dir(follow_symlinks=False)
            and (
                re.fullmatch(r"[0-9a-f]{32}", entry.name)
                or (Path(entry.path) / "db" / "metadata.db").is_file()
            )
        ]


def _read_source_folder(cache_dir: Path) -> str | None:
    db_path = cache_dir / "db" / "metadata.db"
    if db_path.parent.is_symlink() or db_path.is_symlink() or not db_path.is_file():
        return None
    # Discovery must not create, migrate, or modify older databases.
    with closing(
        sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    ) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "folder_metadata" in tables:
            row = connection.execute(
                "SELECT value FROM folder_metadata WHERE data = ?",
                (FOLDER_METADATA_SOURCE_PATH,),
            ).fetchone()
            if row and row[0] and os.path.isabs(row[0]):
                return os.path.normpath(row[0])
        for table in ("photo_metadata", "photo_exif_fields"):
            if table in tables:
                row = connection.execute(
                    f"SELECT file_path FROM {table} WHERE file_path != '' LIMIT 1"
                ).fetchone()
                if row and os.path.isabs(row[0]):
                    return os.path.dirname(row[0])
    return None


def scan_cache(
    cache_base: Path,
    favorite_folder: str,
    cancel_event: threading.Event | None = None,
) -> CacheScanResult:
    result = CacheScanResult()
    favorite = Path(favorite_folder).expanduser().resolve() if favorite_folder else None
    grouped: dict[str, list[Path]] = {}
    try:
        for cache_dir in _cache_directories(cache_base.resolve()):
            if cancel_event is not None and cancel_event.is_set():
                break
            try:
                source = _read_source_folder(cache_dir)
            except (OSError, sqlite3.Error, ValueError):
                source = None
            if source is None:
                result.unidentified_count += 1
                continue
            grouped.setdefault(source, []).append(cache_dir)
        for source, cache_dirs in sorted(grouped.items()):
            path = Path(source)
            exists = path.is_dir()
            ignored = bool(
                favorite is not None
                and exists
                and path.resolve().is_relative_to(favorite)
            )
            result.folders.append(
                CacheFolder(source, tuple(cache_dirs), ignored, not exists)
            )
        result.folders.sort(
            key=lambda folder: (
                folder.ignored,
                not folder.missing,
                folder.source_folder,
            )
        )
    except OSError as exc:
        result.error = str(exc)
    return result


def _count_files(directory: Path) -> int:
    count = 0

    def on_error(error: OSError) -> None:
        raise error

    for root, directories, files in os.walk(
        directory, followlinks=False, onerror=on_error
    ):
        count += len(files)
        count += sum((Path(root) / name).is_symlink() for name in directories)
    return count


def clean_cache(
    cache_base: Path,
    folders: list[CacheFolder],
    progress: Callable[[int, int, str], None],
) -> CacheCleanupResult:
    result = CacheCleanupResult()
    cache_base = cache_base.resolve()
    cleaned_sources: set[str] = set()
    for index, folder in enumerate(folders):
        progress(index, len(folders), folder.source_folder)
        for cache_dir in folder.cache_dirs:
            try:
                # Deletion targets come only from cache discovery, never source paths.
                # Reject links and paths outside the immediate cache directory.
                if (
                    cache_dir.parent != cache_base
                    or cache_dir.is_symlink()
                    or not cache_dir.is_dir()
                    or Path(folder.source_folder).resolve().is_relative_to(cache_dir)
                ):
                    raise ValueError("Cache directory is missing or unsafe to delete.")
                before = _count_files(cache_dir)
                failures: list[str] = []

                def on_error(
                    _function, _path, exc: BaseException, failures=failures
                ) -> None:
                    failures.append(str(exc))

                try:
                    shutil.rmtree(cache_dir, onexc=on_error)
                except OSError as exc:
                    failures.append(str(exc))
                after = _count_files(cache_dir) if cache_dir.exists() else 0
                deleted = max(0, before - after)
                result.deleted_files += deleted
                if deleted or not cache_dir.exists():
                    cleaned_sources.add(folder.source_folder)
                if failures:
                    result.errors.append(
                        f"{folder.source_folder}: {'; '.join(failures)}"
                    )
            except (OSError, ValueError) as exc:
                result.errors.append(f"{folder.source_folder}: {exc}")
        progress(index + 1, len(folders), folder.source_folder)
    result.cleaned_folders = len(cleaned_sources)
    try:
        result.remaining_folders = len(_cache_directories(cache_base))
    except OSError as exc:
        result.errors.append(f"Could not count remaining cache folders: {exc}")
    return result


class _CacheWorkerSignals(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)


class CacheScanWorker(PythonOwnedRunnable):
    def __init__(self, cache_base: Path, favorite_folder: str) -> None:
        super().__init__()
        self._cache_base = cache_base
        self._favorite_folder = favorite_folder
        self._cancel_event = threading.Event()
        self.signals = _CacheWorkerSignals()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            result = scan_cache(
                self._cache_base, self._favorite_folder, self._cancel_event
            )
        except Exception as exc:
            result = CacheScanResult(error=str(exc))
        self.signals.finished.emit(result)


class CacheCleanupWorker(PythonOwnedRunnable):
    def __init__(self, cache_base: Path, folders: list[CacheFolder]) -> None:
        super().__init__()
        self._cache_base = cache_base
        self._folders = folders
        self.signals = _CacheWorkerSignals()

    def run(self) -> None:
        try:
            result = clean_cache(
                self._cache_base, self._folders, self.signals.progress.emit
            )
        except Exception as exc:
            result = CacheCleanupResult(errors=[str(exc)])
        self.signals.finished.emit(result)


def confirm_cleanup(parent: QWidget, count: int) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Clean cache")
    layout = QVBoxLayout(dialog)
    message = QLabel(
        f"The cache for {count} folders will be deleted. Continue?", dialog
    )
    layout.addWidget(message)
    buttons = QHBoxLayout()
    buttons.addStretch()
    cancel_button = QPushButton("Cancel", dialog)
    cancel_button.clicked.connect(dialog.reject)
    buttons.addWidget(cancel_button)
    ok_button = QPushButton("OK", dialog)
    ok_button.clicked.connect(dialog.accept)
    ok_button.setDefault(True)
    buttons.addWidget(ok_button)
    layout.addLayout(buttons)
    sync_dialog_size_to_content(dialog)
    with managed_modal_dialog(dialog):
        return dialog.exec() == QDialog.DialogCode.Accepted


class CacheSelectionDialog(ToolFlowDialog):
    def __init__(self, cache_base: Path, favorite_folder: str, parent=None) -> None:
        self._cache_base = cache_base
        self._favorite_folder = favorite_folder
        self._scan = CacheScanResult()
        self._rows: list[tuple[QListWidgetItem, CacheFolder]] = []
        self._scan_started = False
        self.selected_folders: list[CacheFolder] = []
        width = int(get_runtime_setting(RuntimeSettingKey.CLEAN_CACHE_DIALOG_WIDTH))
        workflow = ToolWorkflow(
            initial_screen="scan",
            screens={
                "scan": ToolScreen(
                    id="scan",
                    title="Clean cache",
                    min_width=width,
                    buttons=(ToolButton("cancel", "Cancel"),),
                    show_progress=True,
                    show_progress_count=False,
                    close_policy="cancel",
                ),
                "select": ToolScreen(
                    id="select",
                    title="Clean cache",
                    min_width=width,
                    build=lambda dialog: dialog._build_selection(),
                    buttons=(ToolButton("cancel", "Cancel"), ToolButton("ok", "OK")),
                ),
            },
            transitions={
                ("*", "cancel"): lambda dialog, event: dialog.reject(),
                ("scan", "scanned"): lambda dialog, event: dialog._on_scanned(
                    *event.args
                ),
                ("select", "ok"): lambda dialog, event: dialog._on_ok(),
            },
        )
        super().__init__(workflow, parent=parent)
        self.setFixedWidth(width)
        self.set_status("Reading cache databases...")
        self.set_progress(0, 0)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._scan_started:
            self._scan_started = True
            self._worker = CacheScanWorker(self._cache_base, self._favorite_folder)
            self.start_task(
                "scan",
                ToolTaskHandle.from_qrunnable(
                    worker=self._worker,
                    signal_map={self._worker.signals.finished: "scanned"},
                ),
            )

    def _on_scanned(self, result: CacheScanResult) -> None:
        self.stop_task("scan", cancel=False)
        self._scan = result
        self.transition_to("select")
        self._update_ok()

    def _build_selection(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        description = QLabel(
            "Select image folders whose cached data should be deleted.\n"
            "Image folders are kept. The current workspace closes "
            "if its cache is selected.",
            widget,
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.folder_list = QListWidget(widget)
        self.folder_list.setTextElideMode(Qt.TextElideMode.ElideLeft)
        self.folder_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.folder_list.setUniformItemSizes(True)
        self.folder_list.itemChanged.connect(self._update_ok)
        layout.addWidget(self.folder_list)
        self._rows = []
        for folder in self._scan.folders:
            if not folder.ignored:
                self._add_folder(folder)

        controls = QHBoxLayout()
        self.check_all_button = QPushButton("Check all", widget)
        self.check_all_button.clicked.connect(lambda: self._check_all(True))
        controls.addWidget(self.check_all_button)
        self.uncheck_all_button = QPushButton("Uncheck all", widget)
        self.uncheck_all_button.clicked.connect(lambda: self._check_all(False))
        controls.addWidget(self.uncheck_all_button)
        controls.addStretch()
        self.include_ignored_button = QPushButton("Include ignored", widget)
        self.include_ignored_button.setEnabled(
            any(folder.ignored for folder in self._scan.folders)
        )
        self.include_ignored_button.clicked.connect(self._include_ignored)
        controls.addWidget(self.include_ignored_button)
        layout.addLayout(controls)

        notes: list[str] = []
        ignored_count = sum(folder.ignored for folder in self._scan.folders)
        if ignored_count:
            notes.append(
                f"{ignored_count} existing folders under Favorite are ignored."
            )
        if self._scan.unidentified_count:
            notes.append(
                f"{self._scan.unidentified_count} cache folders could not be "
                "identified and will be kept."
            )
        if self._scan.error:
            notes.append(f"Cache scan failed: {self._scan.error}")
        if not self._scan.folders and not notes:
            notes.append("No image-folder caches were found.")
        self.notes_label = QLabel("\n".join(notes), widget)
        self.notes_label.setTextFormat(Qt.TextFormat.PlainText)
        self.notes_label.setWordWrap(True)
        self.notes_label.setVisible(bool(notes))
        layout.addWidget(self.notes_label)
        self._size_list()
        return widget

    def _add_folder(self, folder: CacheFolder) -> None:
        text = folder.source_folder
        if folder.ignored:
            text = os.path.relpath(
                Path(folder.source_folder).resolve(),
                Path(self._favorite_folder).expanduser().resolve(),
            )
        item = QListWidgetItem(text)
        item.setToolTip(folder.source_folder)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        font = item.font()
        font.setBold(folder.missing)
        item.setFont(font)
        item.setCheckState(
            Qt.CheckState.Unchecked if folder.ignored else Qt.CheckState.Checked
        )
        if folder.ignored:
            item.setForeground(QColor("red"))
        self._rows.append((item, folder))
        self.folder_list.addItem(item)

    def _size_list(self) -> None:
        maximum = int(
            get_runtime_setting(RuntimeSettingKey.CLEAN_CACHE_LIST_VISIBLE_ROWS)
        )
        count = max(1, min(self.folder_list.count(), maximum))
        row_height = self.folder_list.sizeHintForRow(0)
        if row_height <= 0:
            row_height = self.folder_list.fontMetrics().lineSpacing()
        self.folder_list.setFixedHeight(
            count * row_height + 2 * self.folder_list.frameWidth()
        )

    def _include_ignored(self) -> None:
        if not self.include_ignored_button.isEnabled():
            return
        for folder in self._scan.folders:
            if folder.ignored:
                self._add_folder(folder)
        self.include_ignored_button.setEnabled(False)
        ignored_count = sum(folder.ignored for folder in self._scan.folders)
        self.notes_label.setText(
            self.notes_label.text().replace(
                f"{ignored_count} existing folders under Favorite are ignored.",
                "Red paths are relative to Favorite and start unchecked.",
            )
        )
        self._size_list()
        self._update_ok()
        self.sync_size_to_content()

    def _check_all(self, checked: bool) -> None:
        blocked = self.folder_list.blockSignals(True)
        try:
            for item, _folder in self._rows:
                item.setCheckState(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )
        finally:
            self.folder_list.blockSignals(blocked)
        self._update_ok()

    def _update_ok(self, *_args) -> None:
        button = self.button("ok")
        if button is not None:
            button.setEnabled(
                any(
                    item.checkState() == Qt.CheckState.Checked for item, _ in self._rows
                )
            )

    def _on_ok(self) -> None:
        selected = [
            folder
            for item, folder in self._rows
            if item.checkState() == Qt.CheckState.Checked
        ]
        if selected and confirm_cleanup(self, len(selected)):
            self.selected_folders = selected
            self.accept()


class CacheCleanupDialog(ToolFlowDialog):
    def __init__(
        self, cache_base: Path, folders: list[CacheFolder], parent=None
    ) -> None:
        self._cache_base = cache_base
        self._folders = folders
        self._started = False
        self.result_data = CacheCleanupResult()
        width = int(get_runtime_setting(RuntimeSettingKey.CLEAN_CACHE_DIALOG_WIDTH))
        workflow = ToolWorkflow(
            initial_screen="running",
            screens={
                "running": ToolScreen(
                    id="running",
                    title="Clean cache",
                    min_width=width,
                    build=lambda dialog: dialog._build_running(),
                    buttons=(ToolButton("ok", "OK", enabled=False),),
                    show_progress=True,
                    close_policy="ignore",
                ),
                "result": ToolScreen(
                    id="result",
                    title="Clean cache",
                    min_width=width,
                    build=lambda dialog: dialog._build_result(),
                    buttons=(ToolButton("ok", "OK", default=True),),
                ),
            },
            transitions={
                ("running", "progress"): lambda dialog, event: dialog._on_progress(
                    *event.args
                ),
                ("running", "finished"): lambda dialog, event: dialog._on_finished(
                    *event.args
                ),
                ("result", "ok"): lambda dialog, event: dialog.accept(),
            },
        )
        super().__init__(workflow, parent=parent)
        self.setFixedWidth(width)
        self.status_label.setWordWrap(False)
        self.set_status("Cleaning cache...")
        self.set_progress(0, len(folders))
        counter = f"{len(folders)}/{len(folders)}"
        self.progress_count_label.setFixedWidth(
            self.progress_count_label.fontMetrics().horizontalAdvance(counter)
        )
        self.sync_size_to_content()

    def _build_running(self) -> QWidget:
        self.path_label = EllidedLabel("", self, elide_mode=Qt.TextElideMode.ElideLeft)
        self.path_label.setTextFormat(Qt.TextFormat.PlainText)
        self.path_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.path_label.setFixedHeight(self.path_label.fontMetrics().lineSpacing())
        return self.path_label

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._started:
            self._started = True
            self._worker = CacheCleanupWorker(self._cache_base, self._folders)
            self.start_task(
                "cleanup",
                ToolTaskHandle.from_qrunnable(
                    worker=self._worker,
                    signal_map={
                        self._worker.signals.progress: "progress",
                        self._worker.signals.finished: "finished",
                    },
                ),
            )

    def _on_progress(self, completed: int, total: int, source_folder: str) -> None:
        self.path_label.setText(" ".join(source_folder.splitlines()))
        self.path_label.setToolTip(source_folder)
        self.progress_count_label.setText(f"{completed}/{total}")
        self.progress_bar.setValue(completed)
        self.progress_bar.setFormat(f"{completed}/{total}")

    def _on_finished(self, result: CacheCleanupResult) -> None:
        self.stop_task("cleanup", cancel=False)
        self.result_data = result
        self.transition_to("result")

    def _build_result(self) -> QWidget:
        result = self.result_data
        self.summary_text = SummaryTextEdit(
            [
                f"Image folders cleaned: {result.cleaned_folders}",
                f"Files deleted: {result.deleted_files}",
                f"Image cache folders remaining: {result.remaining_folders}",
                *result.errors,
            ],
            self,
        )
        return self.summary_text


def launch_clean_cache(window: MainWindow) -> None:
    cache_base = get_cache_base_dir().resolve()
    favorite = str(get_user_setting(UserSettingKey.FAVORITE_FOLDER) or "").strip()
    selection = CacheSelectionDialog(cache_base, favorite, parent=window)
    with managed_modal_dialog(selection):
        try:
            if selection.exec() != QDialog.DialogCode.Accepted:
                return
            folders = list(selection.selected_folders)
        finally:
            selection.stop_all_tasks(cancel=True)

    selected_dirs = {directory for folder in folders for directory in folder.cache_dirs}
    loaded_dirs = {
        get_cache_dir_for_folder(folder).resolve()
        for folder in window.photo_model.source_folders
    }
    if selected_dirs & loaded_dirs:
        try:
            window._prepare_workspace_for_cache_cleanup()
        except Exception as exc:
            QMessageBox.warning(window, "Clean cache", str(exc))
            return
    progress = CacheCleanupDialog(cache_base, folders, parent=window)
    with managed_modal_dialog(progress):
        try:
            progress.exec()
        finally:
            progress.stop_all_tasks(cancel=False)
