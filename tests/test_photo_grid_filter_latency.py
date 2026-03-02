"""Tests for filter-related grid latency optimizations."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.grid.photo_grid import PhotoGrid
from piqopiqo.model import ImageItem
from piqopiqo.ssf.settings_state import init_qsettings_store


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-grid-filter-latency-{uuid.uuid4().hex}")
    return app


def _item(path: str, *, state: int = 0) -> ImageItem:
    return ImageItem(
        path=path,
        name=path.split("/")[-1],
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        state=state,
    )


def test_fast_first_paint_renders_without_hq_then_upgrades(qapp, monkeypatch):
    monkeypatch.setenv("PIQO_GRID_HQ_THUMB_LOAD_DELAY_MS", "1")
    init_qsettings_store(dyn=True)

    grid = PhotoGrid()
    grid._rebuild_grid(1, 1)

    calls: list[bool] = []

    def _render(_start_row: int, *, allow_hq: bool) -> None:
        calls.append(allow_hq)

    monkeypatch.setattr(grid, "_render", _render)
    grid.set_data([_item("/tmp/a.jpg", state=2)], fast_first_paint=True)
    assert calls and calls[0] is False

    deadline = time.monotonic() + 0.5
    while len(calls) < 2 and time.monotonic() < deadline:
        qapp.processEvents()

    assert len(calls) >= 2
    assert calls[-1] is True


def test_programmatic_scroll_keeps_hq_disabled_during_fast_first(qapp, monkeypatch):
    monkeypatch.setenv("PIQO_GRID_HQ_THUMB_LOAD_DELAY_MS", "5000")
    init_qsettings_store(dyn=True)

    grid = PhotoGrid()
    grid._rebuild_grid(1, 1)

    monkeypatch.setattr(grid, "_render", lambda *_args, **_kwargs: None)
    grid.set_data([_item("/tmp/a.jpg", state=2)], fast_first_paint=True)
    assert grid._fast_first_paint_active is True
    assert grid._hq_display_enabled is False

    grid._suppress_scroll_navigation_activity = True
    try:
        grid.on_scroll(0)
    finally:
        grid._suppress_scroll_navigation_activity = False

    assert grid._hq_display_enabled is False


def test_set_data_avoids_duplicate_render_when_scrollbar_is_clamped(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    grid._rebuild_grid(1, 1)

    grid.set_data([_item(f"/tmp/{i}.jpg") for i in range(6)])
    qapp.processEvents()
    grid.scrollbar.setValue(5)
    qapp.processEvents()

    calls = {"count": 0}

    def _render(_start_row: int, *, allow_hq: bool) -> None:
        calls["count"] += 1

    monkeypatch.setattr(grid, "_render", _render)
    grid.set_data([_item(f"/tmp/{i}.jpg") for i in range(2)])

    # One render from on_scroll(valueChanged) during scrollbar clamping.
    assert calls["count"] == 1


def test_sync_item_state_skips_disk_probe_when_cache_state_not_dirty(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    item = _item("/tmp/a.jpg", state=2)
    item._cache_state_dirty = False

    calls = {"count": 0}

    def _exists(_self: Path) -> bool:
        calls["count"] += 1
        return False

    monkeypatch.setattr(Path, "exists", _exists)
    grid._sync_item_state_from_cache(item)
    assert calls["count"] == 0

    item._cache_state_dirty = True
    grid._sync_item_state_from_cache(item)
    assert calls["count"] > 0
    assert item._cache_state_dirty is False


def test_fast_first_render_skips_hq_eviction_to_avoid_hq_flash(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    grid._rebuild_grid(1, 1)
    grid.set_data([_item(f"/tmp/{i}.jpg", state=2) for i in range(6)])

    monkeypatch.setattr(grid, "_sync_item_state_from_cache", lambda _item: None)
    monkeypatch.setattr(
        grid, "_ensure_display_pixmap_loaded", lambda _item, *, allow_hq: None
    )

    hq_evict_calls = {"count": 0}

    def _record_hq_evict(_start: int, _end: int) -> None:
        hq_evict_calls["count"] += 1

    monkeypatch.setattr(grid, "_evict_hq_pixmaps_outside", _record_hq_evict)

    grid._fast_first_paint_active = True
    grid._render(0, allow_hq=False)
    assert hq_evict_calls["count"] == 0

    grid._fast_first_paint_active = False
    grid._render(0, allow_hq=False)
    assert hq_evict_calls["count"] == 1


def test_set_num_columns_recomputes_rows_without_waiting_for_resize(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    grid = PhotoGrid()
    grid.resize(900, 700)
    grid.show()
    qapp.processEvents()
    grid.set_data([_item(f"/tmp/{i}.jpg") for i in range(200)])
    qapp.processEvents()

    grid.set_num_columns(10)
    qapp.processEvents()
    rows_after_change = grid.n_rows

    grid.resize(901, 700)
    qapp.processEvents()
    grid.resize(900, 700)
    qapp.processEvents()

    assert grid.n_rows == rows_after_change


def test_num_columns_is_clamped_to_runtime_bounds(qapp, monkeypatch):
    monkeypatch.setenv("PIQO_GRID_NUM_COLUMNS_MIN", "3")
    monkeypatch.setenv("PIQO_GRID_NUM_COLUMNS_MAX", "10")
    monkeypatch.setenv("PIQO_NUM_COLUMNS", "2")
    init_qsettings_store(dyn=True)

    grid = PhotoGrid()
    assert grid.n_cols == 3

    grid.set_num_columns(99)
    assert grid.n_cols == 10

    grid.set_num_columns(-5)
    assert grid.n_cols == 3
