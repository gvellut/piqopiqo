from piqopiqo.model import OnFullscreenExitMultipleSelected


class Config:
    # Application Settings
    APP_NAME = "PiqoPiqo"

    # Paths
    CACHE_DIR = "/Volumes/CrucialX9Pro/projects/piqopiqo/cache"
    # CACHE_DIR = "/Volumes/CrucialX9Pro/projects/piqopiqo/cache"

    # EXIF Panel
    EXIF_TOOL_PATH = None
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
