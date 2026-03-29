"""Tests for Copy SD bulk-copy integration in MainWindow."""

from __future__ import annotations

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

    def reset_for_folder(
        self, _file_paths: list[str], _source_folders: list[str]
    ) -> FolderPrimingResult:
        return self.next_priming_result

    def pause_processing(self) -> None:
        return None

    def resume_processing(self) -> None:
        return None

    def update_visible(self, _visible_paths_in_order: list[str]) -> None:
        return None

    def has_errors(self) -> bool:
        return False

    def get_thumb_errors(self) -> dict[str, str]:
        return {}

    def get_exif_errors(self) -> dict[str, str]:
        return {}

    def add_files(self, _file_paths: list[str]) -> None:
        return None

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


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-copy-sd-main-window-{uuid.uuid4().hex}")
    return app


@pytest.fixture
def window(qapp, monkeypatch):  # noqa: ARG001
    init_qsettings_store(dyn=True)
    _MediaManagerStub.next_priming_result = FolderPrimingResult({}, set())
    monkeypatch.setattr("piqopiqo.main_window.MediaManager", _MediaManagerStub)
    monkeypatch.setattr(
        "piqopiqo.main_window.refresh_main_screen_color_space_cache_macos",
        lambda: None,
    )

    main_window = MainWindow([], [], None)
    main_window.root_folder = "/photos/root"
    yield main_window
    main_window.close()


def test_workspace_bulk_refresh_overlap_reloads_once_when_files_copied(
    window: MainWindow, monkeypatch
):
    stop_calls: list[str] = []
    load_calls: list[tuple[str, bool]] = []
    start_calls: list[str] = []

    monkeypatch.setattr(window, "_stop_folder_watcher", lambda: stop_calls.append("stop"))
    monkeypatch.setattr(
        window,
        "_load_folder",
        lambda folder, *, reset_grid_to_top=False: load_calls.append(
            (folder, reset_grid_to_top)
        ),
    )
    monkeypatch.setattr(
        window, "_start_folder_watcher", lambda: start_calls.append("start")
    )

    target_dir = "/photos/root/20260329_trip/CARD"
    window._begin_workspace_bulk_refresh([target_dir])
    window._finish_workspace_bulk_refresh([target_dir], copied_count=5)

    assert stop_calls == ["stop"]
    assert load_calls == [("/photos/root", False)]
    assert start_calls == []
    assert window._bulk_workspace_watcher_suspended is False


def test_workspace_bulk_refresh_overlap_zero_files_restarts_watcher_without_reload(
    window: MainWindow, monkeypatch
):
    stop_calls: list[str] = []
    load_calls: list[tuple[str, bool]] = []
    start_calls: list[str] = []
    scroll_calls: list[int] = []

    monkeypatch.setattr(window, "_stop_folder_watcher", lambda: stop_calls.append("stop"))
    monkeypatch.setattr(
        window,
        "_load_folder",
        lambda folder, *, reset_grid_to_top=False: load_calls.append(
            (folder, reset_grid_to_top)
        ),
    )
    monkeypatch.setattr(
        window, "_start_folder_watcher", lambda: start_calls.append("start")
    )
    monkeypatch.setattr(window.grid, "on_scroll", lambda value: scroll_calls.append(value))

    target_dir = "/photos/root/20260329_trip/CARD"
    window._begin_workspace_bulk_refresh([target_dir])
    window._finish_workspace_bulk_refresh([target_dir], copied_count=0)

    assert stop_calls == ["stop"]
    assert load_calls == []
    assert start_calls == ["start"]
    assert scroll_calls == []
    assert window._bulk_workspace_watcher_suspended is False


def test_workspace_bulk_refresh_non_overlapping_targets_do_not_touch_workspace(
    window: MainWindow, monkeypatch
):
    stop_calls: list[str] = []
    load_calls: list[tuple[str, bool]] = []
    start_calls: list[str] = []
    scroll_calls: list[int] = []

    monkeypatch.setattr(window, "_stop_folder_watcher", lambda: stop_calls.append("stop"))
    monkeypatch.setattr(
        window,
        "_load_folder",
        lambda folder, *, reset_grid_to_top=False: load_calls.append(
            (folder, reset_grid_to_top)
        ),
    )
    monkeypatch.setattr(
        window, "_start_folder_watcher", lambda: start_calls.append("start")
    )
    monkeypatch.setattr(window.grid, "on_scroll", lambda value: scroll_calls.append(value))

    target_dir = "/outside/root/20260329_trip/CARD"
    window._begin_workspace_bulk_refresh([target_dir])
    window._finish_workspace_bulk_refresh([target_dir], copied_count=4)

    assert stop_calls == []
    assert load_calls == []
    assert start_calls == []
    assert scroll_calls == []
    assert window._bulk_workspace_watcher_suspended is False


def test_workspace_bulk_refresh_reload_forces_current_viewport_render_pass(
    window: MainWindow, monkeypatch
):
    stop_calls: list[str] = []
    load_calls: list[tuple[str, bool]] = []
    scroll_calls: list[int] = []

    window.grid.scrollbar.setRange(0, 10)
    window.grid.scrollbar.setValue(4)

    monkeypatch.setattr(window, "_stop_folder_watcher", lambda: stop_calls.append("stop"))
    monkeypatch.setattr(
        window,
        "_load_folder",
        lambda folder, *, reset_grid_to_top=False: load_calls.append(
            (folder, reset_grid_to_top)
        ),
    )
    monkeypatch.setattr(window.grid, "on_scroll", lambda value: scroll_calls.append(value))

    target_dir = "/photos/root/20260329_trip/CARD"
    window._begin_workspace_bulk_refresh([target_dir])
    window._finish_workspace_bulk_refresh([target_dir], copied_count=2)

    assert stop_calls == ["stop"]
    assert load_calls == [("/photos/root", False)]
    assert scroll_calls == [4]
