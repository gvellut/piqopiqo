# PiqoPiqo

Photo viewer / metadata viewer + editor built with Python 3 and PySide6 (Qt).

## Running the Application

For testing that all the imports work and that the app initializes correctly. As well as testing that the changes are correct, using PyQtAuto (PIQO_INITIAL_RESOLUTION and PIQO_NUM_COLUMNS for setting suitable values)

```bash
# Run with a folder path
uv run piqopiqo /path/to/images

# Run without arguments (opens last folder)
uv run piqopiqo

# Run with environment variable overrides
PIQO_NUM_COLUMNS=10 uv run piqopiqo /path/to/images
```

## Project Structure

```
src/piqopiqo/
├── __main__.py      # Entry point, CLI with click, Qt app setup
├── config.py        # Configuration class with env var overrides (PIQO_ prefix)
├── main_window.py   # Main application window
├── photo_model.py   # PhotoListModel: filtering, sorting, selection, add/remove photos
├── shortcuts.py     # Keyboard shortcut matching utilities
├── model.py         # Data models (ImageItem, FilterCriteria, StatusLabel, ExifField)
├── exif_loader.py   # EXIF metadata loading (background thread)
├── exif_man.py      # EXIF I/O manager (on-demand fetch + write to files)
├── thumb_man.py     # Thumbnail generation and caching (multiprocessing)
├── support.py       # Support functions (cache dir, last folder persistence)
├── utils.py         # Logging setup and utilities
├── label_utils.py   # Status label color utilities
├── orientation.py   # EXIF orientation handling and rotation utilities
├── metadata/        # Database layer
│   ├── metadata_db.py   # SQLite database for cached metadata
│   ├── db_fields.py     # Database field definitions and EXIF mappings
│   └── save_workers.py  # Background worker to save metadata
├── components/      # Reusable UI components
│   └── ellided_label.py   # Truncated label with ellipsis
├── fullscreen/      # Fullscreen image viewing
│   ├── overlay.py   # Fullscreen overlay widget
│   ├── pan.py       # Pan logic for zoomed images
│   └── zoom.py      # Zoom state management
├── grid/            # Photo grid display
│   ├── photo_cell.py    # Single photo cell widget (left/right click)
│   └── photo_grid.py    # Grid of photo thumbnails with context menu
├── panels/          # Side panels
│   ├── edit_panel.py      # Editable metadata panel
│   ├── edit_widgets.py    # Field editor widgets
│   ├── exif_panel.py      # Read-only EXIF display
│   ├── filter_panel.py    # Filtering UI
│   ├── save_exif_dialog.py # Dialog for saving metadata to EXIF
│   └── status_bar.py      # Status bar component
└── platform/        # Platform-specific code
    └── macos.py     # macOS utilities (resolution, move_to_trash)
```

## Key Features

- **Grid view**: Thumbnails with configurable columns, lazy loading
- **Fullscreen**: Full resolution with zoom/pan, keyboard navigation
- **EXIF panel**: Read-only EXIF data display (uses pyexiftool)
- **Edit panel**: Editable metadata (title, description, keywords, coordinates, time taken)
- **Filter panel**: Fields to use for filtering the images displayed on the photo grid
- **Thumbnail caching**: Multiprocessing pipeline, cached to disk
- **Status labels**: Configurable colored labels for photo workflow
- **Sorting**: View menu with sort by Time Taken, File Name, File Name by Folder
- **Context menu**: Right-click on photos for Duplicate and Move to Trash actions
- **Refresh**: Ctrl+R to rescan folder for external file changes
- **Image rotation**: Image menu with Rotate Left/Right (Ctrl+[/]) to rotate photos
- **Save EXIF**: Tools menu to write DB metadata back to image files using exiftool

## PhotoListModel Architecture

The `photo_model.py` module contains `PhotoListModel`, a QObject that manages:
- All photos (`all_photos`) and filtered/sorted view (`photos`)
- Filtering via `set_filter(FilterCriteria)`
- Sorting via `set_sort_order(SortOrder)` - TIME_TAKEN, FILE_NAME, FILE_NAME_BY_FOLDER
- Selection management
- Photo addition (queues thumbnail/EXIF loading, cleans up on removal)
- Signals: `photos_changed`, `photo_added`, `photo_removed`, `selection_changed`

MainWindow uses properties `images_data` and `_all_images_data` that delegate to the model for backward compatibility.

## Configuration

All settings in `config.py` can be overridden via environment variables with `PIQO_` prefix:

- `PIQO_NUM_COLUMNS` - Grid columns (default: 8)
- `PIQO_CACHE_BASE_DIR` - Thumbnail cache location
- `PIQO_THUMB_MAX_DIM` - Max thumbnail dimension (default: 1024)
- `PIQO_CLEAR_CACHE_ON_START` - Clear cache on startup (default: false)
- `PIQO_INITIAL_RESOLUTION` - Initial window size as `WIDTHxHEIGHT` (e.g. `1280x800`). If not set, window opens maximized.

## EXIF Panel Configuration

EXIF fields are defined in `Config.EXIF_FIELDS` as a list of `ExifField` objects:
- `ExifField(key, label)` - key is the exiftool field (e.g., "EXIF:DateTimeOriginal"), label is optional display name
- If `label` is None and `EXIF_AUTO_FORMAT` is True, the key is auto-formatted (e.g., "File:FileName" → "File Name")
- `format_exif_key(key)` function handles the auto-formatting (removes prefix, adds spaces around capitals)

## Edit Panel

The edit panel supports editing metadata fields (title, description, keywords, coordinates, time taken).
- **Auto-save on focus out**: When user leaves a field to focus elsewhere, changes are automatically saved to DB
- **Enter/Tab**: Saves the field and moves focus
- **Escape**: Reverts changes and cancels edit
- Validation is applied for coordinates and datetime fields (red border on invalid input)

## Keyboard Shortcuts

Shortcuts are defined in `config.py` `Config.SHORTCUTS` dict (shortcut name => key combo string).

- **Zoom (fullscreen only)**: `=` zoom in, `-` zoom out, `0` reset zoom
- **Labels (grid + fullscreen)**: `1`-`9` set label by index, `` ` `` (backtick) clears label
- **Rotation**: `Ctrl+[` rotate left, `Ctrl+]` rotate right
- **Refresh**: `Ctrl+R` rescan folder for changes
- Labels are defined in `Config.STATUS_LABELS` as `StatusLabel(name, color, index)`

## Save EXIF (Tools Menu)

The "Tools > Save exif" action writes DB metadata back to image files using exiftool:
- Operates on selected photos, or all filtered photos if none selected
- Shows dialog with progress bar and error log
- Uses MWG (Metadata Working Group) composite tags where available for cross-format compatibility
- Adds XMP history (HistoryAction, HistoryWhen, HistorySoftwareAgent) and processing metadata (ProcessingSoftware, MetadataDate)

### EXIF Field Mappings

Defined in `db_fields.py`:
- **EXIF_TO_DB_MAPPING**: Maps DB fields to EXIF tags for reading (uses MWG:Description, MWG:Keywords)
- **DB_TO_EXIF_WRITE_MAPPING**: Maps DB fields to EXIF tags for writing

| DB Field | Read From | Write To |
|----------|-----------|----------|
| TITLE | XMP:Title, IPTC:ObjectName | XMP:Title + IPTC:ObjectName |
| DESCRIPTION | MWG:Description | MWG:Description |
| KEYWORDS | MWG:Keywords | MWG:Keywords |
| LATITUDE | EXIF:GPSLatitude | EXIF:GPSLatitude + GPSLatitudeRef |
| LONGITUDE | EXIF:GPSLongitude | EXIF:GPSLongitude + GPSLongitudeRef |
| TIME_TAKEN | EXIF:DateTimeOriginal | EXIF:DateTimeOriginal |
| LABEL | XMP:Label | XMP:Label |
| ORIENTATION | EXIF:Orientation | EXIF:Orientation |

### Version

Package version is defined in `__init__.py` as `__version__ = "1"` and used in XMP metadata.

## Image Rotation (Image Menu)

The "Image" menu provides rotation controls for selected photos:
- **Rotate Left** (`Ctrl+[`): Rotates 90° counter-clockwise
- **Rotate Right** (`Ctrl+]`): Rotates 90° clockwise

### How Rotation Works

1. EXIF orientation is read from image files and stored in the DB on import
2. Orientation is applied when displaying (grid thumbnails and fullscreen)
3. Rotation modifies the orientation value in the DB (not the original file)
4. "Save EXIF" writes the modified orientation back to image files

### EXIF Orientation Values

Orientation is stored as an integer (1-8) representing the transform needed:
- 1 = Normal (no transform)
- 3 = Rotate 180°
- 6 = Rotate 90° CW
- 8 = Rotate 270° CW (= 90° CCW)
- Values 2, 4, 5, 7 include horizontal/vertical mirroring

The `orientation.py` module provides utilities for:
- Rotation mappings (`ROTATE_LEFT_MAP`, `ROTATE_RIGHT_MAP`)
- Transform application (`apply_orientation_to_pixmap`, `get_orientation_transform`)

## Context Menu (Right-Click)

Right-click on a photo in the grid to access:
- **Duplicate**: Creates a copy with " copy" suffix (or " copy2", etc.)
- **Move to Trash**: Moves file to macOS Trash

Selection behavior:
- Right-click on unselected photo: selects only that photo
- Right-click on selected photo in multi-selection: keeps all selected, action applies to all

## Dependencies

- `uv` for Python project management (deps in `pyproject.toml`)
- `exiftool` must be installed on the system
- Key packages: PySide6, pyexiftool, Pillow, click, attrs, send2trash

## Development

```bash
# Install dependencies
uv sync

# Install with dev dependencies (includes pyqtauto for testing)
uv sync --all-extras

# Run linting and formatting. Always use --fix.
ruff check --fix
ruff format
```

## Update of Claude.md

After completing a feature, update this file CLAUDE.md with the updated project structure. Also add considerations for reference for future work.