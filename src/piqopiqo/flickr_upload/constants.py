"""Constants for Flickr authentication and upload workflows."""

from __future__ import annotations

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

STAGE_UPLOAD = "Upload"
STAGE_RESET_DATE = "Reset date"
STAGE_MAKE_PUBLIC = "Make public"

TOKEN_VALIDATION_ERROR_TEXT = (
    "Flickr token is not valid anymore. Please login to Flickr again."
)
