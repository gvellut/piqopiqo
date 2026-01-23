import os

from piqopiqo.model import OnFullscreenExitMultipleSelected

# Environment variable prefix for config overrides
ENV_PREFIX = "PIQO_"


class Config:
    # Application Settings
    APP_NAME = "PiqoPiqo"

    CACHE_BASE_DIR = "/Volumes/CrucialX9Pro/projects/piqopiqo/cache"

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
    ]
    EXIF_PANEL_LAYOUT = (30, 70)
    EXIF_PANEL_ROW_SPACING = 5  # Fixed spacing between rows in pixels

    # Concurrency
    MAX_WORKERS = 4

    # Grid Layout Options
    NUM_COLUMNS = 8
    PADDING = 10  # Pixels between cells/edges
    # TODO remove
    METADATA_LINES = 2  # Rows of text below image
    FONT_SIZE = 12  # Approx pixel height of text

    # Image Specs
    THUMB_MAX_DIM = 1024  # Max width/height for high-res cache

    CLEAR_CACHE_ON_START = True

    # Fullscreen overlay settings
    FULLSCREEN_BACKGROUND_COLOR = "black"

    ZOOM_FACTOR = 1.5
    ZOOM_WHEEL_SENSITIVITY = 1
    ZOOM_MAX = 2
    PAN_EMPTY_SPACE = 300

    # Info Panel
    INFO_PANEL_BACKGROUND_COLOR = "black"
    INFO_PANEL_BACKGROUND_TRANSPARENCY = 80  # Percent
    INFO_PANEL_TEXT_COLOR = "white"

    # Selection Behavior
    ON_FULLSCREEN_EXIT = OnFullscreenExitMultipleSelected.KEEP_SELECTION

    # Editable Metadata Panel
    SHOW_EDIT_PANEL = True
    TITLE_MAX_LENGTH = 128
    DESCRIPTION_MAX_LENGTH = 128

    # Status labels with colors (name, hex color)
    STATUS_LABELS = [
        ("No Label", "#808080"),
        ("Approved", "#FF0000"),
        ("Yellow", "#FFFF00"),
        ("Green", "#00FF00"),
        ("Blue", "#0000FF"),
        ("Purple", "#800080"),
    ]

    # Grid item metadata display
    # List of DB field names to show below filename in grid items
    # Available: "title", "time_taken", "keywords", "description"
    # Note: "label" is handled separately (shown as swatch, not text)
    GRID_ITEM_FIELDS = ["title", "time_taken"]

    # Show label as colored swatch on top-right of grid item
    GRID_ITEM_SHOW_LABEL_SWATCH = True


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
            if isinstance(current_value, bool):
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
