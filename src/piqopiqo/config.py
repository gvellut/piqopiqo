class Config:
    # Application Settings
    APP_NAME = "PiqoPiqo"

    # Paths
    CACHE_DIR = "/Volumes/CrucialX9Pro/projects/piqopiqo/cache"
    EXIFTOOL_PATH = "exiftool"  # Assumes in PATH

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
