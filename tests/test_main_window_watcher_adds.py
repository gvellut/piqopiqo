"""Regression tests for batched watcher-driven additions in MainWindow."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.background.media_man import FolderPrimingResult
from piqopiqo.main_window import MainWindow
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.ssf.settings_state import init_qsettings_store


class _SignalStub:
    def connect(self, *_args, **_kwargs) -> None:
        return None


class _MediaManagerStub:
    next_priming_result = FolderPrimingResult({}, set())

    def __init__(self, *_args, **_kwargs):
        self.thumb_ready = _SignalStub()
        self.thumb_progress_updated = _SignalStub()
        self.editable_ready = _SignalStub()
        self.editable_terminal = _SignalStub()
        self.exif_progress_updated = _SignalStub()
        self.panel_fields_ready = _SignalStub()
        self.all_completed = _SignalStub()
        self.reset_calls: list[tuple[list[str], list[str]]] = []
        self.add_files_calls: list[list[str]] = []
        self.remove_files_calls: list[list[str]] = []
        self.refresh_files_calls: list[list[str]] = []
        self.visible_calls: list[list[str]] = []

    def reset_for_folder(
        self, file_paths: list[str], source_folders: list[str]
    ) -> FolderPrimingResult:
        self.reset_calls.append((list(file_paths), list(source_folders)))
        return self.next_priming_result

    def pause_processing(self) -> None:
        return None

    def resume_processing(self) -> None:
        return None

    def update_visible(self, visible_paths_in_order: list[str]) -> None:
        self.visible_calls.append(list(visible_paths_in_order))

    def has_errors(self) -> bool:
        return False

    def get_thumb_errors(self) -> dict[str, str]:
        return {}

    def get_exif_errors(self) -> dict[str, str]:
        return {}

    def add_files(self, file_paths: list[str]) -> None:
        self.add_files_calls.append(list(file_paths))

    def remove_files(self, file_paths: list[str]) -> None:
        self.remove_files_calls.append(list(file_paths))

    def request_thumbnail(self, _file_path: str) -> None:
        return None

    def regenerate_thumbnails(self, _file_paths: list[str]) -> None:
        return None

    def refresh_files(self, file_paths: list[str]) -> None:
        self.refresh_files_calls.append(list(file_paths))

    def reload_exif(self, _file_paths: list[str]) -> None:
        return None

    def ensure_panel_fields_loaded_from_db(self, _file_paths: list[str]) -> None:
        return None

    def refresh_exif_field_keys(self, _field_keys: list[str]) -> None:
        return None

    def stop(self, timeout_s: float | None = None) -> None:  # noqa: ARG002
        return None


def _touch_image(path: Path) -> dict:
    path.write_bytes(b"")
    created = datetime.fromtimestamp(path.stat().st_ctime).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "path": str(path),
        "name": path.name,
        "created": created,
        "source_folder": str(path.parent),
        "state": 0,
    }


def _viewport_row_for_path(window: MainWindow, path: str) -> int:
    index = window.grid.get_index_for_path(path)
    assert index is not None
    return (index // window.grid.n_cols) - window.grid.scrollbar.value()


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-watcher-adds-{uuid.uuid4().hex}")
    return app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):  # noqa: ARG001
    init_qsettings_store(dyn=True)
    _MediaManagerStub.next_priming_result = FolderPrimingResult({}, set())
    monkeypatch.setattr("piqopiqo.main_window.MediaManager", _MediaManagerStub)
    monkeypatch.setattr(
        "piqopiqo.main_window.refresh_main_screen_color_space_cache_macos",
        lambda: None,
    )

    initial_images = [
        _touch_image(tmp_path / f"P{index:04d}.JPG") for index in range(80, 180)
    ]

    main_window = MainWindow(initial_images, [str(tmp_path)], None)
    main_window.resize(900, 700)
    main_window.show()
    qapp.processEvents()
    yield main_window
    main_window.close()


def test_watcher_add_batch_refreshes_grid_once_and_registers_media_once(
    window: MainWindow, monkeypatch, tmp_path
):
    original_set_data = window.grid.set_data
    set_data_calls: list[int] = []

    def _wrapped_set_data(items, *, fast_first_paint: bool = False):
        set_data_calls.append(len(items))
        return original_set_data(items, fast_first_paint=fast_first_paint)

    monkeypatch.setattr(window.grid, "set_data", _wrapped_set_data)
    window.media_manager.add_files_calls.clear()
    set_data_calls.clear()

    new_one = _touch_image(tmp_path / "P9991.JPG")
    new_two = _touch_image(tmp_path / "P9992.JPG")

    window._on_folder_changes([
        ("added", new_one["path"]),
        ("added", new_two["path"]),
    ])

    assert window.media_manager.add_files_calls == [[new_one["path"], new_two["path"]]]
    assert len(set_data_calls) == 1
    assert (
        sum(1 for item in window.photo_model.all_photos if item.path == new_one["path"])
        == 1
    )
    assert (
        sum(1 for item in window.photo_model.all_photos if item.path == new_two["path"])
        == 1
    )


def test_watcher_add_duplicate_events_across_batches_are_idempotent(
    window: MainWindow, tmp_path
):
    window.media_manager.add_files_calls.clear()
    new_image = _touch_image(tmp_path / "P9993.JPG")

    window._on_folder_changes([("added", new_image["path"])])
    window._on_folder_changes([("added", new_image["path"])])

    assert window.media_manager.add_files_calls == [[new_image["path"]]]
    assert (
        sum(
            1
            for item in window.photo_model.all_photos
            if item.path == new_image["path"]
        )
        == 1
    )


def test_watcher_add_skips_paths_already_present_in_model(window: MainWindow, tmp_path):
    existing_path = window.photo_model.all_photos[0].path
    new_image = _touch_image(tmp_path / "P9994.JPG")
    window.media_manager.add_files_calls.clear()

    window._on_folder_changes([
        ("added", existing_path),
        ("added", new_image["path"]),
    ])

    assert window.media_manager.add_files_calls == [[new_image["path"]]]
    assert (
        sum(1 for item in window.photo_model.all_photos if item.path == existing_path)
        == 1
    )
    assert (
        sum(
            1
            for item in window.photo_model.all_photos
            if item.path == new_image["path"]
        )
        == 1
    )


def test_watcher_add_batch_restores_viewport_without_revealing_new_top_item(
    window: MainWindow, qapp: QApplication, tmp_path
):
    assert window.grid.scrollbar.maximum() > 0
    window.grid.scrollbar.setValue(2)
    qapp.processEvents()

    visible_before = window.grid.get_viewport_visible_paths()
    assert visible_before
    anchor_path = visible_before[0]
    anchor_row = _viewport_row_for_path(window, anchor_path)

    new_image = _touch_image(tmp_path / "A0000.JPG")
    window._on_folder_changes([("added", new_image["path"])])
    qapp.processEvents()

    visible_after = window.grid.get_viewport_visible_paths()
    assert anchor_path in visible_after
    assert _viewport_row_for_path(window, anchor_path) == anchor_row
    assert new_image["path"] not in visible_after


def test_watcher_modified_batch_preserves_preview_and_refreshes_media_once(
    window: MainWindow, monkeypatch
):
    refresh_item_calls: list[int] = []
    window.media_manager.refresh_files_calls.clear()
    monkeypatch.setattr(
        window.grid,
        "refresh_item",
        lambda index: refresh_item_calls.append(index),
    )

    modified_paths = [
        window.photo_model.all_photos[5].path,
        window.photo_model.all_photos[8].path,
    ]

    window._on_folder_changes([("modified", path) for path in modified_paths])

    assert window.media_manager.refresh_files_calls == [modified_paths]
    assert refresh_item_calls == []


def test_watcher_same_path_replace_keeps_metadata_and_refreshes(
    window: MainWindow,
):
    item = window.photo_model.all_photos[5]
    path = item.path
    metadata = {
        DBFields.TITLE: "Edited title",
        DBFields.DESCRIPTION: "Edited description",
        DBFields.LATITUDE: 48.8566,
        DBFields.LONGITUDE: 2.3522,
        DBFields.KEYWORDS: "alpha, beta",
        DBFields.TIME_TAKEN: datetime(2026, 1, 1, 10, 0, 0),
        DBFields.LABEL: "Approved",
        DBFields.ORIENTATION: 6,
    }
    db = window.db_manager.get_db_for_folder(item.source_folder)
    db.save_metadata(path, metadata)
    item.db_metadata = metadata.copy()
    item.state = 2
    item._cache_state_dirty = False
    item.embedded_pixmap = object()
    item.hq_pixmap = object()
    item.pixmap = object()
    item._pixmap_source = item.hq_pixmap
    item._pixmap_orientation = 6
    item.exif_data = {"File:FileName": "old.jpg"}
    original_embedded = item.embedded_pixmap
    original_hq = item.hq_pixmap
    original_display = item.pixmap

    original_item_count = len(window.photo_model.all_photos)
    window.media_manager.add_files_calls.clear()
    window.media_manager.remove_files_calls.clear()
    window.media_manager.refresh_files_calls.clear()

    Path(path).write_bytes(b"replacement image bytes")

    window._on_folder_changes([("deleted", path), ("added", path)])

    assert len(window.photo_model.all_photos) == original_item_count
    assert window._items_by_path[path] is item
    assert item.db_metadata == metadata
    stored = db.get_metadata(path)
    assert stored is not None
    for field, expected in metadata.items():
        assert stored[field] == expected
    assert window.media_manager.remove_files_calls == []
    assert window.media_manager.add_files_calls == []
    assert window.media_manager.refresh_files_calls == [[path]]
    assert item.state == 2
    assert item._cache_state_dirty is False
    assert item.embedded_pixmap is original_embedded
    assert item.hq_pixmap is original_hq
    assert item.pixmap is original_display
    assert item.exif_data is None
    assert item._pixmap_source is original_hq
    assert item._pixmap_orientation == 6


def test_watcher_existing_path_added_event_refreshes_thumbnail_state(
    window: MainWindow,
):
    item = window.photo_model.all_photos[5]
    path = item.path
    item.state = 2
    item._cache_state_dirty = False
    item.embedded_pixmap = object()
    item.hq_pixmap = object()
    item.pixmap = object()
    item._pixmap_source = item.hq_pixmap
    item._pixmap_orientation = 1
    item.exif_data = {"File:FileName": "old.jpg"}
    original_embedded = item.embedded_pixmap
    original_hq = item.hq_pixmap
    original_display = item.pixmap

    window.media_manager.add_files_calls.clear()
    window.media_manager.remove_files_calls.clear()
    window.media_manager.refresh_files_calls.clear()

    Path(path).write_bytes(b"replacement image bytes")

    window._on_folder_changes([("added", path)])

    assert window.media_manager.remove_files_calls == []
    assert window.media_manager.add_files_calls == []
    assert window.media_manager.refresh_files_calls == [[path]]
    assert item.state == 2
    assert item._cache_state_dirty is False
    assert item.embedded_pixmap is original_embedded
    assert item.hq_pixmap is original_hq
    assert item.pixmap is original_display
    assert item.exif_data is None
    assert item._pixmap_source is original_hq
    assert item._pixmap_orientation == 1


def test_watcher_delete_removes_subfolder_image_and_keeps_surviving_selection(
    window: MainWindow, tmp_path
):
    survivor = window.photo_model.all_photos[0]
    subfolder = tmp_path / "sub"
    subfolder.mkdir()
    moved_out = _touch_image(subfolder / "P9995.JPG")
    window._on_folder_changes([("added", moved_out["path"])])

    window.select_paths_in_grid(
        [survivor.path, moved_out["path"]],
        anchor_path=moved_out["path"],
    )
    assert {item.path for item in window.photo_model.get_selected_photos()} == {
        survivor.path,
        moved_out["path"],
    }

    window._on_folder_changes([("deleted", moved_out["path"])])

    all_paths = {item.path for item in window.photo_model.all_photos}
    assert moved_out["path"] not in all_paths
    assert {item.path for item in window.photo_model.get_selected_photos()} == {
        survivor.path
    }
    assert str(subfolder) not in window.photo_model.source_folders


def test_watcher_move_inside_root_updates_path_and_keeps_selection(
    window: MainWindow, tmp_path
):
    item = window.photo_model.all_photos[0]
    old_path = item.path
    new_folder = tmp_path / "renamed"
    new_folder.mkdir()
    new_path = str(new_folder / Path(old_path).name)
    Path(old_path).rename(new_path)

    window.media_manager.add_files_calls.clear()
    window.media_manager.remove_files_calls.clear()
    window.select_paths_in_grid([old_path], anchor_path=old_path)

    window._on_folder_changes([("moved", old_path, new_path)])

    assert old_path not in window._items_by_path
    assert new_path in window._items_by_path
    assert item.path == new_path
    assert item.source_folder == str(new_folder)
    assert window.photo_model.get_selected_photos() == [item]
    assert window.media_manager.remove_files_calls == [[old_path]]
    assert window.media_manager.add_files_calls == [[new_path]]
    assert str(new_folder) in window.photo_model.source_folders


class _FakeFullscreenOverlay:
    def __init__(self, current_path: str, loop_paths: list[str], all_paths: list[str]):
        self.current_path = current_path
        self.loop_paths = list(loop_paths)
        self.all_paths = list(all_paths)
        self.rebind_calls: list[tuple[list[str], list[str], str | None]] = []
        self.closed = False

    def get_current_path(self) -> str | None:
        return self.current_path

    def get_visible_paths(self) -> list[str]:
        return list(self.loop_paths)

    def get_all_paths(self) -> list[str]:
        return list(self.all_paths)

    def get_ejected_paths(self) -> list[str]:
        return []

    def rebind_to_items_and_paths(
        self,
        all_items: list,
        paths: list[str],
        preferred_path: str | None = None,
    ) -> bool:
        self.rebind_calls.append((
            [item.path for item in all_items],
            list(paths),
            preferred_path,
        ))
        self.all_paths = [item.path for item in all_items]
        self.loop_paths = list(paths)
        self.current_path = preferred_path or (paths[0] if paths else None)
        return bool(paths)

    def close(self) -> None:
        self.closed = True


def test_watcher_move_inside_root_rebinds_fullscreen_to_new_path(
    window: MainWindow, tmp_path
):
    item = window.photo_model.all_photos[0]
    old_path = item.path
    other_path = window.photo_model.all_photos[1].path
    new_path = str(tmp_path / "fullscreen-renamed.JPG")
    Path(old_path).rename(new_path)

    overlay = _FakeFullscreenOverlay(
        current_path=old_path,
        loop_paths=[old_path, other_path],
        all_paths=[photo.path for photo in window.photo_model.photos],
    )
    window._fullscreen_overlay = overlay
    window._fullscreen_started_with_multi_selection = False

    window._on_folder_changes([("moved", old_path, new_path)])

    assert overlay.closed is False
    assert overlay.rebind_calls[-1][1] == [new_path, other_path]
    assert overlay.rebind_calls[-1][2] == new_path
    assert overlay.current_path == new_path


def test_watcher_delete_rebinds_fullscreen_to_next_surviving_path(window: MainWindow):
    removed = window.photo_model.all_photos[0].path
    survivor = window.photo_model.all_photos[1].path
    overlay = _FakeFullscreenOverlay(
        current_path=removed,
        loop_paths=[removed, survivor],
        all_paths=[photo.path for photo in window.photo_model.photos],
    )
    window._fullscreen_overlay = overlay
    window._fullscreen_started_with_multi_selection = False

    window._on_folder_changes([("deleted", removed)])

    assert overlay.closed is False
    assert overlay.rebind_calls[-1][1] == [survivor]
    assert overlay.rebind_calls[-1][2] == survivor
    assert overlay.current_path == survivor
