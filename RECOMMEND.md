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

`ImageItem` holds file identity, display state (pixmaps), selection state, raw EXIF, and edited metadata all in one `attrs` class. This makes it hard to reason about lifetimes and ownership.

**Recommendation:** Separate into:
- `PhotoIdentity` — immutable: path, name, source_folder, created
- `PhotoDisplayState` — mutable: pixmaps, state, cache_state_dirty
- `PhotoMetadata` — mutable: db_metadata, exif_data, label
- Keep `is_selected` on the model, not on the item (selection is a view concern)

### 4.3 Signal Spaghetti

The main window connects ~30 signals manually in `__init__`. There is no signal registry or lifecycle management. Adding a new feature means modifying `main_window.py` in multiple places.

**Recommendation:** Introduce a lightweight event bus or at least a `_connect_signals()` method per controller module. This makes it easier to audit signal flow and prevents the "add a line here and here and here" pattern.

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

The current `MediaManager` uses `multiprocessing.Process` with shared queues. This works but has pain points:
- Hard to debug (separate process, no breakpoints)
- Serialization overhead for QPixmap (must convert to bytes and back)
- Complex shutdown sequence (`drain_qthread_pool`, process termination)

**What to do:** Consider `QThread` + `QRunnable` for thumbnail generation (Pillow is not CPU-bound enough to need multiprocessing, and the GIL is released during I/O). Keep multiprocessing only for exiftool batch operations where the persistent subprocess model matters. This simplifies the architecture and avoids IPC overhead.

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
| **P1** | Full undo/redo stack (3.1) | Medium | Expected macOS behavior |
| **P1** | Dirty-state indicator for EXIF (5.4) | Low | Prevents user confusion |
| **P2** | Migrate to `QListView` (4.1 / 5.1) | High | Native scroll, a11y, DnD |
| **P2** | Observable settings (5.2) | Medium | Reduces coupling |
| **P2** | Error handling unification (4.4) | Medium | Better UX |
| **P2** | Drag & drop (3.1) | Medium | Expected macOS behavior |
| **P3** | Split `ImageItem` (4.2) | Medium | Cleaner architecture |
| **P3** | Test coverage (4.5) | Ongoing | Long-term stability |
| **P3** | Auto-update, crash reporting (3.1) | Medium | Distribution readiness |
| **P3** | Accessibility / VoiceOver (3.2) | Medium | Inclusivity |
| **P3** | Dark mode support (3.2) | Low–Medium | Visual polish |
