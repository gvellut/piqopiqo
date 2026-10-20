"""Explicit ownership of application-created modal dialogs."""

from collections.abc import Iterator
from contextlib import contextmanager

from PySide6.QtWidgets import QDialog


@contextmanager
def managed_modal_dialog[Dialog: QDialog](dialog: Dialog) -> Iterator[Dialog]:
    """Keep results readable until the owner schedules main-thread deletion."""
    try:
        yield dialog
    finally:
        dialog.deleteLater()
