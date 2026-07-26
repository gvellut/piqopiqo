"""Storage write probes and full-volume error classification.

This module intentionally has no Qt imports so background threads and spawned
media workers can use it safely.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
import tempfile
from typing import Any

from attrs import define

_FULL_STORAGE_ERRNOS = {
    errno.ENOSPC,
    getattr(errno, "EDQUOT", errno.ENOSPC),
}
_FULL_STORAGE_ERROR_SNIPPETS = (
    "no space left on device",
    "disk quota exceeded",
    "database or disk is full",
)
_AMBIGUOUS_SQLITE_ERROR_SNIPPETS = ("unable to open database file",)
_PROBE_BYTES = b"\0" * 4096


@define(frozen=True)
class StorageWriteFault:
    """Description of a failed write caused by exhausted storage."""

    target_path: str
    operation: str
    error_message: str


class StorageFullError(OSError):
    """Raised internally when a storage-full fault must cross a call boundary."""

    def __init__(self, fault: StorageWriteFault):
        self.fault = fault
        super().__init__(fault.error_message)


def _iter_exception_chain(error: BaseException):
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _is_direct_storage_full_error(error: BaseException | str) -> bool:
    if isinstance(error, BaseException):
        for current in _iter_exception_chain(error):
            if getattr(current, "errno", None) in _FULL_STORAGE_ERRNOS:
                return True
            message = str(current).lower()
            if any(snippet in message for snippet in _FULL_STORAGE_ERROR_SNIPPETS):
                return True
        return False

    message = str(error).lower()
    return any(snippet in message for snippet in _FULL_STORAGE_ERROR_SNIPPETS)


def _is_ambiguous_sqlite_open_error(error: BaseException | str) -> bool:
    if isinstance(error, BaseException):
        messages = [str(current).lower() for current in _iter_exception_chain(error)]
    else:
        messages = [str(error).lower()]
    return any(
        snippet in message
        for message in messages
        for snippet in _AMBIGUOUS_SQLITE_ERROR_SNIPPETS
    )


def storage_full_fault_from_error(
    error: BaseException | str,
    *,
    target_path: str | os.PathLike[str],
    operation: str,
    confirm_ambiguous_sqlite: bool = False,
) -> StorageWriteFault | None:
    """Return a storage-full fault when ``error`` represents exhausted storage."""
    is_full = _is_direct_storage_full_error(error)
    if (
        not is_full
        and confirm_ambiguous_sqlite
        and _is_ambiguous_sqlite_open_error(error)
    ):
        try:
            probe_storage_write(target_path, operation=f"{operation}_probe")
        except StorageFullError:
            is_full = True
        except OSError:
            # A non-space probe failure does not prove the volume is full.
            pass

    if not is_full:
        return None

    message = str(error).strip()
    if not message:
        message = (
            error.__class__.__name__ if isinstance(error, BaseException) else str(error)
        )
    return StorageWriteFault(
        target_path=str(target_path),
        operation=str(operation),
        error_message=message,
    )


def probe_storage_write(
    directory: str | os.PathLike[str],
    *,
    operation: str = "storage_write_probe",
) -> None:
    """Write, flush, and remove a small file to verify a directory is writable.

    Raises ``StorageFullError`` for exhausted storage and preserves other
    ``OSError`` failures so callers can handle permissions or disconnections
    separately.
    """
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)

    probe_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=".piqopiqo-write-probe-",
            dir=target_dir,
            delete=False,
        ) as probe:
            probe_path = Path(probe.name)
            probe.write(_PROBE_BYTES)
            probe.flush()
            os.fsync(probe.fileno())
    except OSError as exc:
        fault = storage_full_fault_from_error(
            exc,
            target_path=target_dir,
            operation=operation,
        )
        if fault is not None:
            raise StorageFullError(fault) from exc
        raise
    finally:
        if probe_path is not None:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError:
                pass


def storage_fault_from_payload(value: Any) -> StorageWriteFault | None:
    """Normalize a worker payload into ``StorageWriteFault`` when possible."""
    if isinstance(value, StorageWriteFault):
        return value
    if not isinstance(value, dict):
        return None

    target_path = value.get("target_path")
    operation = value.get("operation")
    error_message = value.get("error_message")
    if not all(isinstance(part, str) and part for part in (target_path, operation)):
        return None
    return StorageWriteFault(
        target_path=target_path,
        operation=operation,
        error_message=str(error_message or "Storage is full"),
    )
