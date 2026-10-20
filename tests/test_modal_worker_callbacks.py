"""Workers may finish after their modal dialog has been dismissed."""

from datetime import datetime
from types import SimpleNamespace

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget
import pytest
from shiboken6 import isValid

from piqopiqo.dialogs.modal import managed_modal_dialog
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.qt_workers import PythonOwnedRunnable
from piqopiqo.ssf.settings_state import init_qsettings_store
from piqopiqo.tools import copy_sd
from piqopiqo.tools.flickr_tools import auth_flow
from piqopiqo.tools.flickr_tools.upload import dialogs as flickr_dialogs
from piqopiqo.tools.gpx2exif import (
    actions as gpx_actions,
    dialogs as gpx_dialogs,
    workers as gpx_workers,
)
from piqopiqo.tools.gpx2exif.service import ApplyGpxResult
from piqopiqo.tools.tool_flow import (
    ToolFlowDialog,
    ToolScreen,
    ToolTaskHandle,
    ToolWorkflow,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    init_qsettings_store(dyn=True)
    return app


def flush_deletions():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class _Signals(QObject):
    finished = Signal()


class _QueuedWorker(PythonOwnedRunnable):
    def __init__(self):
        super().__init__()
        self.signals = _Signals()
        self.cancelled = False

    def request_cancel(self):
        self.cancelled = True

    def run(self):
        self.signals.finished.emit()


@pytest.mark.parametrize("accepted", [False, True])
def test_task_ignores_signal_queued_before_dialog_closes(qapp, accepted):
    received = []
    workflow = ToolWorkflow(
        initial_screen="main",
        screens={"main": ToolScreen(id="main")},
        transitions={("main", "finished"): lambda *_: received.append(True)},
    )
    dialog = ToolFlowDialog(workflow)
    worker = _QueuedWorker()
    pool = QThreadPool()
    task = ToolTaskHandle.from_qrunnable(
        worker=worker,
        pool=pool,
        signal_map={worker.signals.finished: "finished"},
    )
    with managed_modal_dialog(dialog):
        dialog.start_task("queued", task)
        queued_slot = task._connections[0][1]
        assert pool.waitForDone(5000)
        dialog.accept() if accepted else dialog.reject()
    flush_deletions()
    assert not isValid(dialog)
    qapp.processEvents()
    queued_slot()
    assert received == []
    assert worker.cancelled is (not accepted)


@pytest.mark.parametrize("operation", ["apply", "clear"])
@pytest.mark.parametrize("shutting_down", [False, True])
def test_gpx_completion_after_progress_deletion(
    qapp,
    monkeypatch,
    tmp_path,
    operation,
    shutting_down,
):
    folder = str(tmp_path)
    path = str(tmp_path / "photo.jpg")
    track = tmp_path / "track.gpx"
    track.write_text("<gpx/>")
    metadata = {DBFields.TIME_TAKEN: datetime(2026, 1, 1), DBFields.LATITUDE: 1.0}
    item = SimpleNamespace(path=path, source_folder=folder, db_metadata={})
    window = QWidget()
    window.root_folder = folder
    window.photo_model = SimpleNamespace(source_folders=[folder], all_photos=[item])
    window._shutdown_started = False
    window._active_apply_gpx_worker = None
    window.db_manager = SimpleNamespace(
        get_db_for_image=lambda _: SimpleNamespace(get_metadata=lambda _: metadata),
    )
    synced = []
    window.sync_model_after_metadata_update = lambda *a, **k: synced.append((a, k))
    applied = []
    monkeypatch.setattr(
        gpx_actions, "apply_gpx_result_to_model", lambda *a, **k: applied.append((a, k))
    )
    monkeypatch.setattr(
        gpx_actions, "_get_first_folder_gpx_path", lambda *_: str(track)
    )
    monkeypatch.setattr(
        gpx_actions, "_resolve_apply_gpx_initial_time_shifts", lambda *_: ({}, set())
    )
    monkeypatch.setattr(gpx_actions, "_persist_apply_gpx_time_shifts", lambda *_: True)
    monkeypatch.setattr(gpx_actions, "_set_gpx_path_for_folders", lambda *_: True)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes
    )
    launched = []
    monkeypatch.setattr(
        gpx_actions,
        "QThreadPool",
        SimpleNamespace(
            globalInstance=lambda: SimpleNamespace(start=launched.append),
        ),
    )
    progress_dialogs = []

    def accept_input(dialog):
        dialog.mode_combo.setCurrentIndex(1)
        QTimer.singleShot(0, dialog.accept)
        return QDialog.exec(dialog)

    def dismiss_progress(dialog):
        progress_dialogs.append(dialog)
        QTimer.singleShot(0, dialog.reject)
        return QDialog.exec(dialog)

    monkeypatch.setattr(gpx_dialogs.ApplyGpxDialog, "exec", accept_input)
    progress_type = (
        gpx_dialogs.ApplyGpxProgressDialog
        if operation == "apply"
        else gpx_dialogs.ClearGpsProgressDialog
    )
    monkeypatch.setattr(progress_type, "exec", dismiss_progress)
    launch = (
        gpx_actions.launch_apply_gpx
        if operation == "apply"
        else gpx_actions.launch_clear_gps
    )
    launch(window)
    worker = launched[0]
    assert worker._cancel_requested.is_set()
    if operation == "apply":
        assert window._active_apply_gpx_worker is worker
    flush_deletions()
    assert not isValid(progress_dialogs[0])
    worker.signals.progress.emit(1, 1)
    window._shutdown_started = shutting_down
    if operation == "apply":
        worker.signals.folder_changed.emit("folder")
        worker.signals.finished.emit(ApplyGpxResult(updated_paths=[path]))
        assert window._active_apply_gpx_worker is None
        assert bool(applied) is (not shutting_down)
    else:
        worker.signals.finished.emit(gpx_workers.ClearGpsResult([path], 1, 1))
        assert bool(synced) is (not shutting_down)
        if not shutting_down:
            assert item.db_metadata == metadata
    window.deleteLater()
    flush_deletions()


@pytest.mark.parametrize("accepted", [False, True])
def test_flickr_preflight_detaches_unfinished_checks(qapp, monkeypatch, accepted):
    launched = []
    monkeypatch.setattr(
        flickr_dialogs,
        "QThreadPool",
        SimpleNamespace(
            globalInstance=lambda: SimpleNamespace(start=launched.append),
        ),
    )
    dialog = flickr_dialogs.FlickrPreflightDialog(
        visible_upload_items=[{"file_path": "/tmp/photo.jpg"}],
        token_exists=True,
        require_metadata=True,
        db_manager=object(),
    )
    with managed_modal_dialog(dialog):
        dialog.accept() if accepted else dialog.reject()
        assert dialog._closed
        assert dialog._validation_connections == []
    flush_deletions()
    assert not isValid(dialog)
    worker = launched[0]
    assert worker._cancel_requested.is_set()
    worker.signals.finished.emit(["/tmp/photo.jpg"])
    worker.signals.error.emit("late error")
    worker.signals.cancelled.emit()
    # Also cover a callback queued before the disconnection.
    dialog._on_metadata_validation_finished(False, [])
    dialog._on_metadata_validation_error(False, "queued error")


def test_flickr_auth_escape_cancels_before_dialog_deletion(qapp, monkeypatch):
    launched = []
    monkeypatch.setattr(
        auth_flow,
        "QThreadPool",
        SimpleNamespace(
            globalInstance=lambda: SimpleNamespace(start=launched.append),
        ),
    )
    from piqopiqo.tools.flickr_tools.upload.workers import FlickrTokenValidationWorker

    worker = FlickrTokenValidationWorker(
        api_key="test", api_secret="test", quick_timeout_s=5
    )
    dialog = auth_flow._FlickrAuthProgressDialog(title="Test", status="Test")
    with managed_modal_dialog(dialog):
        dialog.start_worker(worker)
        QTimer.singleShot(0, dialog.reject)
        assert dialog.exec() == QDialog.DialogCode.Rejected
    assert worker._cancel_requested.is_set()
    flush_deletions()
    worker.signals.finished.emit(True)
    worker.signals.error.emit("late error")
    assert not isValid(dialog)


def test_sd_date_scan_result_after_cancellation(qapp, monkeypatch):
    launched = []
    dialogs = []
    monkeypatch.setattr(
        copy_sd,
        "QThreadPool",
        SimpleNamespace(
            globalInstance=lambda: SimpleNamespace(start=launched.append),
        ),
    )

    class WaitDialog(QDialog):
        def exec(self):
            dialogs.append(self)
            QTimer.singleShot(0, self.reject)
            return super().exec()

    monkeypatch.setattr(copy_sd, "QDialog", WaitDialog)
    assert (
        copy_sd._resolve_dates_with_progress(
            None,
            "since:last",
            copy_sd.PhotoVolume("CARD", "/tmp/card"),
        )
        is None
    )
    flush_deletions()
    assert not isValid(dialogs[0])
    launched[0].signals.finished.emit([])
    launched[0].signals.error.emit("late error")


def test_sd_eject_finishes_after_dialog_deletion(qapp, monkeypatch):
    launched = []
    monkeypatch.setattr(
        copy_sd,
        "QThreadPool",
        SimpleNamespace(
            globalInstance=lambda: SimpleNamespace(start=launched.append),
        ),
    )
    # ToolTaskHandle owns the pool lookup for this worker.
    monkeypatch.setattr(
        "piqopiqo.tools.tool_flow.QThreadPool",
        SimpleNamespace(
            globalInstance=lambda: SimpleNamespace(start=launched.append),
        ),
    )
    calls = []
    monkeypatch.setattr(copy_sd, "eject_volume", lambda *a, **k: calls.append((a, k)))
    dialog = copy_sd.CopySdProgressDialog(
        copy_sd.PhotoVolume("CARD", "/tmp/card"),
        [],
        [],
        should_eject=True,
    )
    with managed_modal_dialog(dialog):
        dialog._finished = True
        dialog._start_eject()
        dialog.reject()
    flush_deletions()
    assert not isValid(dialog)
    launched[0].run()
    assert len(calls) == 1
