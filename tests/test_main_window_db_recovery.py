"""Tests for main-window metadata DB recovery coordination."""

from __future__ import annotations

from types import SimpleNamespace

from piqopiqo.main_window import MainWindow
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDBFault
from piqopiqo.storage import StorageWriteFault


class _FakeTimer:
    def __init__(self) -> None:
        self.active = False
        self.start_calls: list[int] = []
        self.stop_calls = 0

    def isActive(self) -> bool:
        return self.active

    def start(self, interval_ms: int) -> None:
        self.active = True
        self.start_calls.append(int(interval_ms))

    def stop(self) -> None:
        self.active = False
        self.stop_calls += 1


class _FakeStatusBar:
    def __init__(self) -> None:
        self.messages: list[tuple[str, int]] = []
        self.cleared = 0
        self.reset_calls = 0
        self.has_errors_calls: list[bool] = []

    def showMessage(self, text: str, timeout_ms: int) -> None:
        self.messages.append((text, timeout_ms))

    def clearMessage(self) -> None:
        self.cleared += 1

    def reset(self) -> None:
        self.reset_calls += 1

    def set_has_errors(self, has_errors: bool) -> None:
        self.has_errors_calls.append(bool(has_errors))


class _FakeScrollBar:
    def value(self) -> int:
        return 0


class _FakeGrid:
    def __init__(self) -> None:
        self.scrollbar = _FakeScrollBar()
        self.scroll_calls: list[int] = []

    def on_scroll(self, value: int) -> None:
        self.scroll_calls.append(int(value))


class _FakeMediaManager:
    def __init__(self) -> None:
        self.pause_calls = 0
        self.resume_calls = 0
        self.clear_storage_full_calls = 0
        self.reset_calls: list[tuple[list[str], list[str]]] = []

    def pause_processing(self) -> None:
        self.pause_calls += 1

    def resume_processing(self) -> None:
        self.resume_calls += 1

    def reset_for_folder(self, file_paths: list[str], source_folders: list[str]):
        self.reset_calls.append((list(file_paths), list(source_folders)))
        return SimpleNamespace(
            cached_editable_metadata={},
            missing_editable_paths=set(),
        )

    def has_errors(self) -> bool:
        return False

    def clear_storage_full_fault(self) -> None:
        self.clear_storage_full_calls += 1


class _FakeReplayDB:
    def __init__(self) -> None:
        self.save_calls: list[tuple[str, dict]] = []

    def save_metadata(self, file_path: str, data: dict) -> None:
        self.save_calls.append((file_path, dict(data)))


class _FakeDBManager:
    def __init__(
        self,
        *,
        probe_results: list[tuple[bool, MetadataDBFault | None]],
        replay_db: _FakeReplayDB | None = None,
    ) -> None:
        self._probe_results = list(probe_results)
        self._replay_db = replay_db or _FakeReplayDB()
        self.probe_calls: list[tuple[str, bool, bool]] = []
        self.close_all_calls = 0

    def probe_folder_health(
        self,
        folder_path: str,
        *,
        allow_create: bool = False,
        require_write: bool = False,
    ) -> tuple[bool, MetadataDBFault | None]:
        self.probe_calls.append((folder_path, bool(allow_create), bool(require_write)))
        if self._probe_results:
            return self._probe_results.pop(0)
        return True, None

    def get_db_for_image(self, _file_path: str) -> _FakeReplayDB:
        return self._replay_db

    def close_all(self) -> None:
        self.close_all_calls += 1


class _FakeApp:
    def __init__(self) -> None:
        self.quit_calls = 0

    def quit(self) -> None:
        self.quit_calls += 1


class _FakeRecoveryWindow:
    _metadata_recovery_refresh_fields = staticmethod(
        MainWindow._metadata_recovery_refresh_fields
    )
    _queue_replayable_metadata_save = MainWindow._queue_replayable_metadata_save
    _record_db_redo_warning = MainWindow._record_db_redo_warning
    _on_metadata_save_worker_failure = MainWindow._on_metadata_save_worker_failure
    _on_db_fault_reported = MainWindow._on_db_fault_reported
    _on_storage_full_reported = MainWindow._on_storage_full_reported
    _retry_after_storage_full = MainWindow._retry_after_storage_full
    _schedule_db_recovery_probe = MainWindow._schedule_db_recovery_probe
    _replay_pending_metadata_saves = MainWindow._replay_pending_metadata_saves
    _refresh_workspace_after_db_recovery = (
        MainWindow._refresh_workspace_after_db_recovery
    )
    _show_pending_db_redo_warning = MainWindow._show_pending_db_redo_warning
    _finish_db_recovery = MainWindow._finish_db_recovery
    _probe_db_recovery = MainWindow._probe_db_recovery
    _handle_interrupted_db_action = MainWindow._handle_interrupted_db_action
    _relaunch_after_db_recovery_failure = MainWindow._relaunch_after_db_recovery_failure

    def __init__(self, db_manager: _FakeDBManager) -> None:
        self._shutdown_started = False
        self._db_recovery_active = False
        self._db_recovery_affected_folders: set[str] = set()
        self._db_recovery_pending_metadata_saves = {}
        self._db_recovery_pending_redo_messages: list[str] = []
        self._db_recovery_probe_timer = _FakeTimer()
        self._storage_full_active = False
        self._storage_full_dialog_scheduled = False
        self._storage_full_fault: StorageWriteFault | None = None
        self._launch_command = ["/usr/bin/python3", "-m", "piqopiqo"]
        self.db_manager = db_manager
        self.media_manager = _FakeMediaManager()
        self.status_bar = _FakeStatusBar()
        self.grid = _FakeGrid()
        self.photo_model = SimpleNamespace(
            all_photos=[SimpleNamespace(path="/photos/folder_a/image.jpg")],
            source_folders=["/photos/folder_a"],
        )
        self._items_by_path = {}
        self._last_visible_paths: list[str] = []
        self.sync_calls: list[tuple[set[str], str]] = []
        self.invalidate_calls = 0
        self.cached_apply_calls: list[dict[str, object]] = []
        self.persist_calls = 0
        self.shutdown_calls = 0

    def _invalidate_workspace_items_for_reload(self) -> None:
        self.invalidate_calls += 1

    def _apply_cached_editable_metadata_for_items(self, items_by_path, priming) -> None:
        self.cached_apply_calls.append({
            "items": dict(items_by_path),
            "priming": priming,
        })

    def sync_model_after_metadata_update(self, fields: set[str], source: str) -> None:
        self.sync_calls.append((set(fields), source))

    def _persist_window_state(self) -> None:
        self.persist_calls += 1

    def shutdown_for_quit(self) -> None:
        self.shutdown_calls += 1

    def _show_storage_full_recovery_dialog(self) -> None:
        return None


def _fault(*, classification: str, path_available: bool) -> MetadataDBFault:
    return MetadataDBFault(
        folder_path="/photos/folder_a",
        db_path="/cache/folder_a/db/metadata.db",
        operation="save_metadata",
        error_message="db unavailable",
        during_write=True,
        classification=classification,
        path_available=path_available,
    )


def test_transient_db_recovery_replays_pending_metadata_save(monkeypatch) -> None:
    warning_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "piqopiqo.main_window.QMessageBox.warning",
        lambda _parent, title, text: warning_calls.append((title, text)),
    )

    replay_db = _FakeReplayDB()
    window = _FakeRecoveryWindow(
        _FakeDBManager(
            probe_results=[(True, None)],
            replay_db=replay_db,
        )
    )
    fault = _fault(classification="transient_unavailable", path_available=False)

    window._on_db_fault_reported(fault)
    window._on_metadata_save_worker_failure({
        "file_path": "/photos/folder_a/image.jpg",
        "data": {DBFields.TITLE: "Recovered title"},
        "changed_fields": {DBFields.TITLE},
        "fault": fault,
        "safe_to_replay": True,
        "source": "edit_panel",
    })

    window._probe_db_recovery()

    assert replay_db.save_calls == [
        (
            "/photos/folder_a/image.jpg",
            {DBFields.TITLE: "Recovered title"},
        )
    ]
    assert window.media_manager.pause_calls == 2
    assert window.media_manager.resume_calls == 1
    assert window.status_bar.messages == [("Reconnecting metadata cache...", 0)]
    assert window.status_bar.cleared == 1
    assert window.status_bar.reset_calls == 1
    assert window.invalidate_calls == 1
    assert window.sync_calls == [({DBFields.TITLE}, "db_recovery")]
    assert window._db_recovery_pending_metadata_saves == {}
    assert warning_calls == []


def test_interrupted_db_action_warns_user_after_recovery(monkeypatch) -> None:
    warning_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "piqopiqo.main_window.QMessageBox.warning",
        lambda _parent, title, text: warning_calls.append((title, text)),
    )

    window = _FakeRecoveryWindow(_FakeDBManager(probe_results=[]))
    window._db_recovery_active = True

    window._handle_interrupted_db_action(action_name="Apply GPX")
    window._finish_db_recovery()

    assert warning_calls == [
        (
            "Metadata Cache Recovery",
            "Apply GPX was interrupted while the metadata cache was unavailable. "
            "Please reconnect the cache disk and redo that action after recovery.",
        )
    ]


def test_storage_full_db_fault_pauses_once_without_reconnect_probe(monkeypatch):
    callbacks: list[object] = []
    monkeypatch.setattr(
        "piqopiqo.main_window.QTimer.singleShot",
        lambda _delay_ms, callback: callbacks.append(callback),
    )
    window = _FakeRecoveryWindow(_FakeDBManager(probe_results=[]))
    fault = _fault(classification="storage_full", path_available=True)

    window._on_db_fault_reported(fault)
    window._on_db_fault_reported(fault)

    assert window.media_manager.pause_calls == 1
    assert window._db_recovery_probe_timer.start_calls == []
    assert len(callbacks) == 1
    assert window._storage_full_active is True
    assert window._storage_full_fault == StorageWriteFault(
        target_path=fault.db_path,
        operation=fault.operation,
        error_message=fault.error_message,
    )
    assert window.status_bar.messages[-1] == (
        "Cache storage is full. Free space, then choose Retry.",
        0,
    )


def test_storage_full_metadata_save_is_queued_for_manual_retry():
    window = _FakeRecoveryWindow(_FakeDBManager(probe_results=[]))
    fault = _fault(classification="storage_full", path_available=True)

    window._on_metadata_save_worker_failure({
        "file_path": "/photos/folder_a/image.jpg",
        "data": {DBFields.TITLE: "Keep me"},
        "changed_fields": {DBFields.TITLE},
        "fault": fault,
        "safe_to_replay": True,
        "source": "edit_panel",
    })

    pending = window._db_recovery_pending_metadata_saves["/photos/folder_a/image.jpg"]
    assert pending.data == {DBFields.TITLE: "Keep me"}


def test_storage_full_retry_replays_save_and_refreshes_workspace(monkeypatch):
    monkeypatch.setattr(
        "piqopiqo.main_window.QMessageBox.warning",
        lambda *_args, **_kwargs: None,
    )
    replay_db = _FakeReplayDB()
    window = _FakeRecoveryWindow(_FakeDBManager(probe_results=[], replay_db=replay_db))
    storage_fault = StorageWriteFault(
        target_path="/cache",
        operation="save_metadata",
        error_message="No space left on device",
    )
    window._storage_full_fault = storage_fault
    window._db_recovery_affected_folders.add("/photos/folder_a")
    window._probe_cache_storage_full = lambda: None
    window._queue_replayable_metadata_save(
        file_path="/photos/folder_a/image.jpg",
        data={DBFields.TITLE: "Recovered"},
        changed_fields={DBFields.TITLE},
        source="edit_panel",
    )

    retry_fault = window._retry_after_storage_full()

    assert retry_fault is None
    assert replay_db.save_calls == [
        (
            "/photos/folder_a/image.jpg",
            {DBFields.TITLE: "Recovered"},
        )
    ]
    assert window.media_manager.reset_calls == [
        (
            ["/photos/folder_a/image.jpg"],
            ["/photos/folder_a"],
        )
    ]
    assert window.media_manager.clear_storage_full_calls == 1
    assert window.sync_calls == [({DBFields.TITLE}, "db_recovery")]
    assert window.db_manager.probe_calls == [("/photos/folder_a", True, True)]


def test_storage_full_retry_stays_blocked_when_probe_still_fails():
    window = _FakeRecoveryWindow(_FakeDBManager(probe_results=[]))
    fault = StorageWriteFault(
        target_path="/cache",
        operation="probe_cache_storage",
        error_message="No space left on device",
    )
    window._probe_cache_storage_full = lambda: fault

    retry_fault = window._retry_after_storage_full()

    assert retry_fault == fault
    assert window.db_manager.close_all_calls == 0
    assert window.media_manager.reset_calls == []


def test_unreadable_db_recovery_rebuilds_cache_and_warns(monkeypatch) -> None:
    warning_calls: list[tuple[str, str]] = []
    cleared_folders: list[list[str]] = []
    monkeypatch.setattr(
        "piqopiqo.main_window.QMessageBox.warning",
        lambda _parent, title, text: warning_calls.append((title, text)),
    )
    monkeypatch.setattr(
        "piqopiqo.main_window.clear_metadata_cache_for_folders",
        lambda folders: cleared_folders.append(list(folders)),
    )

    fault = _fault(classification="unreadable_after_reconnect", path_available=True)
    window = _FakeRecoveryWindow(
        _FakeDBManager(
            probe_results=[(False, fault)],
        )
    )
    window._on_db_fault_reported(fault)
    window._queue_replayable_metadata_save(
        file_path="/photos/folder_a/image.jpg",
        data={DBFields.TITLE: "Lost"},
        changed_fields={DBFields.TITLE},
        source="edit_panel",
    )

    window._probe_db_recovery()

    assert cleared_folders == [["/photos/folder_a"]]
    assert window._db_recovery_pending_metadata_saves == {}
    assert window.status_bar.cleared == 1
    assert window.sync_calls == [
        (MainWindow._metadata_recovery_refresh_fields(), "db_recovery")
    ]
    assert len(warning_calls) == 1
    assert "had to be rebuilt" in warning_calls[0][1]


def test_failed_db_recovery_relaunches_application(monkeypatch) -> None:
    critical_calls: list[tuple[str, str]] = []
    popen_calls: list[list[str]] = []
    sync_calls: list[str] = []
    fake_app = _FakeApp()
    monkeypatch.setattr(
        "piqopiqo.main_window.QMessageBox.critical",
        lambda _parent, title, text: critical_calls.append((title, text)),
    )
    monkeypatch.setattr(
        "piqopiqo.main_window.subprocess.Popen",
        lambda args, close_fds=True: popen_calls.append(list(args)),
    )
    monkeypatch.setattr(
        "piqopiqo.main_window.sync_qsettings_store",
        lambda: sync_calls.append("sync"),
    )
    monkeypatch.setattr(
        "piqopiqo.main_window.QApplication.instance",
        lambda: fake_app,
    )

    window = _FakeRecoveryWindow(_FakeDBManager(probe_results=[]))

    window._relaunch_after_db_recovery_failure("fatal recovery failure")

    assert critical_calls == [
        ("Metadata Cache Recovery", "fatal recovery failure"),
    ]
    assert window.persist_calls == 1
    assert window.shutdown_calls == 1
    assert sync_calls == ["sync"]
    assert popen_calls == [["/usr/bin/python3", "-m", "piqopiqo"]]
    assert fake_app.quit_calls == 1
