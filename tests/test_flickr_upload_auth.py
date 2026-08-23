"""Tests for Flickr auth and token path helpers."""

from __future__ import annotations

import threading

from piqopiqo.cache_paths import get_flickr_token_file_path, set_cache_base_dir
from piqopiqo.tools.flickr_tools.upload.constants import (
    FLICKR_TOKEN_DB_FILENAME,
    FLICKR_TOKEN_DIR_NAME,
)
from piqopiqo.tools.flickr_utils import (
    authenticate_via_browser_cancellable,
    create_flickr_client,
    validate_token_or_cleanup,
)


def test_flickr_token_file_path_uses_cache_base(tmp_path) -> None:
    set_cache_base_dir(tmp_path / "cache")
    token_path = get_flickr_token_file_path()
    assert token_path == (
        tmp_path / "cache" / FLICKR_TOKEN_DIR_NAME / FLICKR_TOKEN_DB_FILENAME
    )


def test_create_flickr_client_sets_required_default_timeout(
    tmp_path, monkeypatch
) -> None:
    calls: list[dict] = []

    class _Session:
        headers: dict[str, str] = {}

    class _OAuth:
        session = _Session()

    class _FakeFlickrApi:
        flickr_oauth = _OAuth()

        def __init__(self, *_args, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(
        "piqopiqo.tools.flickr_utils.flickrapi.FlickrAPI",
        _FakeFlickrApi,
    )

    create_flickr_client(
        "k",
        "s",
        token_cache_dir=tmp_path,
        timeout_s=5.0,
    )

    assert calls[0]["timeout"] == 5.0


def test_validate_token_or_cleanup_removes_invalid_token_file(
    tmp_path, monkeypatch
) -> None:
    token_cache_dir = tmp_path / "cache" / FLICKR_TOKEN_DIR_NAME
    token_cache_dir.mkdir(parents=True)
    token_file = token_cache_dir / FLICKR_TOKEN_DB_FILENAME
    token_file.write_text("dummy", encoding="utf-8")

    class _FakeFlickr:
        def token_valid(self, perms: str) -> bool:  # noqa: ARG002
            return False

    client_calls: list[dict] = []

    def create_client(*_args, **kwargs):
        client_calls.append(kwargs)
        return _FakeFlickr()

    monkeypatch.setattr(
        "piqopiqo.tools.flickr_utils.create_flickr_client",
        create_client,
    )

    is_valid = validate_token_or_cleanup(
        "k",
        "s",
        timeout_s=5.0,
        token_cache_dir=token_cache_dir,
    )

    assert is_valid is False
    assert token_file.exists() is False
    assert client_calls[0]["timeout_s"] == 5.0


def test_authenticate_via_browser_cancel_stops_http_server(monkeypatch) -> None:
    cancel_event = threading.Event()

    class _FakeServer:
        def __init__(self):
            self.closed = False

        def wait_for_oauth_verifier(self, timeout=None):  # noqa: ARG002
            cancel_event.set()
            return None

        def server_close(self):
            self.closed = True

    class _FakeOAuth:
        def __init__(self, server):
            self.auth_http_server = server
            self.stopped = False

        def _stop_http_server(self):
            self.stopped = True
            self.auth_http_server = None

    class _FakeFlickr:
        def __init__(self):
            self.server = _FakeServer()
            self.flickr_oauth = _FakeOAuth(self.server)

        def get_request_token(self):
            return None

        def auth_url(self, perms: str):  # noqa: ARG002
            return "http://example.com"

        def get_access_token(self, verifier=None):  # noqa: ARG002
            raise AssertionError("Should not fetch access token when cancelled")

    monkeypatch.setattr(
        "piqopiqo.tools.flickr_utils.webbrowser.open_new_tab",
        lambda _url: True,
    )

    fake_flickr = _FakeFlickr()
    result = authenticate_via_browser_cancellable(fake_flickr, cancel_event)

    assert result.cancelled is True
    assert fake_flickr.server.closed is True
    assert fake_flickr.flickr_oauth.stopped is True
