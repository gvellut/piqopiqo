"""Regression coverage for Qt dialog destruction during worker garbage collection."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("outcome", ["accepted", "rejected", "exception"])
def test_gpx_dialog_is_destroyed_on_main_thread_after_worker_gc(outcome):
    code = """
import gc
import sys
import threading
import weakref

from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from shiboken6 import isValid

from piqopiqo.dialogs.modal import managed_modal_dialog
from piqopiqo.qt_workers import PythonOwnedRunnable
from piqopiqo.ssf.settings_state import init_qsettings_store
from piqopiqo.tools.gpx2exif.dialogs import ApplyGpxDialog

app = QApplication([])
init_qsettings_store(dyn=True)
parent = QWidget()
main_thread = threading.get_ident()
destroyed_threads = []
gc.disable()

def record_destroyed():
    destroyed_threads.append(threading.get_ident())

def close_dialog():
    dialog = ApplyGpxDialog(
        root_folder='/tmp/photos', source_folders=['/tmp/photos'],
        initial_time_shifts={}, previous_time_shift_folders=set(),
        initial_gpx_path='', kml_folder='', parent=parent,
    )
    dialog.destroyed.connect(record_destroyed, Qt.ConnectionType.DirectConnection)
    ref = weakref.ref(dialog)
    try:
        with managed_modal_dialog(dialog):
            close = dialog.reject if sys.argv[1] == 'rejected' else dialog.accept
            QTimer.singleShot(0, close)
            result = dialog.exec()
            assert isValid(dialog)
            assert dialog.get_values()[0] == ''
            assert result == (
                QDialog.DialogCode.Rejected if sys.argv[1] == 'rejected'
                else QDialog.DialogCode.Accepted
            )
            if sys.argv[1] == 'exception':
                raise ValueError('result consumption failed')
    except ValueError:
        assert sys.argv[1] == 'exception'
    return ref

ref = close_dialog()

class Collector(PythonOwnedRunnable):
    def run(self):
        gc.collect()

pool = QThreadPool()
collector = Collector()
pool.start(collector)
assert pool.waitForDone(5000)
assert destroyed_threads == [], destroyed_threads
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
assert destroyed_threads == [main_thread], destroyed_threads
gc.collect()
assert ref() is None
parent.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
gc.enable()
"""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, outcome],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_storage_retry_reuses_dialog_until_loop_finishes(monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtWidgets import QApplication, QDialog
    from shiboken6 import isValid

    import piqopiqo.dialogs.storage_full_dialog as storage_dialogs
    from piqopiqo.storage import StorageWriteFault

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    dialogs = []
    executions = []

    class RetryDialog(storage_dialogs.StorageFullDialog):
        def exec(self):
            dialogs.append(self)
            executions.append(len(executions))
            assert isValid(self)
            QTimer.singleShot(0, self.accept)
            return super().exec()

    monkeypatch.setattr(storage_dialogs, "StorageFullDialog", RetryDialog)
    fault = StorageWriteFault(
        target_path="/tmp/cache", operation="test", error_message="Full"
    )
    retries = iter([fault, None])

    def retry():
        # A nested event loop here must not delete the reusable dialog.
        nested = QDialog()
        QTimer.singleShot(0, nested.accept)
        nested.exec()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert isValid(dialogs[0])
        return next(retries)

    assert storage_dialogs.wait_for_storage_retry(
        parent=None,
        fault=fault,
        retry=retry,
        title="Full",
        headline="Full",
        retry_description="Retry",
    )
    assert len(executions) == 2
    assert dialogs[0] is dialogs[1]
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(dialogs[0])
    assert app is not None
