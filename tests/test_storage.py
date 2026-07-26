"""Tests for storage-full detection and recovery UI."""

from __future__ import annotations

import errno
import sqlite3
import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.dialogs.storage_full_dialog import StorageFullDialog
import piqopiqo.storage as storage
from piqopiqo.storage import (
    StorageFullError,
    StorageWriteFault,
    probe_storage_write,
    storage_full_fault_from_error,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-storage-{uuid.uuid4().hex}")
    return app


@pytest.mark.parametrize(
    "error",
    [
        OSError(errno.ENOSPC, "No space left on device"),
        OSError(getattr(errno, "EDQUOT", errno.ENOSPC), "Disk quota exceeded"),
        sqlite3.OperationalError("database or disk is full"),
    ],
)
def test_storage_full_classifier_recognizes_direct_errors(error, tmp_path):
    fault = storage_full_fault_from_error(
        error,
        target_path=tmp_path,
        operation="write_test",
    )

    assert fault is not None
    assert fault.target_path == str(tmp_path)
    assert fault.operation == "write_test"


def test_ambiguous_sqlite_open_error_requires_failed_full_probe(monkeypatch, tmp_path):
    probe_fault = StorageWriteFault(
        target_path=str(tmp_path),
        operation="probe",
        error_message="No space left on device",
    )
    monkeypatch.setattr(
        storage,
        "probe_storage_write",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(StorageFullError(probe_fault)),
    )

    fault = storage_full_fault_from_error(
        sqlite3.OperationalError("unable to open database file"),
        target_path=tmp_path,
        operation="save_metadata",
        confirm_ambiguous_sqlite=True,
    )

    assert fault is not None
    assert fault.operation == "save_metadata"


def test_ambiguous_sqlite_open_error_stays_non_full_when_probe_is_writable(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        storage,
        "probe_storage_write",
        lambda *_args, **_kwargs: None,
    )

    fault = storage_full_fault_from_error(
        sqlite3.OperationalError("unable to open database file"),
        target_path=tmp_path,
        operation="save_metadata",
        confirm_ambiguous_sqlite=True,
    )

    assert fault is None


def test_ambiguous_sqlite_open_error_stays_non_full_for_disconnected_volume(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        storage,
        "probe_storage_write",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError(errno.ENOENT, "Volume is not mounted")
        ),
    )

    fault = storage_full_fault_from_error(
        sqlite3.OperationalError("unable to open database file"),
        target_path=tmp_path,
        operation="save_metadata",
        confirm_ambiguous_sqlite=True,
    )

    assert fault is None


def test_storage_write_probe_removes_probe_file(tmp_path):
    probe_storage_write(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_storage_full_dialog_places_exit_left_and_retry_right(qapp, tmp_path):
    fault = StorageWriteFault(
        target_path=str(tmp_path),
        operation="write_thumbnail",
        error_message="No space left on device",
    )
    dialog = StorageFullDialog(
        fault,
        title="Cache Storage Full",
        headline="Storage is full.",
        retry_description="Free space and retry.",
    )

    button_row = dialog.layout().itemAt(dialog.layout().count() - 1).layout()
    assert button_row.itemAt(0).widget() is dialog.exit_button
    assert button_row.itemAt(1).spacerItem() is not None
    assert button_row.itemAt(2).widget() is dialog.retry_button
    assert dialog.retry_button.isDefault() is True
