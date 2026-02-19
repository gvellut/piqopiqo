"""Grid context menu and file operations extracted from MainWindow."""

from __future__ import annotations

from datetime import datetime
import logging
import os
import shutil
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMenu
from send2trash import send2trash

from piqopiqo.external_apps import open_in_external_app, reveal_in_file_manager
from piqopiqo.model import ImageItem
from piqopiqo.settings_state import UserSettingKey, get_user_setting

if TYPE_CHECKING:
    from piqopiqo.main_window import MainWindow

logger = logging.getLogger(__name__)


def display_external_app_name(app_path: str) -> str:
    base = os.path.basename(app_path.rstrip(os.sep))
    if base.lower().endswith(".app"):
        return base[:-4]
    return base or app_path


def get_duplicate_path(original_path: str) -> str:
    directory = os.path.dirname(original_path)
    name, ext = os.path.splitext(os.path.basename(original_path))

    suffix = " copy"
    counter = 1

    while True:
        if counter == 1:
            new_name = f"{name}{suffix}{ext}"
        else:
            new_name = f"{name}{suffix}{counter}{ext}"

        new_path = os.path.join(directory, new_name)
        if not os.path.exists(new_path):
            return new_path
        counter += 1


def duplicate_photos(window: MainWindow, photos: list[ImageItem]) -> None:
    for photo in photos:
        new_path = get_duplicate_path(photo.path)
        try:
            shutil.copy2(photo.path, new_path)
            window._suppress_watcher_paths([new_path])

            new_item = ImageItem(
                path=new_path,
                name=os.path.basename(new_path),
                created=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                source_folder=photo.source_folder,
            )

            window.photo_model.add_photo(new_item)
            logger.info(f"Duplicated {photo.path} to {new_path}")

        except OSError as e:
            logger.error(f"Failed to duplicate {photo.path}: {e}")


def move_to_trash(window: MainWindow, photos: list[ImageItem]) -> None:
    paths_to_remove = []

    for photo in photos:
        try:
            window._suppress_watcher_paths([photo.path])
            send2trash(photo.path)
            paths_to_remove.append(photo.path)
            logger.info(f"Moved to trash: {photo.path}")
        except Exception as e:
            logger.error(f"Failed to trash {photo.path}: {e}")

    for path in paths_to_remove:
        window.photo_model.remove_photo(path)


def regenerate_selected_thumbnails(window: MainWindow, photos: list[ImageItem]) -> None:
    paths = [p.path for p in photos]
    for photo in photos:
        photo.state = 0
        photo.embedded_pixmap = None
        photo.hq_pixmap = None
        photo.pixmap = None
    window.media_manager.regenerate_thumbnails(paths)

    window.grid.on_scroll(window.grid.scrollbar.value())


def edit_in_external_app(window: MainWindow, photos: list[ImageItem]) -> None:
    duplicated_paths = []
    for photo in photos:
        new_path = get_duplicate_path(photo.path)
        try:
            shutil.copy2(photo.path, new_path)
            window._suppress_watcher_paths([new_path])
            new_item = ImageItem(
                path=new_path,
                name=os.path.basename(new_path),
                created=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                source_folder=photo.source_folder,
            )
            window.photo_model.add_photo(new_item)
            duplicated_paths.append(new_path)
            logger.info(f"Duplicated {photo.path} to {new_path} for editing")
        except OSError as e:
            logger.error(f"Failed to duplicate {photo.path}: {e}")

    if duplicated_paths:
        open_in_external_app(
            get_user_setting(UserSettingKey.EXTERNAL_EDITOR),
            duplicated_paths,
        )


def show_context_menu(window: MainWindow, global_index: int, pos) -> None:
    from piqopiqo.tools.gpx2exif.actions import extract_gps_time_shift_for_item

    selected = window.photo_model.get_selected_photos()
    if not selected:
        return
    clicked_item = (
        window.images_data[global_index]
        if 0 <= global_index < len(window.images_data)
        else selected[0]
    )

    menu = QMenu(window)

    # Reveal in Finder
    reveal_action = menu.addAction("Reveal in Finder")
    reveal_action.triggered.connect(lambda: reveal_in_file_manager(selected))

    # View in Application (only if configured)
    external_viewer = get_user_setting(UserSettingKey.EXTERNAL_VIEWER)
    if external_viewer:
        view_app_action = menu.addAction(
            f"View in {display_external_app_name(external_viewer)}"
        )
        view_app_action.triggered.connect(
            lambda: open_in_external_app(external_viewer, [p.path for p in selected])
        )

    # Edit in Application (only if configured)
    external_editor = get_user_setting(UserSettingKey.EXTERNAL_EDITOR)
    if external_editor:
        edit_app_action = menu.addAction(
            f"Edit in {display_external_app_name(external_editor)}"
        )
        edit_app_action.triggered.connect(
            lambda: edit_in_external_app(window, selected)
        )

    menu.addSeparator()

    # Regenerate Thumbnail action
    if len(selected) == 1:
        regen_action = menu.addAction("Regenerate Thumbnail")
    else:
        regen_action = menu.addAction(f"Regenerate Thumbnails ({len(selected)} photos)")
    regen_action.triggered.connect(
        lambda: regenerate_selected_thumbnails(window, selected)
    )

    # Regenerate EXIF action
    if len(selected) == 1:
        regen_exif_action = menu.addAction("Regenerate EXIF")
    else:
        regen_exif_action = menu.addAction(f"Regenerate EXIF ({len(selected)} photos)")
    regen_exif_action.triggered.connect(
        lambda: window.media_manager.regenerate_exif([p.path for p in selected])
    )

    menu.addSeparator()

    extract_shift_action = menu.addAction("Extract GPS Time Shift")
    extract_shift_action.triggered.connect(
        lambda: extract_gps_time_shift_for_item(window, clicked_item)
    )

    menu.addSeparator()

    # Duplicate action
    if len(selected) == 1:
        duplicate_action = menu.addAction("Duplicate")
    else:
        duplicate_action = menu.addAction(f"Duplicate ({len(selected)} photos)")
    duplicate_action.triggered.connect(lambda: duplicate_photos(window, selected))

    menu.addSeparator()

    # Move to Trash action
    if len(selected) == 1:
        trash_action = menu.addAction("Move to Trash")
    else:
        trash_action = menu.addAction(f"Move to Trash ({len(selected)} photos)")
    trash_action.triggered.connect(lambda: move_to_trash(window, selected))

    menu.exec(pos)
