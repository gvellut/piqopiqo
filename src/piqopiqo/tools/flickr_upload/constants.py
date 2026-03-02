"""Constants for Flickr authentication and upload workflows."""

from __future__ import annotations

from enum import Enum, auto

FLICKR_TOKEN_DIR_NAME = "flickr"
FLICKR_TOKEN_DB_FILENAME = "oauth-tokens.sqlite"

FLICKR_REQUIRED_PERMS = "write"

# Keep aligned with flickr_api_utils defaults.
API_RETRIES = 6
API_RETRY_DELAY_S = 5
UPLOAD_TIMEOUT_S = 30
QUICK_TIMEOUT_S = 5
CHECK_TICKETS_SLEEP_S = 3
MAX_NUM_CHECKS = 10


class FlickrStage(Enum):
    STAGE_UPLOAD = auto(), "Upload"
    STAGE_CHECK_UPLOAD_STATUS = auto(), "Check upload status"
    STAGE_RESET_DATE = auto(), "Reset date"
    STAGE_MAKE_PUBLIC = auto(), "Make public"
    STAGE_ALBUM_CHECK = auto(), "Album check"
    STAGE_ADD_TO_ALBUM = auto(), "Add to album"

    def __new__(cls, name, label):
        obj = str.__new__(cls, name)

        obj._value_ = name
        return obj

    def __init__(self, name, label):
        self.label = label


FOLDER_STATE_LAST_FLICKR_ALBUM_ID = "FLICKR_ALBUM_ID"

TOKEN_VALIDATION_ERROR_TEXT = (
    "Flickr token is not valid anymore. Please login to Flickr again."
)
