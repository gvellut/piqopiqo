"""Tests for the workspace watcher controller."""

from __future__ import annotations

from pathlib import Path
import time
import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.folder_watcher import WorkspaceWatcherController


class _SignalStub:
    def __init__(self) -> None:
        self._callbacks: list[object] = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def disconnect(self, callback) -> None:
        self._callbacks.remove(callback)


class _FakeFolderWatcher:
    started_roots: list[str] = []
    stop_calls = 0

    def __init__(self, root_folder: str, parent=None) -> None:  # noqa: ARG002
        self.root_folder = root_folder
        self.changes_detected = _SignalStub()

    def start(self) -> None:
        self.__class__.started_roots.append(self.root_folder)

    def stop(self, timeout_s: float = 1.0) -> None:  # noqa: ARG002
        self.__class__.stop_calls += 1


def _touch_image(path: Path, data: bytes = b"image") -> str:
    path.write_bytes(data)
    return str(path)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-folder-watcher-{uuid.uuid4().hex}")
    return app


@pytest.fixture
def fake_folder_watcher(monkeypatch):
    _FakeFolderWatcher.started_roots = []
    _FakeFolderWatcher.stop_calls = 0
    monkeypatch.setattr(
        "piqopiqo.folder_watcher.FolderWatcher",
        _FakeFolderWatcher,
    )
    return _FakeFolderWatcher


def test_suspend_stops_live_watcher_and_resume_refreshes_diff(
    qapp, fake_folder_watcher, tmp_path
):  # noqa: ARG001
    callback_changes: list[list[tuple[str, str]]] = []

    existing = _touch_image(tmp_path / "A001.JPG", b"one")
    modified = _touch_image(tmp_path / "A002.JPG", b"two")

    controller = WorkspaceWatcherController(callback_changes.append)
    controller.set_workspace(str(tmp_path), [existing, modified])
    controller.start()

    assert fake_folder_watcher.started_roots == [str(tmp_path)]

    controller.suspend()

    assert fake_folder_watcher.stop_calls == 1

    Path(existing).unlink()
    time.sleep(0.01)
    Path(modified).write_bytes(b"two-updated")
    added = _touch_image(tmp_path / "A003.JPG", b"three")

    controller.resume_and_refresh()

    assert callback_changes == [
        [
            ("deleted", existing),
            ("added", added),
            ("modified", modified),
        ]
    ]
    assert fake_folder_watcher.started_roots == [str(tmp_path), str(tmp_path)]


def test_suppressed_live_changes_do_not_dispatch_and_keep_snapshot_in_sync(
    qapp, fake_folder_watcher, tmp_path
):  # noqa: ARG001
    callback_changes: list[list[tuple[str, str]]] = []
    existing = _touch_image(tmp_path / "A001.JPG")
    suppressed = str(tmp_path / "A002.JPG")

    controller = WorkspaceWatcherController(callback_changes.append)
    controller.set_workspace(str(tmp_path), [existing])
    controller.start()

    controller.suppress_paths([suppressed], duration_s=5.0)
    _touch_image(Path(suppressed))
    controller._on_watcher_changes([("added", suppressed)])

    assert callback_changes == []

    controller.suspend()
    controller.resume_and_refresh()

    assert callback_changes == []


def test_directory_move_outside_root_dispatches_deleted_images(
    qapp, fake_folder_watcher, tmp_path
):  # noqa: ARG001
    callback_changes: list[list[tuple[str, ...]]] = []
    subfolder = tmp_path / "sub"
    subfolder.mkdir()
    existing = _touch_image(subfolder / "A001.JPG")

    controller = WorkspaceWatcherController(callback_changes.append)
    controller.set_workspace(str(tmp_path), [existing])
    controller.start()

    outside = tmp_path.parent / f"moved-{uuid.uuid4().hex}"
    subfolder.rename(outside)

    controller._on_watcher_changes([("deleted", str(subfolder))])

    assert callback_changes == [[("deleted", existing)]]


def test_directory_rename_inside_root_dispatches_moved_images(
    qapp, fake_folder_watcher, tmp_path
):  # noqa: ARG001
    callback_changes: list[list[tuple[str, ...]]] = []
    subfolder = tmp_path / "sub"
    subfolder.mkdir()
    existing = _touch_image(subfolder / "A001.JPG")

    controller = WorkspaceWatcherController(callback_changes.append)
    controller.set_workspace(str(tmp_path), [existing])
    controller.start()

    renamed = tmp_path / "renamed"
    subfolder.rename(renamed)
    new_path = str(renamed / "A001.JPG")

    controller._on_watcher_changes([
        ("deleted", str(subfolder)),
        ("added", str(renamed)),
    ])

    assert callback_changes == [[("moved", existing, new_path)]]


def test_image_rename_inside_root_dispatches_moved_pair(
    qapp, fake_folder_watcher, tmp_path
):  # noqa: ARG001
    callback_changes: list[list[tuple[str, ...]]] = []
    existing = _touch_image(tmp_path / "A001.JPG")

    controller = WorkspaceWatcherController(callback_changes.append)
    controller.set_workspace(str(tmp_path), [existing])
    controller.start()

    renamed = tmp_path / "A002.JPG"
    Path(existing).rename(renamed)

    controller._on_watcher_changes([
        ("deleted", existing),
        ("added", str(renamed)),
    ])

    assert callback_changes == [[("moved", existing, str(renamed))]]


def test_suppressed_snapshot_move_is_not_dispatched_and_snapshot_stays_in_sync(
    qapp, fake_folder_watcher, tmp_path
):  # noqa: ARG001
    callback_changes: list[list[tuple[str, ...]]] = []
    existing = _touch_image(tmp_path / "A001.JPG")

    controller = WorkspaceWatcherController(callback_changes.append)
    controller.set_workspace(str(tmp_path), [existing])
    controller.start()

    renamed = tmp_path / "A002.JPG"
    controller.suppress_paths([existing], duration_s=5.0)
    Path(existing).rename(renamed)

    controller._on_watcher_changes([
        ("deleted", existing),
        ("added", str(renamed)),
    ])

    assert callback_changes == []

    controller.suspend()
    controller.resume_and_refresh()

    assert callback_changes == []
