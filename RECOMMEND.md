# PiqoPiqo — Recommendations

## 1. Module & File Layout

### 1.1 Split `main_window.py` (2 362 lines)

This file is the single largest risk to maintainability. It mixes layout construction, signal wiring, business logic, menu actions, and tool orchestration. Recommended split:

| New Module | Responsibility | Approx. Lines |
|------------|---------------|---------------|
| `main_window.py` | Window construction, layout, splitters | ~300 |
| `main_controller.py` | Signal wiring, selection handling, panel sync | ~500 |
| `menu_actions.py` | Menu bar creation, action handlers | ~400 |
| `workspace_controller.py` | Open folder, reload, cleanup, folder watcher integration | ~300 |
| `tools_controller.py` | Tool invocation (GPX, Flickr, Save EXIF, Copy SD, Manual Lens) | ~400 |
| `fullscreen_controller.py` | Fullscreen enter/exit, navigation delegation | ~200 |

All controllers would hold a reference to the same `MainWindow` instance (or a slim context object) and register their signals in a deterministic order.

### 1.2 Move GPS/EXIF Parsing Out of `metadata_db.py`

`metadata_db.py` currently contains `exif_gps_to_decimal()`, `parse_exif_gps()`, `parse_exif_datetime()` — these are pure parsing functions unrelated to SQLite. Move them to a new `metadata/exif_parse.py` (or into `metadata/db_fields.py` where the field mappings already live).

### 1.3 Consolidate Model Files

- `model.py` and `photo_model.py` could be merged into a single `models/` package with `image_item.py`, `photo_list.py`, `filter.py`, `labels.py`. This would make imports clearer and allow each model class to grow independently.

### 1.4 Settings Panel → Proper Package

`settings_panel/` is already a package, but `ssf/settings_state.py` is a 700+ line enum dump. Consider splitting:
- `ssf/keys.py` — Enum definitions only
- `ssf/accessors.py` — `get_*` / `set_*` wrapper functions
- `ssf/defaults.py` — Default value declarations

### 1.5 Flatten `tools/`

The `tools/flickr_upload/` and `tools/gpx2exif/` sub-packages each have 8–9 files, some quite small. They are well-isolated, but `tools/copy_sd.py`, `tools/save_exif.py`, and `tools/manual_lens.py` are loose files. Consider giving each tool its own sub-package for consistency, or at minimum grouping the loose files under `tools/misc/`.

---

## 2. Reliability & Recovery

### 2.1 Missing or Deleted Cache Directory

**Current state:** If the cache base directory disappears (e.g. external drive unplugged, manual deletion), the app will crash on first thumbnail or DB access with an unhandled `FileNotFoundError` or `sqlite3.OperationalError`.

**Recommendation:**
- At startup, verify the cache base exists and is writable. If not, show `MandatorySettingsDialog` again.
- Wrap every cache-write path (`generate_hq_thumbnail`, `MetadataDBManager._get_connection`) with a guard that recreates the directory tree. Use `os.makedirs(exist_ok=True)` liberally.
- Add a periodic health-check timer (e.g. every 60 s) that verifies the cache volume is still mounted, and gracefully degrade (disable writes, show banner) rather than crash.

### 2.2 Source Folder Deleted or Renamed

**Current state:** `FolderWatcher` monitors for file changes, but if the entire root folder is deleted or renamed while the app is running, the behaviour is undefined.

**Recommendation:**
- `FolderWatcher` should catch `FileNotFoundError` / `OSError` from `watchfiles` and emit a `folder_lost` signal.
- `MainWindow` should handle this by showing a non-modal dialog ("The folder /path/to/photos is no longer available. Reopen or close workspace?") and disabling writes.
- On reopen, reconcile: any images whose paths no longer exist should be marked as "missing" in the grid (greyed-out cell, strikethrough filename) rather than silently removed.

### 2.3 Disk Unplugged / Volume Unmounted

This is the source-folder-deleted case plus the cache-directory-gone case simultaneously.

**Recommendation:**
- Combine the two guards above.
- Before every file I/O, check `os.path.exists()` on the volume mount point (not the file itself — too slow for large sets). Cache the mount-point check result for a short TTL.
- Use `QFileSystemWatcher` on the mount point parent (e.g. `/Volumes`) to detect volume events immediately on macOS.

### 2.4 Corrupt or Locked SQLite Database

**Current state:** `MetadataDBManager` uses per-thread connections but no explicit `PRAGMA journal_mode` or `PRAGMA wal_checkpoint`. If the app crashes mid-write, the journal file may be left behind and the next open may encounter a locked or corrupt DB.

**Recommendation:**
- Set `PRAGMA journal_mode=WAL` on every connection open. WAL mode allows concurrent reads during writes and is more crash-resilient.
- On `sqlite3.DatabaseError` at open time, attempt `PRAGMA integrity_check`. If it fails, rename the corrupt DB to `.corrupt.{timestamp}` and create a fresh one — metadata can be rebuilt from EXIF.
- Add a "Repair workspace" action in `WorkspacePropertiesDialog` that rebuilds the DB from EXIF data.

### 2.5 Individual Files Removed While App Is Running

**Current state:** `FolderWatcher` emits `changes_detected` which triggers add/remove, but the grid cell may still hold a stale reference.

**Recommendation:**
- On file removal signal, immediately set `ImageItem.pixmap = None` and mark the item as "missing" before removal from the model, to avoid paint errors if the grid tries to render between signal and removal.
- If a file is re-created (e.g. overwritten by an editor), detect the modification event and trigger EXIF + thumbnail reload rather than remove + re-add.

### 2.6 exiftool Crashes or Hangs

**Current state:** Workers use pyexiftool which launches a persistent exiftool process. If it crashes, the worker process itself fails.

**Recommendation:**
- Add a per-batch timeout (e.g. 30 s) to the exiftool subprocess. If exceeded, kill the process, log the error, and skip the batch.
- Track consecutive failures per worker. After N failures, restart the worker process.
- Surface errors in the status bar error list rather than silently dropping items.

---

## 3. Missing Features for a Standard macOS App

### 3.1 Must-Have

| Feature | Status | Notes |
|---------|--------|-------|
| **Native toolbar** | Missing | Use `QToolBar` with unified title bar (Qt supports this on macOS). Provides icon-based access to common actions. |
| **Undo/Redo stack** | Partial (label only) | Only `LabelUndoEntry` exists. Title, keyword, coordinate, and time edits have no undo. Use `QUndoStack` with `QUndoCommand` subclasses for all editable fields. |
| **Drag & drop** | Missing | No drag-to-reorder, drag-to-folder, or drag-from-Finder support. Implement `QDrag` on grid cells and `dragEnterEvent`/`dropEvent` on the grid. |
| **Native file open (recent files)** | Missing | macOS apps should populate the "Open Recent" submenu. Use `QSettings` to store recent folders and `NSDocumentController` interop. |
| **App sandboxing** | Missing | Required for Mac App Store distribution. Would need entitlements for file access, network, and the exiftool helper. |
| **Auto-update** | Missing | No Sparkle framework or equivalent. Users must manually download new versions. Consider `sparkle-project/Sparkle` via PyObjC or a custom update-check mechanism. |
| **Crash reporting** | Missing | No crash reporter. Consider `sentry-sdk` or a simple uncaught-exception handler that writes a crash log and offers to send it. |

### 3.2 Nice-to-Have

| Feature | Notes |
|---------|-------|
| **Dock menu** | Right-click on Dock icon → recent folders, current folder name |
| **Touch Bar** (older Macs) | Label shortcuts, zoom, navigate |
| **Quick Look** integration | Register as Quick Look provider for metadata-rich previews |
| **Share menu** | macOS share sheet for selected photos |
| **Spotlight / mdimporter** | Index metadata so Spotlight can search by keyword/title |
| **Services menu** | Register for "Open in PiqoPiqo" system service |
| **Full keyboard access** | Tab between grid, panels, filter. Currently keyboard nav is mostly within grid. |
| **VoiceOver / accessibility** | No `QAccessibleInterface` implementations. Grid cells and panels should expose roles and descriptions. |
| **Dark mode** | No explicit dark-mode stylesheet. Qt partially adapts to system theme, but custom widgets (PhotoCell paint) may not. |
| **Localization** | No `QTranslator` usage. All strings are hardcoded in English. |

---

## 4. Things That Could Be Done Better

### 4.1 Custom Grid vs. `QAbstractItemModel` + `QListView`

The current `PhotoGrid` is a fully custom widget with manual layout, scroll management, and cell recycling. This is a significant maintenance burden and re-implements what Qt's item views already provide.

**Recommendation:** Replace with a `QListView` in `IconMode` backed by a `QAbstractListModel` and a custom `QStyledItemDelegate`. This gives you:
- Free scroll performance and item recycling
- Native rubber-band selection
- Drag-and-drop for free
- Accessibility support
- Keyboard navigation (arrow keys, page up/down, home/end)

The trade-off is less pixel-level control over cell layout, but `QStyledItemDelegate.paint()` provides enough flexibility for thumbnails + metadata text.

### 4.2 `ImageItem` Is a Mutable God Object

`ImageItem` holds file identity, display state (pixmaps), selection state, raw EXIF, and edited metadata all in one `attrs` class (currently `@define(slots=False)` with a TODO to clean up). This makes it hard to reason about lifetimes and ownership.

**Recommendation:** Separate into:
- `PhotoIdentity` — immutable: path, name, source_folder, created
- `PhotoDisplayState` — mutable: pixmaps, state, cache_state_dirty
- `PhotoMetadata` — mutable: db_metadata, exif_data, label

#### Move `is_selected` Out of `ImageItem`

Currently `is_selected` lives as a mutable boolean on every `ImageItem`. It is read and written from three independent locations that must stay in sync:

1. **`PhotoGrid.on_cell_clicked()`** — mutates `item.is_selected` directly on click/ctrl-click/shift-click, then emits `selection_changed(set)`.
2. **`PhotoListModel`** — has its own selection methods (`select_photo`, `toggle_selection`, `select_range`, `clear_selection`) that also mutate the same `item.is_selected`, and emits its own `selection_changed` signal.
3. **`MainWindow`** — reads `item.is_selected` in ~10 places (`_get_selected_items`, `_capture_metadata_reselection_context`, etc.) and maintains a parallel `_selected_paths_cache` set to avoid scanning the full list.

This creates several problems:

- **Dual authority.** Both `PhotoGrid` and `PhotoListModel` mutate the same field. If one forgets to notify the other, UI and model drift apart. Today the grid is the actual source of truth for user clicks, and `MainWindow.on_selection_changed()` syncs the cache — but `PhotoListModel` also exposes write methods that bypass the grid entirely.
- **Linear scans.** Every time selection is queried, someone iterates all items: `[item for item in self.images_data if item.is_selected]`. With 10 000 images this is noticeable, especially during debounced panel refreshes.
- **Filter transitions.** When a filter changes, `PhotoListModel._apply_filter_and_sort()` clears `is_selected` on items that no longer pass the filter. This is correct but fragile — the selection state is tangled into filtering logic.
- **Serialisation mismatch.** `is_selected` is a view concern but lives on the data object, which is also passed to background workers (MediaManager). Workers never use it, but it crosses process boundaries anyway.

**Proposed design — `SelectionModel`:**

```python
class SelectionModel(QObject):
    """Single source of truth for photo selection."""

    changed = Signal()  # emitted after any mutation

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected: dict[str, int] = {}   # path → index (ordered)
        self._anchor_path: str | None = None

    # --- Queries (O(1)) ---
    @property
    def count(self) -> int: ...
    def is_selected(self, path: str) -> bool: ...
    def selected_paths(self) -> set[str]: ...
    def selected_indices(self) -> set[int]: ...
    def anchor_path(self) -> str | None: ...

    # --- Mutations (emit changed) ---
    def select(self, path: str, index: int, *, clear_others=True): ...
    def toggle(self, path: str, index: int): ...
    def select_range(self, items: list[ImageItem], start: int, end: int): ...
    def clear(self): ...
    def set_from_paths(self, paths: set[str], items: list[ImageItem]): ...

    # --- Filter support ---
    def retain_only(self, valid_paths: set[str]): ...
```

**Migration path:**

1. Create `SelectionModel` as a new class, owned by `MainWindow`.
2. Pass it to `PhotoGrid` and `PhotoListModel` as a dependency (not inheritance).
3. `PhotoGrid.on_cell_clicked()` calls `selection_model.select()` / `.toggle()` / `.select_range()` instead of mutating `item.is_selected`.
4. `PhotoCell.set_content()` receives `is_selected` from `selection_model.is_selected(item.path)` instead of `item.is_selected`.
5. Remove `is_selected` from `ImageItem` entirely.
6. Remove the redundant `_selected_paths_cache` / `_selected_count_cache` from `MainWindow` — the `SelectionModel` *is* the cache.
7. `PhotoListModel` selection methods become thin forwards to `SelectionModel`.
8. `SelectionModel.retain_only()` replaces the scattered `p.is_selected = False` loops in `_apply_filter_and_sort()`.

**Benefits:**
- O(1) selection queries instead of O(n) scans.
- Single signal (`changed`) replaces the current dual `grid.selection_changed` + `photo_model.selection_changed`.
- `ImageItem` becomes a pure data object with no view state.
- Easier to unit-test selection logic in isolation.

### 4.3 Signal Spaghetti

The main window connects **55 signals** manually across its `__init__` and `_create_menu_bar()`. There is no signal registry, no lifecycle management, and no way to audit the full graph without reading 2 362 lines. Adding a new feature means modifying `main_window.py` in 3–5 places: widget creation, signal connection, handler method, and possibly state bookkeeping.

**Inventory of signal connection sites (current state):**

| Source | Signals | Connected In |
|--------|---------|-------------|
| `FilterPanel` | `filter_changed`, `interaction_finished` | `__init__` L176–178 |
| `EditPanel` | `edit_finished`, `interaction_finished`, `metadata_saved` | `__init__` L203–207 |
| `ExifPanel` | `interaction_finished` | `__init__` L211–222 |
| `ColumnNumberSelector` | `decrement_requested`, `increment_requested` | `__init__` L242–245 |
| `QSplitter` | `splitterMoved` | `__init__` L258 |
| `StatusBar` | `error_btn.clicked` | `__init__` L274 |
| `MediaManager` | `thumb_ready`, `thumb_progress_updated`, `editable_ready`, `exif_progress_updated`, `panel_fields_ready`, `all_completed` | `__init__` L279–284 |
| `PhotoGrid` | `request_thumb`, `visible_paths_changed`, `request_fullscreen`, `selection_changed`, `context_menu_requested`, `label_shortcut_requested`, `filter_label_shortcut_requested`, `folder_filter_cycle_requested`, `folder_filter_all_requested`, `clear_filter_shortcut_requested`, `focus_filter_search_shortcut_requested`, `toggle_sidebar_shortcut_requested` | `__init__` L286–308 |
| `PhotoListModel` | `photos_changed`, `photo_added`, `photo_removed` | `__init__` L322–324 |
| `FolderWatcher` | `changes_detected` | `_start_folder_watcher()` L1779 |
| `FullscreenOverlay` | `label_shortcut_requested`, `index_changed`, `destroyed` | `_handle_fullscreen_overlay()` L2112–2148 |
| `SettingsDialog` | `setting_saved` | `on_settings()` L1378 |
| Menu QActions (×19) | `triggered` | `_create_menu_bar()` L1193–1315 |
| Cleanup worker | `finished` | `_on_workspace_properties_action()` L1675 |

**Problems:**

1. **No single place to see the graph.** You must read 5+ methods to understand all connections. Disconnecting a signal means hunting through the entire file.
2. **Hidden temporal coupling.** Some signals are connected in `__init__`, others lazily (fullscreen, watcher, settings dialog). If a component emits before its handler is connected, the event is silently lost.
3. **Handler naming is inconsistent.** Some handlers use `_on_` prefix, some use `on_` (public), some are lambdas (`lambda: self._set_sort_order(...)`). No convention is enforced.
4. **Grid shortcut signals are a workaround.** The grid emits 7 `*_shortcut_requested` signals that just call filter panel methods. This exists because the grid owns the keyboard scope but doesn't have direct access to the filter panel. A proper shortcut/action system would eliminate these pass-through signals.

**Recommendation — Grouped Connection Methods:**

As a first step (before any controller split), extract signal connections into named methods:

```python
class MainWindow(QMainWindow):
    def __init__(self, ...):
        # ... widget creation ...
        self._connect_filter_signals()
        self._connect_panel_signals()
        self._connect_grid_signals()
        self._connect_media_signals()
        self._connect_model_signals()

    def _connect_grid_signals(self):
        """All PhotoGrid ↔ MainWindow connections."""
        self.grid.request_thumb.connect(self.request_thumb_handler)
        self.grid.visible_paths_changed.connect(self._on_visible_paths_changed)
        self.grid.request_fullscreen.connect(self._handle_fullscreen_overlay)
        self.grid.selection_changed.connect(self.on_selection_changed)
        self.grid.context_menu_requested.connect(self._show_context_menu)
        # ... etc ...

    # Each method is ~10–15 lines, easily auditable.
```

**Recommendation — Reduce pass-through shortcut signals:**

The grid emits 7 pass-through signals (`filter_label_shortcut_requested`, `folder_filter_cycle_requested`, `clear_filter_shortcut_requested`, etc.) that the main window just forwards to the filter panel. Each signal has a one-line `_activate_*` handler guarded by `_shared_grid_view_shortcuts_allowed()`.

The naive fix — moving these to window-scoped `QAction`s on `MainWindow` — **does not work here**. The shortcuts are deliberately scoped to `central_widget` with `Qt.WidgetWithChildrenShortcut` and a focus guard (`_shared_grid_view_shortcuts_allowed`). This is necessary because the `FullscreenOverlay` is a separate top-level `QWidget`: when it has focus, shortcuts scoped to the central widget are correctly suppressed. A `Qt.WindowShortcut` on the `MainWindow` would fire even during fullscreen, incorrectly modifying filters behind the overlay.

The current architecture is therefore correct in its scoping. What can be improved is the signal fanout. Instead of 7 signals + 7 connections + 7 `MainWindow` one-liner handlers, the grid could accept a callback object at construction time:

```python
@define
class GridShortcutHandler:
    """Callbacks for grid-scoped shortcuts that affect non-grid components."""
    on_filter_label: Callable[[str | None], None] | None = None
    on_folder_filter_cycle: Callable[[int], None] | None = None
    on_folder_filter_all: Callable[[], None] | None = None
    on_clear_filter: Callable[[], None] | None = None
    on_focus_filter_search: Callable[[], None] | None = None
    on_toggle_sidebar: Callable[[], None] | None = None

# In MainWindow:
handler = GridShortcutHandler(
    on_filter_label=self._on_filter_label_shortcut_requested,
    on_folder_filter_cycle=self._on_folder_filter_cycle_shortcut_requested,
    on_folder_filter_all=self._on_folder_filter_all_shortcut_requested,
    on_clear_filter=self._on_clear_filter_shortcut_requested,
    on_focus_filter_search=self._on_focus_filter_search_shortcut_requested,
    on_toggle_sidebar=self._toggle_right_sidebar_collapsed,
)
self.grid.set_shortcut_handler(handler)
```

This keeps the focus-guard logic inside the grid (where it belongs), eliminates 7 `Signal()` declarations and their boilerplate `_activate_*` methods, and makes the contract explicit. The grid calls `self._shortcut_handler.on_clear_filter()` directly instead of emitting a signal — still guarded by `_shared_grid_view_shortcuts_allowed()` as before.

An alternative middle ground: keep the signals but move them to a dedicated `GridShortcutBridge(QObject)` that is instantiated by `MainWindow` and does all the wiring in one place. This avoids changing the grid's public interface while still consolidating the 7 connections.

**Recommendation — Signal lifecycle for dynamic components:**

`FullscreenOverlay` and `FolderWatcher` are created/destroyed at runtime. Their signals are connected inline in the creation method. If the overlay is re-created, old connections may linger (Qt disconnects on `QObject` destruction, but only if the sender is the destroyed object).

Formalize with a pattern:

```python
def _attach_fullscreen(self, overlay: FullscreenOverlay):
    """Connect all fullscreen signals. Called once per overlay lifetime."""
    overlay.label_shortcut_requested.connect(self._apply_label_to_grid_selection)
    overlay.index_changed.connect(self._on_fullscreen_index_changed)
    overlay.destroyed.connect(self._on_fullscreen_closed)

def _attach_folder_watcher(self, watcher: FolderWatcher):
    """Connect watcher signals. Called once per folder open."""
    watcher.changes_detected.connect(self._on_folder_changes)
```

This makes it trivial to later extract into a controller module and ensures every dynamic component has a clear "attach" entry point.

### 4.4 Error Handling Is Inconsistent

Some errors are caught and logged, some are shown in dialogs, some are collected in `ErrorListDialog`, and some crash the app. There is no unified error-handling strategy.

**Recommendation:**
- Define error severity levels: `info`, `warning`, `error`, `fatal`.
- Route all non-fatal errors through a single `ErrorCollector` that populates the status bar error button.
- Fatal errors (corrupt DB, missing exiftool) should show a blocking dialog with recovery options.
- Never silently swallow exceptions — at minimum log them.

### 4.5 No Test Coverage for UI

Tests exist but primarily for utility functions. No UI tests, no integration tests for the data pipeline.

**Recommendation:**
- Add `pytest-qt` for widget-level tests (panel population, selection, filter application).
- Add integration tests: scan folder → load EXIF → verify DB → verify grid cell content.
- Add a `conftest.py` with fixtures for temporary image folders with known EXIF data.

### 4.6 Thumbnail Regeneration Is All-or-Nothing

"Regenerate Thumbnails" clears the entire cache and reprocesses. For a 10 000-image folder, this takes minutes.

**Recommendation:**
- Support per-image regeneration (already in context menu, but could be more discoverable).
- Track thumbnail freshness: store source file mtime alongside the cached thumb. On load, compare mtimes and regenerate only stale thumbnails.
- Show a progress dialog for bulk regeneration with a cancel button.

---

## 5. Things That Should Be Redone

### 5.1 The Custom Scroll System

`PhotoGrid` implements its own scrollbar, viewport calculations, and scroll acceleration. This is fragile, hard to maintain, and doesn't integrate with macOS trackpad physics (rubber-banding, momentum scrolling).

**What to do:** As noted in 4.1, migrate to `QListView`. If that's too large a change, at minimum replace the manual `QScrollBar` with a `QScrollArea` wrapping the grid container, which gives native scroll physics for free.

### 5.2 Settings State Framework (`ssf/`)

`settings_state.py` defines 100+ keys as string enums with default values, then provides global `get_*`/`set_*` functions that access a module-level `QSettings` instance. This is effectively a global mutable singleton with no change notification.

**What to do:** Wrap settings in a `QObject` subclass that emits `Signal(str, object)` on any change. Components subscribe to the keys they care about. This removes the need for manual "refresh settings" calls scattered throughout the codebase and prevents stale reads.

### 5.3 Multiprocessing Architecture

#### How It Works Today

`MediaManager` (1 019 lines) orchestrates all background work through a pool of **spawned processes** (`multiprocessing.get_context("spawn")`). Each process runs `worker_main()` — an infinite loop consuming tasks from its own `multiprocessing.Queue` and posting results to a shared result queue.

```
Main process (Qt thread)              Worker processes (no Qt)
─────────────────────────             ──────────────────────
MediaManager                          worker_main() loop
  ├── _tick() every 50 ms               ├── run_combined_task()
  │     ├── _drain_results()             │     ├── exiftool.get_metadata() (batch)
  │     ├── _schedule_work()             │     └── exiftool -b -ThumbnailImage (extract)
  │     └── worker pool scaling          ├── run_hq_thumb_task()
  ├── _result_queue  ◄─── results ───   │     └── PIL Image.thumbnail()
  └── worker.task_queue ──── tasks ──►   └── run_write_exif_task()
                                               └── exiftool.set_tags()
```

Three task kinds are dispatched:

| Kind | What It Does | I/O Profile |
|------|-------------|-------------|
| `combined` | Batch EXIF extraction (via persistent exiftool subprocess) + embedded JPEG preview extraction | Subprocess I/O — exiftool reads files, writes preview JPEGs. CPU-light on the Python side. |
| `hq_thumb` | Open full image with Pillow, resize, save JPEG | Disk I/O (read full image) + brief CPU burst (resize). GIL released during Pillow's C decode/encode. |
| `write_exif` | Write edited metadata back to files via exiftool | Subprocess I/O, sequential per-file. |

The manager runs a **50 ms tick timer** on the main thread that drains results and dispatches new work. It maintains a priority system (writes > visible combined > visible HQ > background combined > background HQ) and batches combined tasks by source folder for efficient exiftool invocations.

#### What Works Well

- **No QPixmap crosses process boundaries.** Workers write thumbnail files to disk and return cache paths as strings. The main thread loads pixmaps lazily when the grid renders — so there is no serialization overhead for Qt objects.
- **Priority scheduling.** Visible items are processed first, background items later. The `_rebalance_pending_priorities()` method promotes/demotes items when the viewport scrolls.
- **Folder-based batching.** Combined tasks batch files from the same source folder into a single exiftool invocation, reducing subprocess overhead.
- **Auto-scaling worker pool.** Workers are spawned up to `MAX_WORKERS` under backpressure and stopped when idle (down to `MIN_IDLE_WORKERS`).

#### Pain Points

1. **Spawned processes are expensive to start.** `multiprocessing.get_context("spawn")` forks a fresh Python interpreter for each worker. On macOS this takes ~200–500 ms per worker. The pool pre-creates `MIN_IDLE_WORKERS` at startup, but scaling up under load adds visible latency.

2. **Hard to debug.** Worker processes are separate PIDs — breakpoints, `pdb`, and most IDE debuggers don't attach to them. Logging is the only practical debugging tool, and log output interleaves with the main process.

3. **Complex shutdown sequence.** `stop()` must: send a "stop" message to each task queue, join with timeout, then terminate stragglers, then join again. If any queue is full or a worker hangs, shutdown stalls. There's a separate `drain_qthread_pool()` in the `MetadataSaveWorker` path that also needs coordination.

4. **Polling architecture.** The 50 ms `QTimer` polls the result queue via `get_nowait()`. This means results have up to 50 ms of latency before they're processed. For a 100-image batch where results arrive in rapid succession, this is fine. But for single-item requests (e.g., a user triggers "Regenerate Thumbnail" on one image), the result takes 50 ms longer to appear than it should.

5. **Monolithic worker loop.** `worker_main()` handles all three task kinds in the same process. A Pillow segfault during HQ thumbnail generation kills the exiftool extraction that could have run in another worker. There's no fault isolation between task kinds.

6. **Duplicate state tracking.** `MediaManager` maintains parallel sets for progress (`_thumb_done`, `_editable_done`), pending work (`_pending_combined_visible`, `_pending_combined_other`, `_pending_hq_visible`, `_pending_hq_other`), in-flight tracking (`_in_flight`, `_in_flight_files`), and deferred work (`_deferred_combined`). This is ~10 dictionaries/sets that must stay consistent — a fertile ground for subtle bugs.

7. **No per-task timeout.** If exiftool hangs on a corrupt file, the worker is permanently busy. The manager keeps dispatching to other workers, but the hung worker is never reclaimed.

#### Recommended Changes

**A. Move HQ thumbnail generation to `QThreadPool` + `QRunnable`**

HQ thumbnail generation (`run_hq_thumb_task`) calls Pillow's `Image.open()` + `Image.thumbnail()` + `Image.save()`. These release the GIL during the C-level decode/encode. The Python-side work is trivial (construct a path, call three methods). This task does not need to run in a separate process — a thread is sufficient and gives:

- Instant "start" (no process spawn overhead)
- Debugger-friendly (same PID, breakpoints work)
- Direct access to the result queue (no IPC serialization)
- Simpler shutdown (`QThreadPool.waitForDone()`)

```python
class HQThumbWorker(QRunnable):
    """Generate one HQ thumbnail on a thread pool thread."""

    def __init__(self, file_path: str, thumb_dir: str, max_dim: int,
                 on_done: Callable[[str, str | None, str | None], None]):
        super().__init__()
        self._file_path = file_path
        self._thumb_dir = thumb_dir
        self._max_dim = max_dim
        self._on_done = on_done
        self.setAutoDelete(True)

    def run(self):
        base_name = os.path.splitext(os.path.basename(self._file_path))[0]
        cache_path = str(Path(self._thumb_dir) / "hq" / f"{base_name}.jpg")
        ok = generate_hq_thumbnail(self._file_path, cache_path, self._max_dim)
        # QMetaObject.invokeMethod or signal to push result to main thread
        self._on_done(self._file_path, cache_path if ok else None,
                      None if ok else "HQ generation failed")
```

This eliminates `_pending_hq_visible` / `_pending_hq_other` and the HQ branch from `_pop_next_task()`. The `QThreadPool` handles its own scheduling and concurrency limiting.

**B. Keep multiprocessing for exiftool tasks (`combined` + `write_exif`)**

The exiftool integration has a genuine reason to be in a separate process: `ExifToolHelper` launches and manages a persistent `exiftool` subprocess. Running this in a thread would work, but the persistent subprocess model means a hung exiftool blocks the thread forever (and threads can't be force-killed). Processes can be terminated.

However, restructure the process pool:

- **Dedicated exiftool workers.** Each spawned process runs only exiftool tasks. Remove the `kind` dispatch from `worker_main()` — it only handles `combined` and `write_exif`.
- **Per-task timeout.** Wrap each exiftool invocation in a deadline. If the process doesn't return within, say, 30 seconds per file in the batch, the manager terminates the process and respawns it. The affected files are logged as errors.

```python
# In _tick():
for task_id, worker in list(self._in_flight.items()):
    if worker.started_at + TASK_TIMEOUT < time.monotonic():
        worker.process.terminate()
        self._handle_timeout(task_id)
```

- **Separate write worker.** Optionally, dedicate one process to `write_exif` tasks. This ensures user-initiated writes are never queued behind a large batch of background EXIF reads.

**C. Replace polling with event-driven result delivery**

The 50 ms `QTimer` poll loop is functional but inelegant. Replace with a dedicated result-reader thread that blocks on `result_queue.get()` and emits a Qt signal:

```python
class _ResultReader(QThread):
    result_received = Signal(dict)

    def __init__(self, result_queue):
        super().__init__()
        self._queue = result_queue
        self._running = True

    def run(self):
        while self._running:
            try:
                result = self._queue.get(timeout=0.5)
                self.result_received.emit(result)
            except queue.Empty:
                continue

    def stop(self):
        self._running = False
```

This delivers results to the main thread with ~0 ms latency (Qt signal dispatch) instead of up to 50 ms.

**D. Consolidate state tracking**

Replace the 10 parallel sets/dicts with a single per-file state machine:

```python
class FileState(StrEnum):
    QUEUED = auto()          # Waiting for a worker
    IN_FLIGHT = auto()       # Worker is processing
    EMBEDDED_READY = auto()  # Embedded thumb done, HQ pending
    COMPLETE = auto()        # All work done
    ERROR = auto()           # Terminal failure

@define
class FileTracker:
    state: FileState = FileState.QUEUED
    needs: _CombinedNeed = Factory(_CombinedNeed)
    is_visible: bool = False
    error: str | None = None
    task_id: int | None = None
```

A single `dict[str, FileTracker]` replaces `_thumb_done`, `_editable_done`, `_pending_combined_visible`, `_pending_combined_other`, `_pending_hq_visible`, `_pending_hq_other`, `_in_flight_files`, and `_deferred_combined`. Progress counts become `sum(1 for f in trackers.values() if f.state == ...)`.

#### Migration Path

| Step | Change | Risk |
|------|--------|------|
| 1 | Add `_ResultReader` thread alongside existing timer | Low — additive, timer still works as fallback |
| 2 | Extract HQ thumbnail generation to `QThreadPool` | Medium — remove HQ from worker process, add `HQThumbWorker` |
| 3 | Add per-task timeout to exiftool workers | Low — additive timeout check in `_tick()` |
| 4 | Refactor state tracking to `FileTracker` | Medium — internal refactor, no external API change |
| 5 | Remove 50 ms timer, rely fully on `_ResultReader` | Low — once step 1 is proven stable |
| 6 | Optionally: dedicate one process to writes | Low — scheduling change only |

Each step is independently deployable and testable. The total effect: fewer processes, faster result delivery, debuggable thumbnail generation, and a state model that fits in one dict instead of ten.

### 5.4 EXIF Write Path

EXIF writing is triggered by an explicit user action ("Save EXIF"). This means edits can be lost if the user forgets to save, and there's no dirty-state indicator.

**What to do:**
- Show a visual indicator (dot in tab, asterisk in title bar) when metadata is dirty (differs from on-disk EXIF).
- Auto-save to DB is already happening, so data isn't truly lost — but the user intent is unclear. Consider auto-writing EXIF on a timer or on folder close, with a preference to control this.
- Add a "Revert to EXIF" action per field.

---

## 6. Summary — Priority Matrix

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| **P0** | Cache/folder resilience (2.1–2.3) | Medium | Prevents crashes |
| **P0** | SQLite WAL + corruption recovery (2.4) | Low | Prevents data loss |
| **P1** | Split `main_window.py` (1.1) | Medium | Unblocks all future work |
| **P1** | Extract `SelectionModel` from `ImageItem` (4.2) | Medium | Fixes dual-authority bugs, O(1) queries |
| **P1** | Group signal connections + eliminate pass-throughs (4.3) | Low | Auditability, fewer moving parts |
| **P1** | Full undo/redo stack (3.1) | Medium | Expected macOS behavior |
| **P1** | Dirty-state indicator for EXIF (5.4) | Low | Prevents user confusion |
| **P2** | Migrate to `QListView` (4.1 / 5.1) | High | Native scroll, a11y, DnD |
| **P2** | Observable settings (5.2) | Medium | Reduces coupling |
| **P2** | Error handling unification (4.4) | Medium | Better UX |
| **P2** | Drag & drop (3.1) | Medium | Expected macOS behavior |
| **P3** | Split `ImageItem` further (4.2) | Medium | Cleaner architecture |
| **P3** | Test coverage (4.5) | Ongoing | Long-term stability |
| **P3** | Auto-update, crash reporting (3.1) | Medium | Distribution readiness |
| **P3** | Accessibility / VoiceOver (3.2) | Medium | Inclusivity |
| **P3** | Dark mode support (3.2) | Low–Medium | Visual polish |
