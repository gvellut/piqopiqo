"""GPX feature actions extracted from MainWindow."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QDialog, QMessageBox

from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.ssf.settings_state import (
    RuntimeSettingKey,
    StateKey,
    UserSettingKey,
    get_runtime_setting,
    get_state,
    get_user_setting,
)

from .constants import FOLDER_STATE_LAST_GPX_PATH, FOLDER_STATE_LAST_TIME_SHIFT
from .gpx_processing import to_relative_folder
from .time_shift_memory import (
    normalize_time_shift,
    normalize_timeshift_cache,
    remember_timeshift_value,
    resolve_timeshift_for_folder,
)

if TYPE_CHECKING:
    from piqopiqo.main_window import MainWindow
    from piqopiqo.model import ImageItem

logger = logging.getLogger(__name__)


def _read_last_timeshift_by_folders_state() -> dict[str, str]:
    state = get_state()
    return normalize_timeshift_cache(state.get(StateKey.LAST_TIMESHIFT_BY_FOLDERS))


def _read_last_timeshift_state() -> str | None:
    state = get_state()
    return normalize_time_shift(state.get(StateKey.LAST_TIMESHIFT))


def _remember_time_shift(*, relative_folder: str, time_shift: str) -> None:
    shift = normalize_time_shift(time_shift)
    if shift is None:
        return

    current_cache = _read_last_timeshift_by_folders_state()
    updated_cache = remember_timeshift_value(
        current_cache,
        folder_key=relative_folder,
        value=shift,
        limit=max(
            0,
            int(get_runtime_setting(RuntimeSettingKey.TIMESHIFT_CACHE_NUM)),
        ),
    )

    state = get_state()
    state.set(StateKey.LAST_TIMESHIFT_BY_FOLDERS, updated_cache)
    state.set(StateKey.LAST_TIMESHIFT, shift)


def persist_folder_time_shift(
    window: MainWindow,
    folder_path: str,
    time_shift: str | None,
) -> None:
    shift = normalize_time_shift(time_shift)
    db_folder = window.db_manager.get_db_for_folder(folder_path)
    db_folder.set_folder_value(FOLDER_STATE_LAST_TIME_SHIFT, shift)
    if shift is None:
        return

    relative_folder = to_relative_folder(
        window.root_folder or folder_path,
        folder_path,
    )
    _remember_time_shift(relative_folder=relative_folder, time_shift=shift)


def _persist_apply_gpx_time_shifts(
    window: MainWindow,
    folder_time_shifts: dict[str, str],
) -> None:
    for folder_path, time_shift in folder_time_shifts.items():
        persist_folder_time_shift(window, folder_path, time_shift)


def _set_gpx_path_for_folders(
    window: MainWindow,
    source_folders: list[str],
    gpx_path: str | None,
) -> None:
    value = str(gpx_path).strip() if gpx_path is not None else ""
    to_store = value if value else None
    for folder in source_folders:
        db = window.db_manager.get_db_for_folder(folder)
        db.set_folder_value(FOLDER_STATE_LAST_GPX_PATH, to_store)


def _get_first_folder_gpx_path(window: MainWindow, source_folders: list[str]) -> str:
    for folder in source_folders:
        value = window.db_manager.get_db_for_folder(folder).get_folder_value(
            FOLDER_STATE_LAST_GPX_PATH
        )
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _resolve_apply_gpx_initial_time_shifts(
    window: MainWindow,
) -> tuple[dict[str, str], set[str]]:
    ignore_unknown_folder_last = bool(
        get_user_setting(UserSettingKey.TIME_SHIFT_UNKNOWN_FOLDER_IGNORE)
    )
    cache_by_folder = _read_last_timeshift_by_folders_state()
    last_timeshift = _read_last_timeshift_state()

    initial_time_shifts: dict[str, str] = {}
    previous_time_shift_folders: set[str] = set()
    for folder in sorted(window.photo_model.source_folders):
        db_shift = window.db_manager.get_db_for_folder(folder).get_folder_value(
            FOLDER_STATE_LAST_TIME_SHIFT
        )
        relative_folder = to_relative_folder(window.root_folder or folder, folder)
        resolved_shift, from_state = resolve_timeshift_for_folder(
            db_value=db_shift,
            folder_key=relative_folder,
            cache_by_folder=cache_by_folder,
            last_timeshift=last_timeshift,
            ignore_unknown_folder_last=ignore_unknown_folder_last,
        )
        initial_time_shifts[folder] = resolved_shift
        if from_state and resolved_shift:
            previous_time_shift_folders.add(folder)

    return initial_time_shifts, previous_time_shift_folders


def apply_gpx_result_to_model(window: MainWindow, result, *, update_db: bool) -> None:
    if not update_db:
        return

    updated_paths = list(getattr(result, "updated_paths", []) or [])
    if not updated_paths:
        return

    for path in updated_paths:
        item = window._items_by_path.get(path)
        if item is None:
            continue
        db = window.db_manager.get_db_for_image(path)
        meta = db.get_metadata(path)
        if meta is None:
            continue
        item.db_metadata = meta.copy()

    window.sync_model_after_metadata_update(
        {DBFields.TIME_TAKEN, DBFields.LATITUDE, DBFields.LONGITUDE},
        source="apply_gpx",
    )


def extract_gps_time_shift_for_item(window: MainWindow, item: ImageItem) -> None:
    from .dialogs import (
        ExtractGpsTimeShiftConfirmDialog,
        ExtractGpsTimeShiftProgressDialog,
    )
    from .workers import ExtractGpsTimeShiftWorker

    folder_path = item.source_folder
    db_folder = window.db_manager.get_db_for_folder(folder_path)
    existing_shift = db_folder.get_folder_value(FOLDER_STATE_LAST_TIME_SHIFT)
    relative_folder = to_relative_folder(window.root_folder or folder_path, folder_path)

    confirm = ExtractGpsTimeShiftConfirmDialog(
        folder_label=relative_folder,
        existing_shift=existing_shift,
        parent=window,
    )
    if confirm.exec() != QDialog.DialogCode.Accepted:
        return

    metadata = item.db_metadata
    if metadata is None:
        metadata = window.db_manager.get_db_for_image(item.path).get_metadata(item.path)
    if not metadata:
        QMessageBox.warning(
            window, "Extract GPS Time shift", "Metadata is not ready yet."
        )
        return

    time_taken = metadata.get(DBFields.TIME_TAKEN)
    if not isinstance(time_taken, datetime):
        QMessageBox.warning(
            window,
            "Extract GPS Time shift",
            "Time taken is missing for the selected photo.",
        )
        return

    worker = ExtractGpsTimeShiftWorker(
        photo_path=item.path,
        exif_time=time_taken,
        gcp_project=str(get_user_setting(UserSettingKey.GCP_PROJECT) or ""),
        gcp_sa_key_path=str(get_user_setting(UserSettingKey.GCP_SA_KEY_PATH) or ""),
    )

    progress = ExtractGpsTimeShiftProgressDialog(parent=window)
    progress.start(worker)
    if progress.exec() != QDialog.DialogCode.Accepted:
        return

    if progress.result_shift:
        persist_folder_time_shift(window, folder_path, progress.result_shift)


def launch_apply_gpx(window: MainWindow) -> None:
    if not window.root_folder or not window.photo_model.source_folders:
        return
    if window._active_apply_gpx_worker is not None:
        QMessageBox.information(
            window,
            "Apply GPX",
            "An Apply GPX operation is already running.",
        )
        return

    from .dialogs import (
        ApplyGpxDialog,
        ApplyGpxMode,
        ApplyGpxProgressDialog,
    )
    from .workers import ApplyGpxWorker

    source_folders = list(window.photo_model.source_folders)
    state = get_state()
    last_gpx_folder = str(state.get(StateKey.LAST_GPX_FOLDER) or "").strip()
    initial_gpx_path = _get_first_folder_gpx_path(window, source_folders)
    initial_time_shifts, previous_time_shift_folders = (
        _resolve_apply_gpx_initial_time_shifts(window)
    )

    def on_browse_selected_folder(folder: str) -> None:
        state.set(StateKey.LAST_GPX_FOLDER, str(folder).strip())

    input_dialog = ApplyGpxDialog(
        root_folder=window.root_folder,
        source_folders=source_folders,
        initial_time_shifts=initial_time_shifts,
        previous_time_shift_folders=previous_time_shift_folders,
        initial_gpx_path=initial_gpx_path,
        kml_folder=str(get_user_setting(UserSettingKey.GPX_KML_FOLDER) or ""),
        last_gpx_folder=last_gpx_folder,
        on_browse_selected_folder=on_browse_selected_folder,
        parent=window,
    )
    if input_dialog.exec() != QDialog.DialogCode.Accepted:
        return

    gpx_path, mode, folder_time_shifts = input_dialog.get_values()
    _persist_apply_gpx_time_shifts(window, folder_time_shifts)
    _set_gpx_path_for_folders(window, source_folders, gpx_path)
    update_db = mode == ApplyGpxMode.UPDATE_DB

    folder_to_files: dict[str, list[str]] = {}
    for item in window.photo_model.all_photos:
        folder_to_files.setdefault(item.source_folder, []).append(item.path)

    total = sum(len(paths) for paths in folder_to_files.values())
    progress_dialog = ApplyGpxProgressDialog(total=total, parent=window)

    worker = ApplyGpxWorker(
        root_folder=window.root_folder,
        folder_to_files=folder_to_files,
        gpx_path=gpx_path,
        db_manager=window.db_manager,
        timezone_name=str(get_user_setting(UserSettingKey.GPX_TIMEZONE) or ""),
        ignore_offset=bool(get_user_setting(UserSettingKey.GPX_IGNORE_OFFSET)),
        kml_folder=str(get_user_setting(UserSettingKey.GPX_KML_FOLDER) or ""),
        update_db=update_db,
        exiftool_path=str(get_user_setting(UserSettingKey.EXIFTOOL_PATH) or ""),
    )
    window._active_apply_gpx_worker = worker

    def on_folder_changed(relative_folder: str):
        progress_dialog.set_folder(relative_folder)

    def on_progress(completed: int, total_count: int):
        progress_dialog.set_progress(completed, total_count)

    def on_error(message: str):
        window._active_apply_gpx_worker = None
        if progress_dialog.isVisible():
            progress_dialog.show_error(message)
        else:
            QMessageBox.warning(window, "Apply GPX", message)

    def on_finished(result):
        window._active_apply_gpx_worker = None
        if result is None:
            return

        apply_gpx_result_to_model(window, result, update_db=update_db)

        if progress_dialog.isVisible():
            progress_dialog.finish(result)

    worker.signals.folder_changed.connect(on_folder_changed)
    worker.signals.progress.connect(on_progress)
    worker.signals.error.connect(on_error)
    worker.signals.finished.connect(on_finished)
    progress_dialog.cancel_requested.connect(worker.request_cancel)

    QThreadPool.globalInstance().start(worker)
    progress_dialog.exec()


def launch_clear_gps(window: MainWindow) -> None:
    if not window.root_folder or not window.photo_model.source_folders:
        return
    if window._active_apply_gpx_worker is not None:
        QMessageBox.information(
            window,
            "Clear GPS",
            "An Apply GPX operation is already running.",
        )
        return

    items = list(window.photo_model.all_photos)
    if not items:
        return

    reply = QMessageBox.question(
        window,
        "Clear GPS",
        (
            f"Clear GPS coordinates (latitude/longitude) for {len(items)} loaded "
            "photo(s)?\n\nThis only updates the metadata database."
        ),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if reply != QMessageBox.StandardButton.Yes:
        return

    updated_count = 0
    for item in items:
        db = window.db_manager.get_db_for_image(item.path)
        metadata = item.db_metadata
        if metadata is None:
            metadata = db.get_metadata(item.path)
        if metadata is None:
            continue

        updated_metadata = metadata.copy()
        updated_metadata[DBFields.LATITUDE] = None
        updated_metadata[DBFields.LONGITUDE] = None
        db.save_metadata(item.path, updated_metadata)

        item.db_metadata = updated_metadata.copy()
        updated_count += 1

    if updated_count <= 0:
        return

    window.sync_model_after_metadata_update(
        {DBFields.LATITUDE, DBFields.LONGITUDE},
        source="clear_gps",
    )
