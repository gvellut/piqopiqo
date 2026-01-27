# PiqoPiqo

Photo viewer / metadata viewer + editor built with Python 3 and PySide6 (Qt).

## Running the Application

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
├── photo_grid.py    # MainWindow, grid view, fullscreen, selection handling
├── edit_panel.py    # Editable metadata panel (title, description, keywords, label)
├── filter_panel.py  # Filtering UI
├── exif_loader.py   # EXIF metadata loading
├── exif_man.py      # EXIF management utilities
├── metadata_db.py   # SQLite database for cached metadata
├── thumb_man.py     # Thumbnail generation and caching (multiprocessing)
├── status_bar.py    # Status bar component
├── model.py         # Data models and enums
├── components.py    # Reusable UI components
├── support.py       # Support functions (cache dir, last folder persistence)
├── utils.py         # Logging setup and utilities
└── db_fields.py     # Database field definitions
```

## Key Features

- **Grid view**: Thumbnails with configurable columns, lazy loading
- **Fullscreen**: Full resolution with zoom/pan, keyboard navigation
- **EXIF panel**: Read-only EXIF data display (uses pyexiftool)
- **Edit panel**: Editable metadata (title, description, keywords, coordinates, time taken)
- **Thumbnail caching**: Multiprocessing pipeline, cached to disk
- **Status labels**: Configurable colored labels for photo workflow

## Configuration

All settings in `config.py` can be overridden via environment variables with `PIQO_` prefix:

- `PIQO_NUM_COLUMNS` - Grid columns (default: 8)
- `PIQO_CACHE_BASE_DIR` - Thumbnail cache location
- `PIQO_THUMB_MAX_DIM` - Max thumbnail dimension (default: 1024)
- `PIQO_CLEAR_CACHE_ON_START` - Clear cache on startup (default: false)
- `PIQO_INITIAL_RESOLUTION` - Initial window size as `WIDTHxHEIGHT` (e.g. `1280x800`). If not set, window opens maximized.

## Keyboard Shortcuts

Shortcuts are defined in `config.py` `Config.SHORTCUTS` dict (shortcut name => key combo string).

- **Zoom (fullscreen only)**: `=` zoom in, `-` zoom out, `0` reset zoom
- **Labels (grid + fullscreen)**: `1`-`9` set label by index, `` ` `` (backtick) clears label
- Labels are defined in `Config.STATUS_LABELS` as `StatusLabel(name, color, index)`

## Dependencies

- `uv` for Python project management (deps in `pyproject.toml`)
- `exiftool` must be installed on the system
- Key packages: PySide6, pyexiftool, Pillow, click, attrs

## Development

```bash
# Install dependencies
uv sync

# Install with dev dependencies (includes pyqtauto for testing)
uv sync --all-extras

# Run linting and formatting
ruff check --fix
ruff format
```

## Update of Claude.md

After completing a feature, update this file CLAUDE.md if needed