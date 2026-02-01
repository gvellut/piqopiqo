from enum import auto
import os

from .model import OnFullscreenExitMultipleSelected, StatusLabel
from .utils import UpperStrEnum

# Environment variable prefix for config overrides
ENV_PREFIX = "PIQO_"


class Shortcut(UpperStrEnum):
    ZOOM_IN = auto()
    ZOOM_OUT = auto()
    ZOOM_RESET = auto()
    LABEL_1 = auto()
    LABEL_2 = auto()
    LABEL_3 = auto()
    LABEL_4 = auto()
    LABEL_5 = auto()
    LABEL_6 = auto()
    LABEL_7 = auto()
    LABEL_8 = auto()
    LABEL_9 = auto()
    LABEL_NONE = auto()


class Config:
    # Application Settings
    APP_NAME = "PiqoPiqo"

    # "/Volumes/CrucialX9Pro/projects/piqopiqo/cache"
    CACHE_BASE_DIR = "/Volumes/CrucialX8/projects/piqopiqo/cache"

    # Initial window resolution (format: "WIDTHxHEIGHT", e.g. "1280x800")
    # If None, the window opens maximized.
    INITIAL_RESOLUTION = None

    # EXIF Panel
    EXIFTOOL_PATH = None
    EXIF_FIELDS = [
        "EXIF:ExposureTime",
        "EXIF:FNumber",
        "EXIF:ExposureProgram",
        "EXIF:ISO",
        "EXIF:DateTimeOriginal",
        "EXIF:CreateDate",
        "EXIF:ShutterSpeedValue",
        "EXIF:ApertureValue",
        "EXIF:FocalLength",
        "EXIF:LensModel",
        "File:FileName",
        "File:FileModifyDate",
    ]
    EXIF_PANEL_LAYOUT = (30, 70)
    EXIF_PANEL_ROW_SPACING = 5  # Fixed spacing between rows in pixels

    # Concurrency
    MAX_WORKERS = 4

    # Shutdown
    # Maximum time (seconds) allowed for a graceful shutdown before forcing exit.
    SHUTDOWN_TIMEOUT_S = 5.0

    # Grid Layout Options
    NUM_COLUMNS = 8
    PADDING = 10  # Pixels between cells/edges
    # TODO remove
    METADATA_LINES = 2  # Rows of text below image
    FONT_SIZE = 12  # Approx pixel height of text

    # Image Specs
    THUMB_MAX_DIM = 1024  # Max width/height for high-res cache

    CLEAR_CACHE_ON_START = False

    # Fullscreen overlay settings
    FULLSCREEN_BACKGROUND_COLOR = "black"

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

    # Selection Behavior
    ON_FULLSCREEN_EXIT = OnFullscreenExitMultipleSelected.KEEP_SELECTION

    # Editable Metadata Panel
    SHOW_EDIT_PANEL = True
    TITLE_MAX_LENGTH = 128
    DESCRIPTION_MAX_LENGTH = 128

    # Status labels (name, hex color, index for shortcut key)
    STATUS_LABELS = [
        StatusLabel("Approved", "#FF0000", 1),
        StatusLabel("Rejected", "#FFFF00", 2),
        StatusLabel("Uploaded", "#00FF00", 3),
        StatusLabel("Verification", "#0000FF", 4),
    ]

    # Grid item metadata display
    # List of DB field names to show below filename in grid items
    # Available: "title", "time_taken", "keywords", "description"
    # Note: "label" is handled separately (shown as swatch, not text)
    GRID_ITEM_FIELDS = ["title", "time_taken"]

    # Show label as colored swatch on top-right of grid item
    GRID_ITEM_SHOW_LABEL_SWATCH = True

    # Keyboard shortcuts (key combinations, e.g. "ctrl+r", "cmd+alt+t", "=")
    # Modifier keys: ctrl, alt, cmd/meta, shift. Separator: +
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
    }


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
