import os

from .model import ExifField, OnFullscreenExitMultipleSelected, StatusLabel
from .shortcuts import Shortcut

# Environment variable prefix for config overrides
ENV_PREFIX = "PIQO_"


class ConfigNoUserSettings:
    # options useful for testing (set with env var)

    # Keyword Tree
    # If True, the keyword tree is not persisted (in-memory only for testing)
    DETACHED_KEYWORD_TREE = False

    # Initial window resolution (format: "WIDTHxHEIGHT", e.g. "1280x800")
    # If None, the window opens maximized.
    INITIAL_RESOLUTION = None

    # internal options

    EXIF_PANEL_COLUMN_STRETCH = (30, 70)
    EXIF_PANEL_ROW_SPACING = 5  # Fixed spacing between rows in pixels

    # Show label as colored swatch on top-right of grid item
    GRID_ITEM_SHOW_LABEL_SWATCH = True

    # Auto-format exiftool keys for display when no label is provided.
    # If True: "File:FileName" => "File Name"
    # If False: uses the raw exiftool key as-is
    EXIF_AUTO_FORMAT = True

    # Concurrency
    MAX_WORKERS = 4
    # Keep at least this many idle worker processes around
    MIN_IDLE_WORKERS = 1
    # Max number of images to process per exiftool batch call
    MAX_EXIFTOOLS_IMAGE_BATCH = 8

    # Shutdown
    # Maximum time (seconds) allowed for a graceful shutdown before forcing exit.
    SHUTDOWN_TIMEOUT_S = 5.0

    # Grid Layout Options
    PADDING = 10  # Pixels between cells/edges
    FONT_SIZE = 12  # Approx pixel height of text
    GRID_ITEM_TEXT_FIELDS_TOP_PADDING = 10
    # Keep HQ thumbnails only for visible items plus a row buffer.
    GRID_THUMB_BUFFER_ROWS = 2
    # Keep embedded thumbnails for a wider buffer (reloading from disk is cheap
    # but we don't need to keep all of them in memory).
    GRID_EMBEDDED_BUFFER_ROWS = 20
    # If True, while navigating (scroll/row movement), show embedded previews and
    # switch to HQ only after idle delay.
    GRID_HQ_THUMB_DELAY_ENABLED = True
    # Delay before switching from embedded to HQ after navigation stops (ms).
    GRID_HQ_THUMB_LOAD_DELAY_MS = 100
    # If True, disable HQ thumbnail loading/generation and only use embedded
    # previews in the grid. Useful for visual debugging of low-res rendering.
    GRID_LOWRES_ONLY = False

    ZOOM_WHEEL_SENSITIVITY = 1
    PAN_EMPTY_SPACE = 300
    PAN_CURSOR_DELAY_MS = 100  # Delay before showing pan cursor on mouse press

    # Info Panel in fullscreen overlay
    INFO_PANEL_BACKGROUND_COLOR = "black"
    INFO_PANEL_BACKGROUND_TRANSPARENCY = 80  # Percent
    INFO_PANEL_TEXT_COLOR = "white"
    INFO_PANEL_MARGIN_BOTTOM = 10  # Space from bottom (or top) edge of screen
    INFO_PANEL_MARGIN_SIDE = 10  # Space from left side of screen
    INFO_PANEL_POSITION = "bottom"  # "top" or "bottom"
    INFO_PANEL_ZOOM_PERCENT_OVERLAY_TIMER_MS = 1000

    # Editable Metadata Panel
    SHOW_EDIT_PANEL = True
    TITLE_MAX_LENGTH = 128
    DESCRIPTION_MAX_LENGTH = 128

    # Grid item metadata display
    # List of DB field names to show below filename in grid items
    # TODO add setting : do not show title
    # TODO add setting : if no time taken : show date created in FS or do it
    # automatically
    GRID_ITEM_FIELDS = ["title", "time_taken"]


class Config(ConfigNoUserSettings):
    # FIXME Add verification for existence + dialog to set at startup
    # or set to computed ie in Library Application Support
    # "/Volumes/CrucialX9Pro/projects/piqopiqo/cache"
    # # "/Volumes/CrucialX8/projects/piqopiqo/cache"
    CACHE_BASE_DIR = "/Volumes/CrucialX9Pro/projects/piqopiqo/cache"

    # EXIF tool
    # None for taken from PATH : with PyInstaller : not taken into account
    # FIXME add verification + dialog to set at startup
    EXIFTOOL_PATH = "/opt/homebrew/bin/exiftool"

    EXIF_FIELDS = [
        ExifField("EXIF:FocalLength"),
        ExifField("Composite:ShutterSpeed", "Shutter Speed"),
        ExifField("EXIF:FNumber", "F-Number"),
        ExifField("EXIF:ISO"),
        ExifField("EXIF:DateTimeOriginal", "Date/Time Original"),
        ExifField("File:FileName", "File Name"),
    ]

    # Grid Layout Options
    NUM_COLUMNS = 6

    # Image Specs
    THUMB_MAX_DIM = 1024  # Max width/height for high-res cache

    CLEAR_CACHE_ON_START = False

    # Fullscreen overlay settings
    FULLSCREEN_BACKGROUND_COLOR = "black"

    # Selection Behavior
    ON_FULLSCREEN_EXIT = OnFullscreenExitMultipleSelected.KEEP_SELECTION

    # Status labels (name, hex color, index for shortcut key)
    STATUS_LABELS = [
        StatusLabel("Approved", "#FF0000", 1),
        StatusLabel("Rejected", "#FFFF00", 2),
        StatusLabel("Uploaded", "#00FF00", 3),
        StatusLabel("Verification", "#0000FF", 4),
    ]

    # External applications
    # Application name for viewing photos (e.g. "Preview", "Adobe Lightroom")
    # Empty string = disabled (menu item hidden)
    EXTERNAL_VIEWER = "Gimp"
    # Application name for editing photos (e.g. "Photoshop", "Affinity Photo")
    # Empty string = disabled (menu item hidden)
    EXTERNAL_EDITOR = "Gimp"

    # Keyboard shortcuts (key combinations, e.g. "ctrl+r", "cmd+alt+t", "=")
    # Modifier keys: ctrl, alt, cmd/meta, shift. Separator: +
    # Some work only in fullscreen (Zoom), the labels work in both, the select
    SHORTCUTS = {
        Shortcut.ZOOM_IN: "=",
        Shortcut.ZOOM_OUT: "-",
        Shortcut.ZOOM_RESET: "0",
        Shortcut.LABEL_1: "1",
        Shortcut.LABEL_2: "2",
        Shortcut.LABEL_3: "3",
        Shortcut.LABEL_4: "4",
        Shortcut.LABEL_5: "5",
        Shortcut.LABEL_6: "6",
        Shortcut.LABEL_7: "7",
        Shortcut.LABEL_8: "8",
        Shortcut.LABEL_9: "9",
        Shortcut.LABEL_NONE: "`",
        Shortcut.SELECT_ALL: "ctrl+a",
    }

    COPY_SD_BASE_EXTERNAL_FOLDER = "/Volumes/CrucialX8/photos"


def apply_env_overrides():
    """Apply environment variable overrides to Config class attributes.

    Environment variables starting with PIQO_ will override the corresponding
    Config attributes. For example, PIQO_NUM_COLUMNS will override Config.NUM_COLUMNS.

    Type conversion is attempted based on the original attribute type:
    - int: converts to integer
    - float: converts to float
    - bool: converts to boolean (accepts: true/false, yes/no, 1/0, case-insensitive)
    - str: used as-is
    - list: splits comma-separated values
    - None: treated as string (for optional string fields)
    """
    for env_var, value in os.environ.items():
        if not env_var.startswith(ENV_PREFIX):
            continue

        # Extract the config attribute name
        attr_name = env_var[len(ENV_PREFIX) :]

        # Check if this attribute exists in Config
        if not hasattr(Config, attr_name):
            continue

        # Get the current value to determine the type
        current_value = getattr(Config, attr_name)

        # Convert the environment variable value to the appropriate type
        try:
            if current_value is None:
                # None defaults are optional strings
                converted_value = value
            elif isinstance(current_value, bool):
                # Handle boolean conversion
                converted_value = value.lower() in ("true", "yes", "1")
            elif isinstance(current_value, int):
                converted_value = int(value)
            elif isinstance(current_value, float):
                converted_value = float(value)
            elif isinstance(current_value, list):
                # Split comma-separated values
                converted_value = [item.strip() for item in value.split(",")]
            else:
                # Default to string
                converted_value = value

            # Apply the override
            setattr(Config, attr_name, converted_value)

        except (ValueError, TypeError):
            # Skip if conversion fails
            continue
