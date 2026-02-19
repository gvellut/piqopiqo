"""Qt workers for Flickr auth, token validation and album resolution."""

from __future__ import annotations

from pathlib import Path
import threading

from PySide6.QtCore import QObject, QRunnable, Signal

from piqopiqo.cache_paths import get_flickr_cache_dir, get_flickr_token_file_path

from .albums import FlickrAlbumPlan, resolve_album_plan
from .auth import (
    authenticate_via_browser_cancellable,
    create_flickr_client,
    validate_token_or_cleanup,
)


class FlickrLoginWorkerSignals(QObject):
    finished = Signal(object)  # FlickrAuthResult
    cancelled = Signal()
    error = Signal(str)


class FlickrLoginWorker(QRunnable):
    """Background Flickr browser-auth worker."""

    def __init__(self, *, api_key: str, api_secret: str):
        super().__init__()
        self._api_key = api_key
        self._api_secret = api_secret
        self._cancel_requested = threading.Event()
        self.signals = FlickrLoginWorkerSignals()

    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def run(self) -> None:
        if self._cancel_requested.is_set():
            self.signals.cancelled.emit()
            return

        try:
            flickr = create_flickr_client(
                self._api_key,
                self._api_secret,
                token_cache_dir=get_flickr_cache_dir(),
                response_format="parsed-json",
            )
            result = authenticate_via_browser_cancellable(
                flickr,
                self._cancel_requested,
            )
        except Exception as ex:  # pragma: no cover - external API/system failures
            if self._cancel_requested.is_set():
                self.signals.cancelled.emit()
                return
            self.signals.error.emit(str(ex))
            return

        if result.cancelled or self._cancel_requested.is_set():
            self.signals.cancelled.emit()
            return

        if result.error_message:
            self.signals.error.emit(result.error_message)
            return

        self.signals.finished.emit(result)


class FlickrTokenValidationWorkerSignals(QObject):
    finished = Signal(bool)
    cancelled = Signal()
    error = Signal(str)


class FlickrTokenValidationWorker(QRunnable):
    """Background token validation worker."""

    def __init__(self, *, api_key: str, api_secret: str):
        super().__init__()
        self._api_key = api_key
        self._api_secret = api_secret
        self._cancel_requested = threading.Event()
        self.signals = FlickrTokenValidationWorkerSignals()

    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def run(self) -> None:
        if self._cancel_requested.is_set():
            self.signals.cancelled.emit()
            return

        try:
            token_file_path = get_flickr_token_file_path()
            cache_dir = Path(token_file_path).parent
            valid = validate_token_or_cleanup(
                self._api_key,
                self._api_secret,
                token_cache_dir=cache_dir,
            )
        except Exception as ex:  # pragma: no cover - external API/system failures
            if self._cancel_requested.is_set():
                self.signals.cancelled.emit()
                return
            self.signals.error.emit(str(ex))
            return

        if self._cancel_requested.is_set():
            self.signals.cancelled.emit()
            return

        self.signals.finished.emit(valid)


class FlickrAlbumCheckWorkerSignals(QObject):
    finished = Signal(object)  # FlickrAlbumPlan
    cancelled = Signal()
    error = Signal(str)


class FlickrAlbumCheckWorker(QRunnable):
    """Background worker resolving Flickr album input."""

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        album_text: str,
        cached_plan: dict[str, object] | None = None,
    ):
        super().__init__()
        self._api_key = api_key
        self._api_secret = api_secret
        self._album_text = str(album_text or "")
        self._cached_plan = cached_plan
        self._cancel_requested = threading.Event()
        self.signals = FlickrAlbumCheckWorkerSignals()

    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def run(self) -> None:
        if self._cancel_requested.is_set():
            self.signals.cancelled.emit()
            return

        try:
            token_file_path = get_flickr_token_file_path()
            cache_dir = Path(token_file_path).parent
            flickr = create_flickr_client(
                self._api_key,
                self._api_secret,
                token_cache_dir=cache_dir,
                response_format="parsed-json",
            )
            plan = resolve_album_plan(
                flickr,
                self._album_text,
                cached_plan=FlickrAlbumPlan.from_dict(self._cached_plan),
            )
        except Exception as ex:  # pragma: no cover - external API/system failures
            if self._cancel_requested.is_set():
                self.signals.cancelled.emit()
                return
            self.signals.error.emit(str(ex))
            return

        if self._cancel_requested.is_set():
            self.signals.cancelled.emit()
            return

        self.signals.finished.emit(plan)
