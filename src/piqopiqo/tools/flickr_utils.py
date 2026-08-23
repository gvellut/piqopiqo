"""Shared Flickr authentication and API helpers for application tools."""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path
import random
import re
import string
import threading
import time
from typing import Any
import webbrowser

from attrs import define
import flickrapi

from piqopiqo import __version__ as piqopiqo_version
from piqopiqo.cache_paths import get_flickr_cache_dir, get_flickr_token_file_path
from piqopiqo.ssf.settings_state import APP_NAME

logger = logging.getLogger(__name__)

FLICKR_TOKEN_DIR_NAME = "flickr"
FLICKR_TOKEN_DB_FILENAME = "oauth-tokens.sqlite"
FLICKR_REQUIRED_PERMS = "write"
DEFAULT_API_RETRY_DELAY_S = 5.0


@define(frozen=True)
class FlickrAuthResult:
    success: bool = False
    cancelled: bool = False
    error_message: str = ""


class FlickrOperationCancelled(RuntimeError):
    """Raised internally when a Flickr worker is cooperatively cancelled."""


def _random_suffix(length: int = 5) -> str:
    pool = string.ascii_letters + string.digits
    return "".join(random.choice(pool) for _ in range(max(1, length)))


def create_flickr_client(
    api_key: str,
    api_secret: str,
    *,
    token_cache_dir: str | Path | None = None,
    response_format: str = "parsed-json",
    timeout_s: float,
) -> flickrapi.FlickrAPI:
    """Create a Flickr API client bound to the configured token cache directory."""
    cache_dir = Path(token_cache_dir) if token_cache_dir else get_flickr_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    flickr = flickrapi.FlickrAPI(
        str(api_key),
        str(api_secret),
        format=response_format,
        token_cache_location=str(cache_dir),
        timeout=timeout_s,
    )
    flickr.flickr_oauth.session.headers.update({
        "User-Agent": f"{APP_NAME} v{piqopiqo_version}"
    })
    return flickr


def token_file_exists(token_file_path: str | Path | None = None) -> bool:
    """Return whether the OAuth token SQLite file exists on disk."""
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
    """Authenticate through the browser with cooperative cancellation."""
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
    except Exception as ex:  # pragma: no cover - browser/system/API failure
        stop_auth_http_server(flickr)
        return FlickrAuthResult(error_message=str(ex))


def validate_token_or_cleanup(
    api_key: str,
    api_secret: str,
    *,
    timeout_s: float,
    token_cache_dir: str | Path | None = None,
    perms: str = FLICKR_REQUIRED_PERMS,
) -> bool:
    """Return whether the token is valid and remove an invalid token file."""
    flickr = create_flickr_client(
        api_key,
        api_secret,
        token_cache_dir=token_cache_dir,
        response_format="parsed-json",
        timeout_s=timeout_s,
    )
    valid = bool(flickr.token_valid(perms=perms))
    if not valid:
        if token_cache_dir:
            clear_token_file(Path(token_cache_dir) / FLICKR_TOKEN_DB_FILENAME)
        else:
            clear_token_file()
    return valid


def extract_album_id(value: str) -> str:
    """Extract an album ID from a numeric ID or supported Flickr URL."""
    text = str(value or "").strip()
    if text.isdigit():
        return text
    match = re.search(r"flickr\.com/photos/[^/]+/(?:albums|sets)/(\d+)", text)
    if match:
        return str(match.group(1))
    raise ValueError(f"Not a valid Flickr album URL or ID: {text}")


def extract_photo_id(value: str) -> str:
    """Extract a photo ID from a numeric ID or supported Flickr URL."""
    text = str(value or "").strip()
    if text.isdigit():
        return text
    match = re.search(r"flickr\.com/photos/[^/]+/(\d+)", text)
    if match:
        return str(match.group(1))
    raise ValueError(f"Not a valid Flickr photo URL or ID: {text}")


def format_flickr_tags(tags: list[str] | tuple[str, ...] | None) -> str | None:
    """Format tag values as Flickr's quoted, space-separated API argument."""
    if not tags:
        return None

    cleaned: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        text = str(tag).strip()
        if not text:
            continue
        if '"' in text:
            raise ValueError('" should not be in a Flickr tag')
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(f'"{text}"')
    return " ".join(cleaned) if cleaned else None


def retry[T](
    num_retries: int,
    func: Callable[[], T],
    error_callback: Callable[[Exception], tuple[bool, bool]] | None = None,
    *,
    delay_s: float = DEFAULT_API_RETRY_DELAY_S,
) -> T | None:
    """Retry a Flickr call and optionally delegate error short-circuit policy."""
    remaining = max(1, int(num_retries))
    while remaining > 0:
        try:
            return func()
        except Exception as ex:
            if error_callback is not None:
                return_now, raise_now = error_callback(ex)
                if return_now:
                    return None
                if raise_now:
                    raise
            remaining -= 1
            if remaining > 0:
                time.sleep(max(0.0, float(delay_s)))
                continue
            raise
    return None


def as_list(value: Any) -> list:
    """Normalize a Flickr response node to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def all_pages(
    page_elem: str,
    iter_elem: str,
    func: Callable[..., object],
    *args,
    num_retries: int = 1,
    retry_delay_s: float = DEFAULT_API_RETRY_DELAY_S,
    cancel_event: threading.Event | None = None,
    **kwargs,
) -> list:
    """Collect every page from a parsed-json Flickr response."""
    page = 1
    collected: list = []
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise FlickrOperationCancelled()
        response = retry(
            num_retries,
            lambda: func(*args, **kwargs, page=page),  # noqa: B023
            delay_s=retry_delay_s,
        )
        container = response.get(page_elem) if isinstance(response, dict) else None
        if not isinstance(container, dict):
            raise RuntimeError(f"Flickr response has no '{page_elem}' payload.")
        collected.extend(as_list(container.get(iter_elem)))
        try:
            current_page = int(container.get("page", page))
            total_pages = int(container.get("pages", 1))
        except (TypeError, ValueError) as ex:
            raise RuntimeError("Flickr response has invalid pagination data.") from ex
        if current_page >= total_pages:
            return collected
        page += 1
