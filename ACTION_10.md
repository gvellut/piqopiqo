# ACTION_10: Folder-based Cache, Editable Metadata Panel, and Folder Management

## Status: IMPLEMENTED

All tasks have been implemented. See the Implementation Summary below.

## Overview

This action adds several major features to PiqoPiqo:
1. Per-folder thumbnail caching with hash-based folder identification
2. Open folder menu item and support for launching without a folder argument
3. Editable metadata panel with SQLite storage
4. Folder filter panel for multi-folder views

---

## Task 1: Create Support Directory Utilities

**File:** `src/piqopiqo/support.py` (new file)

**Goal:** Create a utility module for determining platform-specific application support directories.

**Details:**
- Create function `get_support_dir() -> Path` that returns the appropriate support directory:
  - macOS: `~/Library/Application Support/PiqoPiqo/`
  - Windows: `%APPDATA%/PiqoPiqo/`
  - Linux: `~/.config/piqopiqo/`
- Use `sys.platform` to detect the platform
- Create the directory if it doesn't exist
- Use existing libraries only (os, pathlib, sys) - no new dependencies
- The support directory will be used for:
  - `last_folder.json` - stores the last opened folder path
  - Future: any other persistent application state

**Existing libraries to check:**
- The project uses `os`, `pathlib`, `sys` which are sufficient for this task

---

## Task 2: Refactor Cache Directory Structure

**Files to modify:**
- `src/piqopiqo/config.py`
- `src/piqopiqo/thumb_man.py`
- `src/piqopiqo/__main__.py`

**Goal:** Change from single cache directory to per-origin-folder cache structure.

**Details:**

### 2.1 Update Config
- Remove `CACHE_DIR` as a single path
- Add `CACHE_BASE_DIR` - base directory for all caches (default: use support directory + "cache")
- Keep `CLEAR_CACHE_ON_START` but make it work per-folder-cache

### 2.2 Create cache path utility functions in `thumb_man.py`
- Add function `get_folder_cache_id(folder_path: str) -> str`:
  - Compute hash of the absolute folder path using `hashlib.md5` or `hashlib.sha256`
  - Return first 32 characters of the hex digest
  - This ensures same folder always gets same cache, different folders get different caches
  - If folder is moved, cache is invalidated (new hash)

- Add function `get_cache_dir_for_folder(folder_path: str) -> Path`:
  - Returns `{CACHE_BASE_DIR}/{folder_hash}/`
  - Example: `/Users/guilhem/Library/Application Support/PiqoPiqo/cache/a1b2c3d4.../`

- Add function `get_thumb_dir_for_folder(folder_path: str) -> Path`:
  - Returns `{CACHE_BASE_DIR}/{folder_hash}/thumb/`
  - The `thumb` subfolder is created inside the folder-specific cache
  - This allows future expansion (db folder will be added alongside)

### 2.3 Update `worker_task` and `hq_worker_task`
- These functions need to receive the cache directory as a parameter (since they run in separate processes)
- Modify function signatures: `worker_task(file_path, cache_dir)` and `hq_worker_task(file_path, cache_dir)`
- Update cache path construction to use the passed `cache_dir`

### 2.4 Update `ThumbnailManager`
- Store `cache_dirs: dict[str, Path]` mapping source folder paths to their cache directories
- Modify `queue_image(file_path)`:
  - Determine the source folder from `file_path`
  - Get or create the appropriate cache directory
  - Pass cache directory to worker tasks
- Add method `register_folder(folder_path: str)`:
  - Computes and stores the cache directory for a folder
  - Creates the thumb subdirectory if needed

### 2.5 Update `__main__.py`
- Track all unique folders found during scanning
- For each unique folder, register it with ThumbnailManager
- Update cache clearing logic to work with the new structure

**Note on multiple folders:**
When scanning recursively (e.g., `/photos/2024/`), images may come from:
- `/photos/2024/january/`
- `/photos/2024/february/`
- `/photos/2024/march/`

Each of these gets its own cache folder, stored flat (not hierarchical):
```
cache/
  {hash_of_january}/thumb/
  {hash_of_february}/thumb/
  {hash_of_march}/thumb/
```

---

## Task 3: Add "Regenerate Thumbnail Cache" Menu Item

**File to modify:** `src/piqopiqo/photo_grid.py`

**Goal:** Add a menu item to regenerate all thumbnails for the current folder(s).

**Details:**
- Add menu item "Regenerate Thumbnails" to File menu
- Shortcut: `Cmd+Shift+R` (macOS) / `Ctrl+Shift+R`
- Handler `on_regenerate_thumbnails()`:
  - Clear all cache directories for currently loaded folders (delete thumb folder contents)
  - Reset all `ImageItem.state` to 0
  - Reset all `ImageItem.pixmap` to None
  - Trigger grid refresh which will re-request thumbnails

---

## Task 4: Add "Open Folder" Menu Item and Folder Persistence

**Files to modify:**
- `src/piqopiqo/__main__.py`
- `src/piqopiqo/photo_grid.py`

**Goal:** Allow opening folders from the menu and persist the last opened folder.

### 4.1 Create folder persistence functions in `support.py`
- Add `save_last_folder(folder_path: str)`:
  - Save to `{support_dir}/last_folder.json`
  - JSON format: `{"path": "/path/to/folder", "timestamp": "ISO8601"}`
- Add `get_last_folder() -> str | None`:
  - Read from `{support_dir}/last_folder.json`
  - Return the path or None if file doesn't exist or is invalid

### 4.2 Update `__main__.py`
- Make the `folder` argument optional: `@click.argument("folder", type=click.Path(exists=True), required=False)`
- Logic on startup:
  1. If folder argument provided: use it, save as last folder
  2. If no folder argument: try to load last folder from JSON
  3. If no last folder: launch in "empty" mode (no images loaded)
- Pass the folder (or None) to MainWindow

### 4.3 Implement "Open Folder" in MainWindow
- Update `on_open()` to use `QFileDialog.getExistingDirectory()`
- On folder selection:
  - Save as last folder
  - Scan the new folder
  - Reinitialize the grid with new images
  - Register new folders with ThumbnailManager
  - Clear current images and reset state
- Consider: should this close and reopen the window, or reload in place? (Reload in place is cleaner)

### 4.4 Create Empty State Panel
- New widget class `EmptyStatePanel(QWidget)` in a new file `src/piqopiqo/empty_state.py`
- Displays when no folder is loaded:
  - Centered layout
  - "Open a folder to get started" message
  - Large "Open Folder" button
  - Button connects to same handler as menu Open
- MainWindow shows this panel instead of grid when no folder is loaded
- Use `QStackedWidget` to switch between empty state and main content

---

## Task 5: Add Editable Metadata Panel - Core Infrastructure

**New file:** `src/piqopiqo/edit_panel.py`

**Goal:** Create the editable metadata panel widget and database infrastructure.

### 5.1 Database Schema
Create SQLite database at `{cache_base_dir}/{folder_hash}/db/metadata.db`

**Table: `photo_metadata`**
```sql
CREATE TABLE photo_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,  -- Full path to the image
    file_name TEXT NOT NULL,         -- Filename for display/search
    title TEXT,                      -- Max length from config
    description TEXT,                -- Max length from config
    latitude REAL,                   -- Decimal format
    longitude REAL,                  -- Decimal format
    keywords TEXT,                   -- Comma-separated or JSON array
    datetime_original TEXT,          -- ISO8601 format
    label TEXT,                      -- Status label (e.g., "Red", "Yellow")
    created_at TEXT NOT NULL,        -- ISO8601 timestamp
    updated_at TEXT NOT NULL         -- ISO8601 timestamp
);
CREATE INDEX idx_file_path ON photo_metadata(file_path);
```

### 5.2 Database Manager Class
Create `MetadataDB` class:
- `__init__(self, db_path: Path)` - does NOT create DB file yet
- `_ensure_db()` - creates DB file and tables on first write
- `get_metadata(file_path: str) -> dict | None` - returns None if no entry
- `save_metadata(file_path: str, data: dict)` - creates or updates entry
- `delete_metadata(file_path: str)` - removes entry
- `has_metadata(file_path: str) -> bool` - checks if entry exists

**Important:** The database file is only created when the first edit is saved, not on application start.

### 5.3 Add Config Options
Add to `config.py`:
```python
# Editable metadata panel
SHOW_EDIT_PANEL = True
TITLE_MAX_LENGTH = 128
DESCRIPTION_MAX_LENGTH = 128

# Status labels with colors (name, hex color)
STATUS_LABELS = [
    ("No Label", "#808080"),
    ("Red", "#FF0000"),
    ("Yellow", "#FFFF00"),
    ("Green", "#00FF00"),
    ("Blue", "#0000FF"),
    ("Purple", "#800080"),
]
```

---

## Task 6: Editable Metadata Panel - Widget Implementation

**File:** `src/piqopiqo/edit_panel.py`

**Goal:** Implement the UI for editing photo metadata.

### 6.1 Create `EditPanel(QWidget)` class

**Layout:**
- Vertical layout with scroll area
- Each field has: header label + input widget
- Fields from top to bottom:
  1. Title (single line, but can wrap visually if long)
  2. Description (multi-line text area)
  3. Latitude (single line, numeric validation)
  4. Longitude (single line, numeric validation)
  5. Keywords (single line, expandable)
  6. Time (single line, datetime format)
  7. Status (combobox)

**Field widgets:**
- `TitleEdit(QLineEdit)` - custom class:
  - Strips newlines on paste
  - Enter saves and returns focus to grid
  - Cmd+Enter does nothing
  - Max length from config

- `DescriptionEdit(QPlainTextEdit)` - custom class:
  - Cmd+Enter (macOS) / Alt+Enter (others) for newlines
  - Enter saves and returns focus to grid
  - Max length from config

- `CoordinateEdit(QLineEdit)` - custom class for lat/lon:
  - Validates decimal number format
  - Validates range: lat -90 to 90, lon -180 to 180
  - Shows validation error styling if invalid

- `KeywordsEdit(QLineEdit)` - custom class:
  - No length limit
  - Expandable height if content wraps

- `TimeEdit(QLineEdit)` - custom class:
  - Validates datetime format
  - Expected format: `YYYY:MM:DD HH:MM:SS` (EXIF format)

- `StatusComboBox(QComboBox)` - custom class:
  - Populated from `Config.STATUS_LABELS`
  - Each item shows color swatch
  - Change event immediately saves (no enter needed)
  - Selecting "No Label" clears the value (sets to null)

### 6.2 EXIF Field Mappings

For pre-populating fields from EXIF data, here are the exiftool field names:

| Edit Field | ExifTool Field | Notes |
|------------|----------------|-------|
| Title | `EXIF:ImageDescription` or `XMP:Title` | Try XMP first |
| Description | `EXIF:UserComment` or `XMP:Description` | Try XMP first |
| Latitude | `EXIF:GPSLatitude` + `EXIF:GPSLatitudeRef` | Convert from DMS to decimal |
| Longitude | `EXIF:GPSLongitude` + `EXIF:GPSLongitudeRef` | Convert from DMS to decimal |
| Keywords | `IPTC:Keywords` or `XMP:Subject` | May be array or string |
| Time | `EXIF:DateTimeOriginal` | Format: `YYYY:MM:DD HH:MM:SS` |
| Status | `XMP:Label` | Namespace: `http://ns.adobe.com/xap/1.0/` |

### 6.3 GPS Coordinate Conversion (EXIF to Decimal)

Create utility function `exif_gps_to_decimal(degrees, minutes, seconds, ref) -> float`:
```python
def exif_gps_to_decimal(degrees, minutes, seconds, ref):
    """Convert EXIF GPS format to decimal degrees.

    Args:
        degrees: Degrees value (int or float)
        minutes: Minutes value (int or float)
        seconds: Seconds value (float)
        ref: Reference direction ('N', 'S', 'E', 'W')

    Returns:
        Decimal degrees (negative for S and W)
    """
    decimal = degrees + minutes / 60 + seconds / 3600
    if ref in ('S', 'W'):
        decimal = -decimal
    return decimal
```

Also handle the case where EXIF returns GPS as a single decimal value (some cameras do this).

### 6.4 Key Bindings

**General behavior:**
- Tab: Move to next field (cycles back to first from last)
- Shift+Tab: Move to previous field
- Escape: Revert to original value, return focus to grid
- Cmd+Z / Ctrl+Z: Undo within field (standard Qt behavior)

**On field focus out (tab away or click elsewhere):**
- If value was modified: save automatically (same as Enter)

**Focus management:**
- When photo selected in grid: panel shows data but focus stays on grid
- When clicking a field: focus moves to that field
- After Enter or Escape: focus returns to the grid

---

## Task 7: Editable Metadata Panel - Data Flow and Multi-Selection

**Files:** `src/piqopiqo/edit_panel.py`, `src/piqopiqo/photo_grid.py`

**Goal:** Handle data loading, saving, and multi-selection scenarios.

### 7.1 Single Photo Selection

When a single photo is selected:
1. Check if metadata exists in database for this photo
2. If yes: load from database
3. If no: extract initial values from EXIF data
4. Display values in edit fields
5. On edit + save: create database entry with ALL fields (even unedited ones)

### 7.2 Multiple Photo Selection

When multiple photos are selected:
1. For each field, gather values from all selected photos
2. If all values are the same: display that value
3. If values differ: display `<Multiple Values>`

**Editing with multiple selection:**
- When focusing a field showing `<Multiple Values>`:
  - Clear the field immediately (becomes empty)
  - User types new value
  - On save (Enter/Tab): apply this value to ALL selected photos

- Escape behavior:
  - Field reverts to showing `<Multiple Values>`
  - NO changes are made to any photo's data

- Cmd+Z behavior:
  - Reverts to empty (the state after clearing `<Multiple Values>`)
  - Does NOT restore `<Multiple Values>` display
  - Only Escape fully cancels the edit

### 7.3 Database Write Conditions

The database file and entry are created only when:
1. User edits a field AND
2. Presses Enter, Tab (to next field), or clicks outside

The database is NOT created when:
- Just viewing photos
- Selecting photos
- Pressing Escape after editing

### 7.4 Empty/Null Handling

- If field has data and user clears it completely: value becomes NULL in database
- If EXIF has no data for a field: field shows empty, stored as NULL
- `<Multiple Values>` is never stored - it's display-only

### 7.5 Integration with MainWindow

Update `MainWindow`:
- Add `EditPanel` above `ExifPanel` (both in right splitter)
- Use `QSplitter` (vertical) to allow resizing between EditPanel and ExifPanel
- Connect `selection_changed` signal to update both panels
- Pass reference to `MetadataDB` instances (one per folder cache)

**Signal flow:**
```
Grid.selection_changed
  -> MainWindow.on_selection_changed()
    -> EditPanel.update_for_selection(items: list[ImageItem])
    -> ExifPanel.update_exif(items: list[ImageItem])
```

---

## Task 8: Integrate Edit Panel into Main Window Layout

**Files to modify:**
- `src/piqopiqo/photo_grid.py`
- `src/piqopiqo/config.py`

**Goal:** Add the edit panel to the main window layout above the EXIF panel.

### 8.1 Layout Structure Update

Current structure:
```
MainWindow
└── Splitter (horizontal)
    ├── PagedPhotoGrid (80%)
    └── ExifPanel (20%)
```

New structure:
```
MainWindow
└── Splitter (horizontal)
    ├── PagedPhotoGrid (80%)
    └── Splitter (vertical) (20%)
        ├── EditPanel (50% of right side)
        └── ExifPanel (50% of right side)
```

### 8.2 Conditional Display

- Check `Config.SHOW_EDIT_PANEL`
- If False: don't create EditPanel, use current layout
- If True: create the nested splitter layout

### 8.3 Focus Management

- Grid maintains focus for keyboard navigation
- Clicking an edit field transfers focus to that field
- EditPanel signals when edit is complete (enter/escape) -> MainWindow returns focus to grid
- Add signal: `EditPanel.edit_finished` -> `MainWindow.on_edit_finished()` -> `self.grid.setFocus()`

---

## Task 9: Add Folder Filter Panel

**New file:** `src/piqopiqo/filter_panel.py`

**Goal:** Add a filter panel at the top of the main area for filtering by source folder.

### 9.1 Create `FolderFilterPanel(QWidget)` class

**Layout:**
- Horizontal layout, compact height
- Checkbox: "Filter by folder"
- Combobox: List of folders (only last component of path shown)
- Only visible when multiple folders have photos

**Behavior:**
- When checkbox is unchecked: show all photos
- When checkbox is checked: filter to selected folder
- Selecting a folder in combobox auto-checks the checkbox
- Combobox shows folder name only (e.g., "january" not "/photos/2024/january")
- Tooltip on combobox items shows full path

### 9.2 Integration with MainWindow

**Layout update:**
```
MainWindow
└── Central Widget
    └── VBoxLayout
        ├── FolderFilterPanel (only if multiple folders)
        └── Main Content (horizontal splitter with grid + panels)
```

### 9.3 Filtering Logic

- `FolderFilterPanel` emits signal: `filter_changed(folder_path: str | None)`
  - `None` means show all
  - String means filter to that folder

- `MainWindow` receives signal:
  - Store current filter
  - Filter `self.images_data` to create filtered list
  - Update grid with filtered data
  - Update panels accordingly

- Filtering should be fast (just Python list filtering)
- Selection state preserved where possible

### 9.4 Detection of Multiple Folders

- After `scan_folder()`, extract unique parent folders from all image paths
- If only one unique folder: hide FolderFilterPanel
- If multiple unique folders: show FolderFilterPanel, populate combobox

---

## Task 10: Final Integration and Testing

**Goal:** Wire everything together and ensure all components work harmoniously.

### 10.1 Update `__main__.py`
- Handle optional folder argument
- Initialize all managers (ThumbnailManager, MetadataDB per folder)
- Pass required references to MainWindow

### 10.2 Update `MainWindow.__init__`
- Accept optional folder (can be None)
- Create EmptyStatePanel for no-folder state
- Create FolderFilterPanel
- Create EditPanel (if config enabled)
- Wire all signals
- Initialize MetadataDB for each unique folder in the scan

### 10.3 State Management
- Track: current folder(s), current filter, current selection
- Ensure state is consistent across all panels when:
  - Folder is opened
  - Filter is changed
  - Selection is changed
  - Photos are scrolled

### 10.4 Error Handling
- Database write failures: show error message, don't crash
- Invalid input in edit fields: show validation error, don't save
- Missing folders: graceful handling, clear last_folder.json if folder no longer exists

---

## File Summary

**New files to create:**
1. `src/piqopiqo/support.py` - Platform support directory utilities
2. `src/piqopiqo/empty_state.py` - Empty state panel widget
3. `src/piqopiqo/edit_panel.py` - Editable metadata panel and database
4. `src/piqopiqo/filter_panel.py` - Folder filter panel

**Files to modify:**
1. `src/piqopiqo/config.py` - New config options
2. `src/piqopiqo/thumb_man.py` - Per-folder cache logic
3. `src/piqopiqo/__main__.py` - Optional folder, initialization changes
4. `src/piqopiqo/photo_grid.py` - Layout changes, new menu items, signal wiring

---

## Implementation Order

The tasks are designed to be implemented in sequence:

1. **Task 1** - Support directory (standalone, foundation for others)
2. **Task 2** - Cache refactor (depends on Task 1, needed for thumbnails and database)
3. **Task 3** - Regenerate thumbnails menu (depends on Task 2)
4. **Task 4** - Open folder and persistence (depends on Tasks 1, 2)
5. **Task 5** - Edit panel infrastructure (depends on Task 2 for db location)
6. **Task 6** - Edit panel UI (depends on Task 5)
7. **Task 7** - Edit panel data flow (depends on Tasks 5, 6)
8. **Task 8** - Edit panel integration (depends on Tasks 5, 6, 7)
9. **Task 9** - Folder filter panel (can be done after Task 4)
10. **Task 10** - Final integration (depends on all above)

Tasks 5-8 form the edit panel feature and should be done together.
Task 9 is somewhat independent and can be done in parallel with Tasks 5-8 after Task 4 is complete.

---

## Notes and Clarifications

### On Cache Invalidation
- If a folder is moved/renamed, it gets a new hash and new cache
- Old cache remains (manual cleanup or future "clean unused caches" feature)
- This is intentional: better to regenerate than risk showing wrong thumbnails

### On Database Location
- Database is stored alongside thumbnail cache (same folder hash)
- This keeps all folder-specific data together
- Structure: `{cache_base}/{folder_hash}/thumb/` and `{cache_base}/{folder_hash}/db/`

### On Status Labels
- The `XMP:Label` field in exiftool corresponds to `http://ns.adobe.com/xap/1.0/` Label
- This is used by Adobe products for color labels
- Values are strings: "Red", "Yellow", "Green", "Blue", "Purple"
- "No Label" in our UI means the field is not set (null)

### On GPS Conversion
- Reference file shows decimal-to-EXIF conversion (the opposite direction)
- For EXIF-to-decimal: reverse the process
- EXIF stores as: degrees + minutes + seconds + reference (N/S/E/W)
- Decimal: single float, negative for S and W

### On Keyboard Shortcuts
- macOS: Cmd is the standard modifier
- Windows/Linux: Ctrl is the standard modifier
- Qt handles this automatically with `QKeySequence.StandardKey` for common actions
- For custom shortcuts, use `QKeySequence("Ctrl+Shift+R")` etc.

---

## Implementation Summary

### Files Created
- `src/piqopiqo/support.py` - Platform-specific support directory utilities
- `src/piqopiqo/edit_panel.py` - Editable metadata panel, database manager, field widgets
- `src/piqopiqo/filter_panel.py` - Folder filter panel

### Files Modified
- `src/piqopiqo/config.py` - Added CACHE_BASE_DIR, SHOW_EDIT_PANEL, STATUS_LABELS, etc.
- `src/piqopiqo/thumb_man.py` - Per-folder cache with hash-based IDs
- `src/piqopiqo/__main__.py` - Optional folder argument, last folder persistence
- `src/piqopiqo/model.py` - Added source_folder field to ImageItem
- `src/piqopiqo/photo_grid.py` - Integrated edit panel, filter panel, new menu items

### Key Features Implemented
1. **Per-folder thumbnail cache**: Each source folder gets its own cache directory
2. **Open Folder menu**: File > Open Folder... (Ctrl+O)
3. **Regenerate Thumbnails**: File > Regenerate Thumbnails (Ctrl+Shift+R)
4. **Last folder persistence**: Saves/loads from support directory JSON
5. **Editable metadata panel**: Title, description, lat/lon, keywords, time, status
6. **SQLite database**: Created on first edit, stored alongside thumbnail cache
7. **Multi-selection support**: Shows `<Multiple Values>`, applies edits to all
8. **Folder filter**: Combobox to filter by source folder when multiple detected
