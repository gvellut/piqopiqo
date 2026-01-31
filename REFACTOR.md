# PiqoPiqo Refactoring Plan

## Overview

Refactor the codebase into submodules, split large files, and eliminate `pan_logic.py` by integrating its logic properly.

## Main Components to Address

| Component | Current Location | Lines | Action |
|-----------|-----------------|-------|--------|
| MainWindow | photo_grid.py | ~550 | Move to `main_window.py` |
| PagedPhotoGrid | photo_grid.py | ~330 | Move to `grid/photo_grid.py` |
| PhotoCell | photo_grid.py | ~160 | Move to `grid/photo_cell.py` |
| FullscreenOverlay | fullscreen_overlay.py | ~1230 | Refactor to use `fullscreen/pan.py` |
| EditPanel + widgets | edit_panel.py | ~743 | Split widgets to `panels/edit_widgets.py` |
| ExifPanel | exif_man.py | ~100 | Move to `panels/exif_panel.py` |
| pan_logic.py | root | 166 | DELETE - duplicated in fullscreen_overlay |

## Proposed Structure

```
src/piqopiqo/
├── __main__.py              # Entry point (update imports)
├── config.py                # Unchanged
├── model.py                 # Unchanged
├── db_fields.py             # Unchanged
├── utils.py                 # Unchanged
├── support.py               # Unchanged
├── shortcuts.py             # Unchanged
├── metadata_db.py           # Unchanged
├── exif_loader.py           # Unchanged
├── thumb_man.py             # Unchanged
├── exif_man.py              # ExifManager only (ExifPanel moved)
├── main_window.py           # NEW: MainWindow class
│
├── components/              # NEW: Shared components
│   ├── __init__.py
│   ├── ellided_label.py     # From components.py
│   ├── label_utils.py       # NEW: _get_label_color() (shared)
│   └── save_workers.py      # NEW: Unified MetadataSaveWorker
│
├── grid/                    # NEW: Grid submodule
│   ├── __init__.py
│   ├── photo_cell.py        # PhotoCell
│   └── photo_grid.py        # PagedPhotoGrid
│
├── panels/                  # NEW: Panel submodule
│   ├── __init__.py
│   ├── edit_panel.py        # EditPanel
│   ├── edit_widgets.py      # NEW: TitleEdit, DescriptionEdit, etc.
│   ├── exif_panel.py        # ExifPanel (from exif_man.py)
│   ├── filter_panel.py      # FolderFilterPanel
│   └── status_bar.py        # LoadingStatusBar, ErrorListDialog
│
├── fullscreen/              # NEW: Fullscreen submodule
│   ├── __init__.py
│   ├── overlay.py           # FullscreenOverlay (refactored)
│   ├── pan.py               # Pure pan functions (testable)
│   └── zoom.py              # ZoomState, ZoomDirection, zoom functions
│
└── platform/                # Unchanged
    ├── __init__.py
    └── macos.py
```

## Implementation Phases

### Phase 1: Create Shared Components
1. Create `components/` directory
2. Move `EllidedLabel` to `components/ellided_label.py`
3. Extract `_get_label_color()` to `components/label_utils.py` (used by photo_grid + fullscreen)
4. Unify `_LabelSaveWorker` + `DBSaveWorker` into `components/save_workers.py`
5. Delete old `components.py`

### Phase 2: Split Photo Grid
1. Create `grid/` directory
2. Create `grid/photo_cell.py` with PhotoCell class
3. Create `grid/photo_grid.py` with PagedPhotoGrid class
4. Create `main_window.py` with MainWindow class
5. Delete old `photo_grid.py`

### Phase 3: Create Panels Module
1. Create `panels/` directory
2. Extract input widgets to `panels/edit_widgets.py`
3. Move `EditPanel` to `panels/edit_panel.py`
4. Move `ExifPanel` to `panels/exif_panel.py` (keep ExifManager in exif_man.py)
5. Move `FolderFilterPanel` to `panels/filter_panel.py`
6. Move `LoadingStatusBar` + `ErrorListDialog` to `panels/status_bar.py`

### Phase 4: Refactor Fullscreen (Eliminate pan_logic.py)
1. Create `fullscreen/` directory
2. Create `fullscreen/pan.py` with pure pan calculation functions
3. Create `fullscreen/zoom.py` with ZoomState, ZoomDirection, zoom helpers
4. Refactor `FullscreenOverlay` to use these modules (no duplication)
5. Delete `pan_logic.py` (currently dead code - not imported by overlay)
6. Update `tests/test_pan_logic.py` to import from `fullscreen.pan`

### Phase 5: Update Imports
1. Update `__main__.py` to import from `main_window`
2. Update all cross-module imports
3. Add re-exports in `__init__.py` for backward compatibility

## Key Refactoring: pan_logic.py

**Current Problem**: `pan_logic.py` contains pure functions for testing, but `fullscreen_overlay.py` duplicates all this logic in methods like:
- `_get_current_space_per_side()` duplicates `calculate_current_space()`
- `_get_effective_empty_space_per_side()` duplicates `calculate_effective_space_per_side()`
- etc.

**Solution**:
1. Keep pure functions in `fullscreen/pan.py` (testable without Qt)
2. Make `FullscreenOverlay` import and USE these functions
3. Tests import from `fullscreen.pan` instead

Example:
```python
# fullscreen/pan.py - pure function
def calculate_clamp_correction(img_rect, view_size, effective_space) -> tuple[float, float]:
    """Calculate dx, dy to clamp image within bounds."""
    # ... pure calculation logic
    return dx, dy

# fullscreen/overlay.py - uses the function
from piqopiqo.fullscreen.pan import calculate_clamp_correction

def _clamp_pan_smooth(self):
    dx, dy = calculate_clamp_correction(
        self._get_image_rect(),
        (self.width(), self.height()),
        self._get_effective_empty_space_per_side()
    )
    # apply correction
```

## Verification

1. Run existing tests: `uv run pytest tests/`
2. Run the application: `uv run piqopiqo /path/to/images`
3. Test fullscreen zoom/pan navigation
4. Test label shortcuts (1-9, backtick)
5. Test metadata editing in EditPanel
6. Run linting: `ruff check --fix && ruff format`

## Files to Modify/Create

**Create (15 new files):**
- `main_window.py`
- `components/__init__.py`, `ellided_label.py`, `label_utils.py`, `save_workers.py`
- `grid/__init__.py`, `photo_cell.py`, `photo_grid.py`
- `panels/__init__.py`, `edit_widgets.py`, `exif_panel.py`
- `fullscreen/__init__.py`, `overlay.py`, `pan.py`, `zoom.py`

**Move/Refactor:**
- `edit_panel.py` → `panels/edit_panel.py`
- `filter_panel.py` → `panels/filter_panel.py`
- `status_bar.py` → `panels/status_bar.py`
- `fullscreen_overlay.py` → `fullscreen/overlay.py`

**Delete:**
- `photo_grid.py` (split into 3 files)
- `pan_logic.py` (dead code, logic moved to fullscreen/pan.py)
- `components.py` (moved to components/)
