"""Qt workers for Flickr auth and token validation."""

from __future__ import annotations

from pathlib import Path
import threading

from PySide6.QtCore import QObject, QRunnable, Signal

from piqopiqo.cache_paths import get_flickr_cache_dir, get_flickr_token_file_path

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
