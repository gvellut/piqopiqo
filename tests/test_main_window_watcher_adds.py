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

    def remove_files(self, _file_paths: list[str]) -> None:
        return None

    def request_thumbnail(self, _file_path: str) -> None:
        return None

    def regenerate_thumbnails(self, _file_paths: list[str]) -> None:
        return None

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

    window._on_folder_changes(
        [
            ("added", new_one["path"]),
            ("added", new_two["path"]),
        ]
    )

    assert window.media_manager.add_files_calls == [[new_one["path"], new_two["path"]]]
    assert len(set_data_calls) == 1
    assert sum(1 for item in window.photo_model.all_photos if item.path == new_one["path"]) == 1
    assert sum(1 for item in window.photo_model.all_photos if item.path == new_two["path"]) == 1


def test_watcher_add_duplicate_events_across_batches_are_idempotent(
    window: MainWindow, tmp_path
):
    window.media_manager.add_files_calls.clear()
    new_image = _touch_image(tmp_path / "P9993.JPG")

    window._on_folder_changes([("added", new_image["path"])])
    window._on_folder_changes([("added", new_image["path"])])

    assert window.media_manager.add_files_calls == [[new_image["path"]]]
    assert sum(1 for item in window.photo_model.all_photos if item.path == new_image["path"]) == 1


def test_watcher_add_skips_paths_already_present_in_model(
    window: MainWindow, tmp_path
):
    existing_path = window.photo_model.all_photos[0].path
    new_image = _touch_image(tmp_path / "P9994.JPG")
    window.media_manager.add_files_calls.clear()

    window._on_folder_changes(
        [
            ("added", existing_path),
            ("added", new_image["path"]),
        ]
    )

    assert window.media_manager.add_files_calls == [[new_image["path"]]]
    assert sum(1 for item in window.photo_model.all_photos if item.path == existing_path) == 1
    assert sum(1 for item in window.photo_model.all_photos if item.path == new_image["path"]) == 1


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
