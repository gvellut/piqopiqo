"""Tests for initial folder-load sorting stabilization."""

from __future__ import annotations

from datetime import datetime
import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.background.media_man import FolderPrimingResult
from piqopiqo.main_window import (
    SELECTION_PANEL_DEBOUNCE_MS,
    MainWindow,
    _DeferredTimeTakenLoadResortState,
)
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.model import ImageItem
from piqopiqo.photo_model import SortOrder
from piqopiqo.ssf.settings_state import StateKey, init_qsettings_store, set_state_value


class _SignalStub:
    def connect(self, *_args, **_kwargs) -> None:
        return None


class _MediaManagerStub:
    next_priming_result = FolderPrimingResult({}, set())
    has_errors_value = False

    def __init__(self, *_args, **_kwargs):
        self.thumb_ready = _SignalStub()
        self.thumb_progress_updated = _SignalStub()
        self.editable_ready = _SignalStub()
        self.editable_terminal = _SignalStub()
        self.exif_progress_updated = _SignalStub()
        self.panel_fields_ready = _SignalStub()
        self.all_completed = _SignalStub()
        self.reset_calls: list[tuple[list[str], list[str]]] = []
        self.pause_calls = 0
        self.resume_calls = 0

    def reset_for_folder(
        self, file_paths: list[str], source_folders: list[str]
    ) -> FolderPrimingResult:
        self.reset_calls.append((list(file_paths), list(source_folders)))
        return self.next_priming_result

    def pause_processing(self) -> None:
        self.pause_calls += 1

    def resume_processing(self) -> None:
        self.resume_calls += 1

    def update_visible(self, _visible_paths_in_order: list[str]) -> None:
        return None

    def has_errors(self) -> bool:
        return bool(self.has_errors_value)

    def add_files(self, _file_paths: list[str]) -> None:
        return None

    def remove_files(self, _file_paths: list[str]) -> None:
        return None

    def request_thumbnail(self, _file_path: str) -> None:
        return None

    def regenerate_thumbnails(self, _file_paths: list[str]) -> None:
        return None

    def refresh_files(self, _file_paths: list[str]) -> None:
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
    core.setApplicationName(f"piqopiqo-test-load-sort-{uuid.uuid4().hex}")
    return app


def _image(path: str, name: str) -> dict:
    return {
        "path": path,
        "name": name,
        "created": "2020-01-01 00:00:00",
        "source_folder": "/photos",
        "state": 0,
    }


def test_startup_load_uses_cached_metadata_for_first_time_taken_sort(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    set_state_value(StateKey.SORT_ORDER, SortOrder.TIME_TAKEN.name)

    _MediaManagerStub.next_priming_result = FolderPrimingResult(
        cached_editable_metadata={
            "/photos/a.jpg": {DBFields.TIME_TAKEN: datetime(2026, 1, 1, 12, 0, 0)},
            "/photos/b.jpg": {DBFields.TIME_TAKEN: datetime(2026, 1, 1, 10, 0, 0)},
        },
        missing_editable_paths=set(),
    )
    monkeypatch.setattr("piqopiqo.main_window.MediaManager", _MediaManagerStub)
    monkeypatch.setattr(
        "piqopiqo.main_window.refresh_main_screen_color_space_cache_macos",
        lambda: None,
    )

    window = MainWindow(
        [_image("/photos/a.jpg", "a.jpg"), _image("/photos/b.jpg", "b.jpg")],
        ["/photos"],
        None,
    )
    try:
        assert [item.path for item in window.images_data] == [
            "/photos/b.jpg",
            "/photos/a.jpg",
        ]
        assert window._deferred_time_taken_load_resort_state is None
        assert window.media_manager.reset_calls == [
            (["/photos/a.jpg", "/photos/b.jpg"], ["/photos"])
        ]
        assert window.media_manager.pause_calls == 1
        assert window.media_manager.resume_calls == 1
    finally:
        window.close()


class _FakeDeferredChunkWindow:
    def __init__(
        self,
        *,
        batch_size: int,
        processed: int = 0,
        pending_paths: set[str] | None = None,
        dirty_paths: set[str] | None = None,
        visible_paths: list[str] | None = None,
    ):
        self._deferred_time_taken_load_resort_state = _DeferredTimeTakenLoadResortState(
            pending_paths=pending_paths or {"/photos/a.jpg", "/photos/b.jpg"},
            processed_since_last_resort=processed,
            batch_size=batch_size,
            dirty_paths=dirty_paths or set(),
        )
        self.photo_model = type(
            "PhotoModel", (), {"sort_order": SortOrder.TIME_TAKEN}
        )()
        self._last_visible_paths = list(visible_paths or [])
        self.media_manager = type(
            "MediaManager", (), {"update_visible": lambda _self, _paths: None}
        )()
        self.calls: list[str] = []

    def _run_deferred_time_taken_load_resort(self, *, source: str) -> None:
        self.calls.append(source)

    def _maybe_flush_deferred_time_taken_visible_resort(self, *, source: str) -> bool:
        return MainWindow._maybe_flush_deferred_time_taken_visible_resort(
            self,
            source=source,
        )


def test_editable_terminal_resorts_after_batch_threshold():
    fake_window = _FakeDeferredChunkWindow(
        batch_size=100,
        processed=99,
        dirty_paths={"/photos/a.jpg"},
    )

    MainWindow._on_editable_terminal(fake_window, "/photos/a.jpg", True)

    assert fake_window.calls == ["folder_load_chunk"]
    state = fake_window._deferred_time_taken_load_resort_state
    assert state is not None
    assert state.pending_paths == {"/photos/b.jpg"}
    assert state.dirty_paths == set()
    assert state.processed_since_last_resort == 0


def test_editable_terminal_batch_size_zero_waits_for_completion():
    fake_window = _FakeDeferredChunkWindow(batch_size=0)

    MainWindow._on_editable_terminal(fake_window, "/photos/a.jpg", False)

    assert fake_window.calls == []
    state = fake_window._deferred_time_taken_load_resort_state
    assert state is not None
    assert state.pending_paths == {"/photos/b.jpg"}
    assert state.processed_since_last_resort == 1


def test_deferred_visible_area_resorts_when_visible_metadata_is_loaded():
    fake_window = _FakeDeferredChunkWindow(
        batch_size=100,
        processed=1,
        pending_paths={"/photos/b.jpg", "/photos/c.jpg"},
        dirty_paths={"/photos/a.jpg", "/photos/b.jpg"},
        visible_paths=["/photos/a.jpg", "/photos/b.jpg"],
    )

    MainWindow._on_editable_terminal(fake_window, "/photos/b.jpg", True)

    assert fake_window.calls == ["folder_load_visible"]
    state = fake_window._deferred_time_taken_load_resort_state
    assert state is not None
    assert state.pending_paths == {"/photos/c.jpg"}
    assert state.dirty_paths == set()
    assert state.processed_since_last_resort == 0


def test_visible_path_change_resorts_when_new_visible_area_is_loaded():
    fake_window = _FakeDeferredChunkWindow(
        batch_size=100,
        pending_paths={"/photos/c.jpg"},
        dirty_paths={"/photos/a.jpg", "/photos/b.jpg"},
    )

    MainWindow._on_visible_paths_changed(
        fake_window,
        ["/photos/a.jpg", "/photos/b.jpg"],
    )

    assert fake_window.calls == ["folder_load_visible"]
    state = fake_window._deferred_time_taken_load_resort_state
    assert state is not None
    assert state.dirty_paths == set()
    assert state.processed_since_last_resort == 0


def test_time_taken_load_resort_batch_size_normalization_clamps_invalid_values():
    assert MainWindow._normalize_time_taken_load_resort_batch_size(100) == 100
    assert MainWindow._normalize_time_taken_load_resort_batch_size(-5) == 0
    assert MainWindow._normalize_time_taken_load_resort_batch_size("bad") == 0


class _FakeStatusBar:
    def __init__(self):
        self.values: list[bool] = []

    def set_has_errors(self, value: bool) -> None:
        self.values.append(bool(value))


class _FakeMediaManagerErrors:
    def __init__(self, has_errors: bool):
        self._has_errors = bool(has_errors)

    def has_errors(self) -> bool:
        return self._has_errors


class _FakeLoadingCompleteWindow:
    def __init__(self):
        self._deferred_time_taken_load_resort_state = _DeferredTimeTakenLoadResortState(
            pending_paths=set(),
            processed_since_last_resort=3,
            batch_size=0,
        )
        self.media_manager = _FakeMediaManagerErrors(True)
        self.status_bar = _FakeStatusBar()
        self.calls: list[str] = []

    def _run_deferred_time_taken_load_resort(self, *, source: str) -> None:
        self.calls.append(source)


def test_loading_complete_runs_final_resort_and_clears_state():
    fake_window = _FakeLoadingCompleteWindow()

    MainWindow._on_loading_complete(fake_window)

    assert fake_window.calls == ["folder_load_complete"]
    assert fake_window._deferred_time_taken_load_resort_state is None
    assert fake_window.status_bar.values == [True]


class _FakeRunDeferredWindow:
    def __init__(self):
        self.photo_model = type(
            "PhotoModel", (), {"sort_order": SortOrder.TIME_TAKEN}
        )()
        self.calls: list[object] = []

    def _capture_grid_viewport_snapshot(self) -> dict:
        snapshot = {
            "selected_visible_paths": ["/photos/keep.jpg"],
            "visible_paths": ["/photos/fallback.jpg"],
        }
        self.calls.append(("capture", snapshot))
        return snapshot

    def _execute_metadata_model_sync(
        self,
        changed_fields: set[str],
        *,
        source: str,
        rebind_fullscreen_loop: bool,
    ) -> None:
        self.calls.append((
            "execute",
            set(changed_fields),
            source,
            rebind_fullscreen_loop,
        ))

    def _restore_grid_viewport_after_sort_change(self, snapshot: dict) -> None:
        self.calls.append(("restore", snapshot))


def test_run_deferred_time_taken_load_resort_restores_viewport():
    fake_window = _FakeRunDeferredWindow()

    MainWindow._run_deferred_time_taken_load_resort(
        fake_window,
        source="folder_load_chunk",
    )

    assert fake_window.calls == [
        (
            "capture",
            {
                "selected_visible_paths": ["/photos/keep.jpg"],
                "visible_paths": ["/photos/fallback.jpg"],
            },
        ),
        ("execute", {DBFields.TIME_TAKEN}, "folder_load_chunk", False),
        (
            "restore",
            {
                "selected_visible_paths": ["/photos/keep.jpg"],
                "visible_paths": ["/photos/fallback.jpg"],
            },
        ),
    ]


class _SelectionRefreshTimer:
    def __init__(self):
        self.active = False
        self.starts: list[int] = []
        self.stop_count = 0

    def isActive(self) -> bool:
        return self.active

    def start(self, delay_ms: int) -> None:
        self.active = True
        self.starts.append(delay_ms)

    def stop(self) -> None:
        self.active = False
        self.stop_count += 1


class _SelectionRefreshStatusBar:
    def __init__(self):
        self.active = False
        self.calls: list[bool] = []

    def set_selection_progress_active(self, active: bool) -> None:
        active = bool(active)
        if self.active == active:
            return
        self.active = active
        self.calls.append(active)


class _SelectionRefreshPanel:
    def __init__(self):
        self.pending_counts: list[int] = []
        self.clear_count = 0
        self.update_calls: list[list[ImageItem]] = []

    def show_selection_pending(self, count: int) -> None:
        self.pending_counts.append(int(count))

    def clear_selection_pending(self) -> None:
        self.clear_count += 1

    def update_for_selection(self, items: list[ImageItem]) -> None:
        self.update_calls.append(list(items))

    def update_exif(self, items: list[ImageItem]) -> None:
        self.update_calls.append(list(items))


class _SelectionRefreshMediaManager:
    def __init__(self):
        self.panel_loads: list[list[str]] = []

    def ensure_panel_fields_loaded_from_db(self, paths: list[str]) -> None:
        self.panel_loads.append(list(paths))


class _SelectionRefreshPhotoModel:
    def __init__(self, items: list[ImageItem]):
        self._items = items

    def get_selected_photos(self) -> list[ImageItem]:
        return [item for item in self._items if item.is_selected]


class _SelectionRefreshWindow:
    def __init__(self, items: list[ImageItem]):
        self.images_data = items
        self.photo_model = _SelectionRefreshPhotoModel(items)
        self.status_bar = _SelectionRefreshStatusBar()
        self.edit_panel = _SelectionRefreshPanel()
        self.exif_panel = _SelectionRefreshPanel()
        self.media_manager = _SelectionRefreshMediaManager()
        self._selected_paths_cache: set[str] = set()
        self._selected_count_cache = 0
        self._selection_panel_refresh_serial = 0
        self._selection_panel_refresh_scheduled_serial: int | None = None
        self._selection_panel_refresh_in_progress = False
        self._selection_panel_refresh_timer = _SelectionRefreshTimer()
        self.status_count_updates = 0

    def _update_status_bar_count(self) -> None:
        self.status_count_updates += 1

    def _set_selected_cache_from_indices(self, selected_indices) -> int:
        return MainWindow._set_selected_cache_from_indices(self, selected_indices)

    def _set_selected_cache_from_items(self, items: list[ImageItem]) -> None:
        MainWindow._set_selected_cache_from_items(self, items)

    def _set_selection_refresh_progress_active(self, active: bool) -> None:
        MainWindow._set_selection_refresh_progress_active(self, active)

    def _show_selection_panels_pending(self, count: int) -> None:
        MainWindow._show_selection_panels_pending(self, count)

    def _clear_selection_panels_pending(self) -> None:
        MainWindow._clear_selection_panels_pending(self)

    def _schedule_deferred_selection_panel_refresh(self) -> None:
        MainWindow._schedule_deferred_selection_panel_refresh(self)

    def _should_defer_selection_panel_refresh(
        self,
        selected_count: int | None = None,
        *,
        include_active_timer: bool = True,
    ) -> bool:
        return MainWindow._should_defer_selection_panel_refresh(
            self,
            selected_count,
            include_active_timer=include_active_timer,
        )

    def _cancel_deferred_selection_panel_refresh(self) -> None:
        MainWindow._cancel_deferred_selection_panel_refresh(self)

    def _apply_or_defer_panel_refresh(
        self,
        *,
        selected_items: list[ImageItem] | None = None,
        selected_count: int | None = None,
        coalesce_with_active_timer: bool = False,
    ) -> None:
        MainWindow._apply_or_defer_panel_refresh(
            self,
            selected_items=selected_items,
            selected_count=selected_count,
            coalesce_with_active_timer=coalesce_with_active_timer,
        )

    def _update_panels_for_selection(self, items: list[ImageItem]) -> None:
        MainWindow._update_panels_for_selection(self, items)


def test_repeated_large_selection_defers_panels_until_single_flush():
    items = []
    for index in range(201):
        item = ImageItem(
            path=f"/photos/{index}.jpg",
            name=f"{index}.jpg",
            created="2020-01-01 00:00:00",
            source_folder="/photos",
            db_metadata={DBFields.KEYWORDS: "same"},
        )
        item.is_selected = True
        item.exif_data = {}
        items.append(item)
    selected_indices = set(range(len(items)))
    window = _SelectionRefreshWindow(items)

    MainWindow.on_selection_changed(window, selected_indices)
    MainWindow.on_selection_changed(window, selected_indices)

    assert window.status_bar.calls == [True]
    assert window._selection_panel_refresh_timer.starts == [
        SELECTION_PANEL_DEBOUNCE_MS,
        SELECTION_PANEL_DEBOUNCE_MS,
    ]
    assert window.edit_panel.update_calls == []
    assert window.exif_panel.update_calls == []

    window._selection_panel_refresh_timer.active = False
    MainWindow._flush_deferred_selection_panel_refresh(window)

    assert window.status_bar.calls == [True, False]
    assert len(window.edit_panel.update_calls) == 1
    assert len(window.exif_panel.update_calls) == 1
    assert len(window.edit_panel.update_calls[0]) == len(items)
    assert len(window.media_manager.panel_loads[0]) == len(items)


class _FakeGrid:
    def __init__(self):
        self.refreshed: list[int] = []

    def refresh_item(self, index: int) -> None:
        self.refreshed.append(index)


class _FakeEditableReadyWindow:
    def __init__(self):
        item = ImageItem(
            path="/photos/a.jpg",
            name="a.jpg",
            created="2020-01-01 00:00:00",
            source_folder="/photos",
            state=0,
        )
        item._global_index = 4
        self._items_by_path = {item.path: item}
        self.grid = _FakeGrid()
        self.edit_panel = None
        self._selected_paths_cache: set[str] = set()
        self.photo_model = type(
            "PhotoModel", (), {"sort_order": SortOrder.TIME_TAKEN}
        )()
        self._current_filter = None
        self._pending_scheduled_sync_fields: set[str] = set()
        self._model_refresh_scheduled = False

    def _should_defer_selection_panel_refresh(self) -> bool:
        return False

    def _get_selected_items(self) -> list[ImageItem]:
        return []

    def _should_defer_time_taken_load_resort_for(self, _file_path: str) -> bool:
        return False

    def _flush_scheduled_model_sync(self) -> None:
        return None


class _FakeDeferredEditableReadyWindow(_FakeEditableReadyWindow):
    def __init__(self):
        super().__init__()
        self._deferred_time_taken_load_resort_state = _DeferredTimeTakenLoadResortState(
            pending_paths={"/photos/a.jpg"},
            processed_since_last_resort=0,
            batch_size=100,
        )

    def _should_defer_time_taken_load_resort_for(self, file_path: str) -> bool:
        return MainWindow._should_defer_time_taken_load_resort_for(self, file_path)

    def _mark_deferred_time_taken_loaded(self, file_path: str) -> None:
        MainWindow._mark_deferred_time_taken_loaded(self, file_path)


def test_editable_ready_still_schedules_immediate_resort_without_deferred_state(
    monkeypatch,
):
    fake_window = _FakeEditableReadyWindow()
    single_shot_calls: list[int] = []
    monkeypatch.setattr(
        "piqopiqo.main_window.QTimer.singleShot",
        lambda delay_ms, _callback: single_shot_calls.append(delay_ms),
    )

    MainWindow._on_editable_ready(
        fake_window,
        "/photos/a.jpg",
        {DBFields.TIME_TAKEN: datetime(2026, 1, 1, 10, 0, 0)},
    )

    assert fake_window.grid.refreshed == [4]
    assert fake_window._model_refresh_scheduled is True
    assert fake_window._pending_scheduled_sync_fields == {
        DBFields.TIME_TAKEN,
        DBFields.TITLE,
        DBFields.KEYWORDS,
        DBFields.LABEL,
    }
    assert single_shot_calls == [50]


def test_deferred_editable_ready_marks_dirty_without_immediate_resort(monkeypatch):
    fake_window = _FakeDeferredEditableReadyWindow()
    single_shot_calls: list[int] = []
    monkeypatch.setattr(
        "piqopiqo.main_window.QTimer.singleShot",
        lambda delay_ms, _callback: single_shot_calls.append(delay_ms),
    )

    MainWindow._on_editable_ready(
        fake_window,
        "/photos/a.jpg",
        {DBFields.TIME_TAKEN: datetime(2026, 1, 1, 10, 0, 0)},
    )

    state = fake_window._deferred_time_taken_load_resort_state
    assert state is not None
    assert state.dirty_paths == {"/photos/a.jpg"}
    assert fake_window._model_refresh_scheduled is False
    assert fake_window._pending_scheduled_sync_fields == set()
    assert single_shot_calls == []
