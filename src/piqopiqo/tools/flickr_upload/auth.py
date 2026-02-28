"""Flickr authentication helpers."""

from __future__ import annotations

import logging
from pathlib import Path
import random
import string
import threading
import webbrowser

from attrs import define
import flickrapi

from piqopiqo import __version__ as piqopiqo_version
from piqopiqo.cache_paths import get_flickr_cache_dir, get_flickr_token_file_path
from piqopiqo.ssf.settings_state import APP_NAME

from .constants import FLICKR_REQUIRED_PERMS, FLICKR_TOKEN_DB_FILENAME

logger = logging.getLogger(__name__)


@define(frozen=True)
class FlickrAuthResult:
    success: bool = False
    cancelled: bool = False
    error_message: str = ""


def _random_suffix(length: int = 5) -> str:
    pool = string.ascii_letters + string.digits
    return "".join(random.choice(pool) for _ in range(max(1, length)))


def create_flickr_client(
    api_key: str,
    api_secret: str,
    *,
    token_cache_dir: str | Path | None = None,
    response_format: str = "parsed-json",
    timeout_s: float | None = None,
) -> flickrapi.FlickrAPI:
    """Create a Flickr API client bound to the configured token cache dir."""
    cache_dir = Path(token_cache_dir) if token_cache_dir else get_flickr_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    flickr = flickrapi.FlickrAPI(
        str(api_key),
        str(api_secret),
        format=response_format,
        token_cache_location=str(cache_dir),
        timeout=timeout_s,
    )

    flickr.flickr_oauth.session.headers.update(
        {"User-Agent": f"{APP_NAME} v{piqopiqo_version}"}
    )
    return flickr


def token_file_exists(token_file_path: str | Path | None = None) -> bool:
    """Check if the OAuth token SQLite file exists on disk."""
    path = Path(token_file_path) if token_file_path else get_flickr_token_file_path()
    return path.exists() and path.is_file()


def clear_token_file(token_file_path: str | Path | None = None) -> None:
    """Delete the OAuth token SQLite file if it exists."""
    path = Path(token_file_path) if token_file_path else get_flickr_token_file_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Failed to delete Flickr token file: %s", path)


def stop_auth_http_server(flickr: flickrapi.FlickrAPI) -> None:
    """Stop the temporary local HTTP server started by flickrapi auth."""
    server = getattr(flickr.flickr_oauth, "auth_http_server", None)
    if server is None:
        return

    try:
        server.server_close()
    except Exception:
        logger.debug("Error while closing auth HTTP server", exc_info=True)

    try:
        flickr.flickr_oauth._stop_http_server()  # noqa: SLF001
    except Exception:
        logger.debug("Error while clearing auth HTTP server state", exc_info=True)


def authenticate_via_browser_cancellable(
    flickr: flickrapi.FlickrAPI,
    cancel_event: threading.Event,
    *,
    perms: str = FLICKR_REQUIRED_PERMS,
    poll_timeout_s: float = 0.25,
) -> FlickrAuthResult:
    """Authenticate through browser with cooperative cancellation."""
    if cancel_event.is_set():
        stop_auth_http_server(flickr)
        return FlickrAuthResult(cancelled=True)

    try:
        flickr.get_request_token()
        auth_url = flickr.auth_url(perms=perms)

        if not webbrowser.open_new_tab(auth_url):
            stop_auth_http_server(flickr)
            return FlickrAuthResult(
                error_message=f"Unable to open browser for {auth_url}"
            )

        auth_server = getattr(flickr.flickr_oauth, "auth_http_server", None)
        if auth_server is None:
            stop_auth_http_server(flickr)
            return FlickrAuthResult(
                error_message="Authentication server was not started."
            )

        verifier = None
        while not cancel_event.is_set():
            verifier = auth_server.wait_for_oauth_verifier(timeout=poll_timeout_s)
            if verifier:
                break

        if cancel_event.is_set():
            stop_auth_http_server(flickr)
            return FlickrAuthResult(cancelled=True)

        if not verifier:
            stop_auth_http_server(flickr)
            return FlickrAuthResult(
                error_message="Authentication verifier not received."
            )

        flickr.get_access_token(verifier=verifier)
        stop_auth_http_server(flickr)
        return FlickrAuthResult(success=True)
    except Exception as ex:  # pragma: no cover - external API/browser/system failure
        stop_auth_http_server(flickr)
        return FlickrAuthResult(error_message=str(ex))


def validate_token_or_cleanup(
    api_key: str,
    api_secret: str,
    *,
    token_cache_dir: str | Path | None = None,
    perms: str = FLICKR_REQUIRED_PERMS,
) -> bool:
    """Return whether token is valid; invalid tokens trigger token-file cleanup."""
    flickr = create_flickr_client(
        api_key,
        api_secret,
        token_cache_dir=token_cache_dir,
        response_format="parsed-json",
    )
    valid = bool(flickr.token_valid(perms=perms))
    if not valid:
        # FIXME normally the token_valid of flickrapi lib took care of the deletion
        # if not valid. Check and remove if the case
        if token_cache_dir:
            clear_token_file(Path(token_cache_dir) / FLICKR_TOKEN_DB_FILENAME)
        else:
            clear_token_file()
    return valid
