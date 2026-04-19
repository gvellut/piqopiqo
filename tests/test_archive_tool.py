"""Tests for the Archive tool workflow."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget
import pytest

from piqopiqo.background.media_man import FolderPrimingResult
from piqopiqo.main_window import MainWindow
from piqopiqo.model import FilterCriteria, ImageItem
from piqopiqo.ssf.settings_state import (
    StateKey,
    UserSettingKey,
    get_state,
    get_state_value,
    init_qsettings_store,
    set_user_setting,
)
from piqopiqo.tools.archive import (
    ArchiveDialog,
    ArchiveMoveResult,
    ArchiveMoveWorker,
    launch_archive,
)


class _SignalStub:
    def connect(self, *_args, **_kwargs) -> None:
        return None


class _MediaManagerStub:
    next_priming_result = FolderPrimingResult({}, set())

    def __init__(self, *_args, **_kwargs):
        self.thumb_ready = _SignalStub()
        self.thumb_progress_updated = _SignalStub()
        self.editable_ready = _SignalStub()
        self.editable_terminal = _SignalStub()
        self.exif_progress_updated = _SignalStub()
        self.panel_fields_ready = _SignalStub()
        self.all_completed = _SignalStub()

    def reset_for_folder(
        self, _file_paths: list[str], _source_folders: list[str]
    ) -> FolderPrimingResult:
        return self.next_priming_result

    def pause_processing(self) -> None:
        return None

    def resume_processing(self) -> None:
        return None

    def update_visible(self, _visible_paths_in_order: list[str]) -> None:
        return None

    def has_errors(self) -> bool:
        return False

    def get_thumb_errors(self) -> dict[str, str]:
        return {}

    def get_exif_errors(self) -> dict[str, str]:
        return {}

    def add_files(self, _file_paths: list[str]) -> None:
        return None

    def remove_files(self, _file_paths: list[str]) -> None:
        return None

    def request_thumbnail(self, _file_path: str) -> None:
        return None

    def regenerate_thumbnails(self, _file_paths: list[str]) -> None:
        return None

    def refresh_files(self, _file_paths: list[str]) -> None:
        return None

    def reload_exif(self, _file_paths: list[str]) -> None:
        return None

    def ensure_panel_fields_loaded_from_db(self, _file_paths: list[str]) -> None:
        return None

    def refresh_exif_field_keys(self, _field_keys: list[str]) -> None:
        return None

    def stop(self, timeout_s: float | None = None) -> None:  # noqa: ARG002
        return None


class _FakeArchiveMediaManager(QObject):
    write_progress = Signal(int, int)
    write_file_completed = Signal(str, bool, str)
    write_all_completed = Signal()

    def __init__(self):
        super().__init__()
        self.write_calls: list[list[tuple[str, dict]]] = []
        self.stop_write_calls = 0

    def write_exif(self, items: list[tuple[str, dict]]) -> None:
        self.write_calls.append(list(items))

    def stop_write(self) -> None:
        self.stop_write_calls += 1


class _WatcherControlSpy:
    def __init__(self) -> None:
        self.suspend_calls = 0
        self.resume_calls = 0

    def suspend(self) -> None:
        self.suspend_calls += 1

    def resume_and_refresh(self) -> None:
        self.resume_calls += 1


class _FakeArchiveDbManager:
    def __init__(self, *, ready: bool = True):
        self.ready = ready
        self.ensure_calls: list[list[ImageItem]] = []

    def ensure_items_metadata_ready(self, items: list[ImageItem]) -> bool:
        self.ensure_calls.append(list(items))
        return self.ready


class _FakeLaunchPhotoModel:
    def __init__(self, all_photos: list[ImageItem], source_folders: list[str]):
        self.all_photos = list(all_photos)
        self.source_folders = list(source_folders)


class _FakeLaunchWindow(QWidget):
    def __init__(
        self,
        *,
        root_folder: str | None,
        all_photos: list[ImageItem] | None = None,
        source_folders: list[str] | None = None,
        watcher_control=None,
    ):
        super().__init__()
        self.root_folder = root_folder
        self.photo_model = _FakeLaunchPhotoModel(all_photos or [], source_folders or [])
        self.open_settings_calls: list[UserSettingKey] = []
        self._workspace_watcher = watcher_control

    @property
    def workspace_watcher_control(self):
        return self._workspace_watcher

    def open_settings_for_key(self, key: UserSettingKey) -> None:
        self.open_settings_calls.append(key)


class _FakeArchiveWindow(QWidget):
    def __init__(self, *, ready: bool = True):
        super().__init__()
        self.media_manager = _FakeArchiveMediaManager()
        self.db_manager = _FakeArchiveDbManager(ready=ready)
        self.prepare_calls = 0
        self.resume_calls = 0
        self.unload_calls: list[bool] = []
        self.folder_dialog_hint_updates: list[str] = []
        self.removed_recent_folders: list[str] = []

    def _prepare_workspace_for_archive_move(self) -> None:
        self.prepare_calls += 1

    def _resume_workspace_after_archive_failure(self) -> None:
        self.resume_calls += 1

    def _unload_workspace(self, *, clear_last_folder: bool = False) -> None:
        self.unload_calls.append(bool(clear_last_folder))

    def _set_folder_dialog_directory_hint_from_folder(
        self,
        folder_path: str | None,
    ) -> None:
        self.folder_dialog_hint_updates.append(str(folder_path or ""))

    def _remove_recent_folder_from_history(self, folder_path: str | None) -> None:
        self.removed_recent_folders.append(str(folder_path or ""))


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-archive-{uuid.uuid4().hex}")
    return app


@pytest.fixture
def settings_store():
    init_qsettings_store(dyn=True)
    return get_state()


@pytest.fixture
def main_window(qapp, settings_store, monkeypatch, tmp_path):  # noqa: ARG001
    _MediaManagerStub.next_priming_result = FolderPrimingResult({}, set())
    monkeypatch.setattr("piqopiqo.main_window.MediaManager", _MediaManagerStub)
    monkeypatch.setattr(
        "piqopiqo.main_window.refresh_main_screen_color_space_cache_macos",
        lambda: None,
    )

    root_folder = tmp_path / "root"
    root_folder.mkdir()
    images = [
        {
            "path": str(root_folder / "a.jpg"),
            "name": "a.jpg",
            "state": 0,
            "created": "2026-01-01 10:00:00",
            "source_folder": str(root_folder),
        }
    ]
    window = MainWindow(images, [str(root_folder)], str(root_folder))
    yield window
    window.close()


def _item(path: str) -> ImageItem:
    return ImageItem(
        path=path,
        name=path.rsplit("/", 1)[-1],
        created="2026-01-01 10:00:00",
        source_folder=path.rsplit("/", 1)[0],
    )


def test_launch_archive_warns_when_no_folder_loaded(qapp, settings_store, monkeypatch):  # noqa: ARG001
    window = _FakeLaunchWindow(root_folder=None)
    info_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "piqopiqo.tools.archive.QMessageBox.information",
        lambda _parent, title, text: info_calls.append((title, text)),
    )

    launch_archive(window)

    assert info_calls == [("Archive", "No folder is currently loaded.")]


def test_launch_archive_redirects_to_settings_for_missing_destination(
    qapp, settings_store, tmp_path, monkeypatch  # noqa: ARG001
):
    root_folder = tmp_path / "20250502_annecy"
    root_folder.mkdir()
    window = _FakeLaunchWindow(root_folder=str(root_folder))
    prompted: list[str] = []
    monkeypatch.setattr(
        "piqopiqo.tools.archive.prompt_open_settings_for_missing_setting",
        lambda _parent, *, title, text, icon=None: prompted.append(
            f"{title}:{text}"
        )
        or True,
    )

    launch_archive(window)

    assert prompted
    assert window.open_settings_calls == [UserSettingKey.ARCHIVE_DESTINATION]


def test_launch_archive_stops_on_same_name_conflict(
    qapp, settings_store, tmp_path, monkeypatch  # noqa: ARG001
):
    root_folder = tmp_path / "20250502_annecy"
    root_folder.mkdir()
    destination = tmp_path / "archive"
    destination.mkdir()
    (destination / root_folder.name).mkdir()
    set_user_setting(UserSettingKey.ARCHIVE_DESTINATION, str(destination))

    window = _FakeLaunchWindow(root_folder=str(root_folder))
    warning_calls: list[tuple[str, str]] = []
    created: list[object] = []
    monkeypatch.setattr(
        "piqopiqo.tools.archive.QMessageBox.warning",
        lambda _parent, title, text: warning_calls.append((title, text)),
    )
    monkeypatch.setattr(
        "piqopiqo.tools.archive.ArchiveDialog",
        lambda *args, **kwargs: created.append((args, kwargs)),
    )

    launch_archive(window)

    assert len(warning_calls) == 1
    assert warning_calls[0][0] == "Archive"
    assert "already contains a folder with the same name" in warning_calls[0][1]
    assert created == []


def test_launch_archive_uses_all_photos_not_visible_photos(
    qapp, settings_store, tmp_path, monkeypatch  # noqa: ARG001
):
    root_folder = tmp_path / "20250502_annecy"
    root_folder.mkdir()
    destination = tmp_path / "archive"
    destination.mkdir()
    set_user_setting(UserSettingKey.ARCHIVE_DESTINATION, str(destination))

    all_photo = _item("/photos/root/all.jpg")
    window = _FakeLaunchWindow(
        root_folder=str(root_folder),
        all_photos=[all_photo],
        source_folders=["/photos/root"],
    )

    captured: dict[str, object] = {}

    class _DialogStub:
        def __init__(self, _window, **kwargs) -> None:
            captured.update(kwargs)

        def exec(self) -> int:
            return 0

    monkeypatch.setattr("piqopiqo.tools.archive.ArchiveDialog", _DialogStub)

    launch_archive(window)

    assert captured["items"] == [all_photo]
    assert captured["source_folders"] == ["/photos/root"]


def test_launch_archive_passes_workspace_watcher_control(
    qapp, settings_store, tmp_path, monkeypatch  # noqa: ARG001
):
    root_folder = tmp_path / "20250502_annecy"
    root_folder.mkdir()
    destination = tmp_path / "archive"
    destination.mkdir()
    set_user_setting(UserSettingKey.ARCHIVE_DESTINATION, str(destination))

    watcher_control = _WatcherControlSpy()
    window = _FakeLaunchWindow(
        root_folder=str(root_folder),
        watcher_control=watcher_control,
    )

    captured: dict[str, object] = {}

    class _DialogStub:
        def __init__(self, _window, **kwargs) -> None:
            captured.update(kwargs)

        def exec(self) -> int:
            return 0

    monkeypatch.setattr("piqopiqo.tools.archive.ArchiveDialog", _DialogStub)

    launch_archive(window)

    assert captured["watcher_control"] is watcher_control


def test_archive_dialog_checkbox_state_round_trip(qapp, settings_store):  # noqa: ARG001
    get_state().set(StateKey.ARCHIVE_SAVE_EXIF, True)
    window = _FakeArchiveWindow()
    dialog = ArchiveDialog(
        window,
        root_folder="/photos/root",
        archive_path="/archive/root",
        items=[],
        source_folders=[],
    )
    dialog.save_exif_checkbox.setChecked(False)
    dialog._start_move_stage = lambda: None

    dialog._start_archive()

    assert get_state_value(StateKey.ARCHIVE_SAVE_EXIF) is False


def test_archive_dialog_initial_focus_is_ok_button(qapp, settings_store):  # noqa: ARG001
    window = _FakeArchiveWindow()
    dialog = ArchiveDialog(
        window,
        root_folder="/photos/root",
        archive_path="/archive/root",
        items=[],
        source_folders=[],
    )

    dialog.show()
    qapp.processEvents()

    assert dialog.ok_btn.hasFocus() is True
    assert dialog.save_exif_checkbox.hasFocus() is False

    dialog.close()


def test_archive_dialog_exif_stage_shows_compact_progress_and_suspends_watcher(
    qapp, settings_store  # noqa: ARG001
):
    watcher_control = _WatcherControlSpy()
    window = _FakeArchiveWindow()
    item = _item("/photos/root/a.jpg")
    item.db_metadata = {"title": "Title"}
    dialog = ArchiveDialog(
        window,
        root_folder="/photos/root",
        archive_path="/archive/root",
        items=[item],
        source_folders=["/photos/root"],
        watcher_control=watcher_control,
    )

    dialog.show()
    qapp.processEvents()
    initial_height = dialog.height()

    dialog.save_exif_checkbox.setChecked(True)
    dialog._start_archive()
    qapp.processEvents()

    assert watcher_control.suspend_calls == 1
    assert dialog.summary_label.isHidden() is True
    assert dialog.progress_header_widget.isHidden() is False
    assert dialog.progress_count_label.text() == "0/1"
    assert dialog.ok_btn.text() == "Cancel"
    assert dialog.ok_btn.isEnabled() is True
    assert dialog.cancel_btn.isHidden() is True
    assert dialog.save_exif_checkbox.isHidden() is True
    assert dialog.height() < initial_height

    dialog._cancel_exif_stage()
    dialog.close()


def test_archive_dialog_exif_progress_updates_counter_and_bar(
    qapp, settings_store  # noqa: ARG001
):
    watcher_control = _WatcherControlSpy()
    window = _FakeArchiveWindow()
    items = [_item("/photos/root/a.jpg"), _item("/photos/root/b.jpg"), _item("/photos/root/c.jpg")]
    for index, item in enumerate(items):
        item.db_metadata = {"title": f"Title {index}"}

    dialog = ArchiveDialog(
        window,
        root_folder="/photos/root",
        archive_path="/archive/root",
        items=items,
        source_folders=["/photos/root"],
        watcher_control=watcher_control,
    )

    dialog.save_exif_checkbox.setChecked(True)
    dialog._start_archive()
    window.media_manager.write_progress.emit(1, 3)

    assert dialog.progress_bar.value() == 1
    assert dialog.progress_bar.format() == "1/3"
    assert dialog.progress_count_label.text() == "1/3"

    dialog._cancel_exif_stage()


def test_archive_dialog_finished_state_keeps_current_width(
    qapp, settings_store  # noqa: ARG001
):
    window = _FakeArchiveWindow()
    item = _item("/photos/root/a.jpg")
    item.db_metadata = {"title": "Title"}
    dialog = ArchiveDialog(
        window,
        root_folder="/photos/root",
        archive_path="/archive/root",
        items=[item],
        source_folders=["/photos/root"],
    )

    dialog.show()
    qapp.processEvents()
    dialog.resize(760, dialog.height())
    qapp.processEvents()

    dialog._show_finished_result(
        text=(
            "Archive complete.\nMoved to:\n"
            "/Volumes/CrucialX8/photos/__uploaded/20260308_croixstecatherine"
        ),
    )
    qapp.processEvents()

    assert dialog.width() == 760

    dialog.close()


def test_archive_dialog_unchecked_exif_starts_move_immediately(qapp, settings_store):  # noqa: ARG001
    window = _FakeArchiveWindow()
    dialog = ArchiveDialog(
        window,
        root_folder="/photos/root",
        archive_path="/archive/root",
        items=[_item("/photos/root/a.jpg")],
        source_folders=["/photos/root"],
    )
    dialog.save_exif_checkbox.setChecked(False)
    started: list[bool] = []
    dialog._start_move_stage = lambda: started.append(True)

    dialog._start_archive()

    assert started == [True]
    assert window.media_manager.write_calls == []


def test_archive_dialog_exif_cancel_stops_before_move_and_resumes_watcher(
    qapp, settings_store  # noqa: ARG001
):
    watcher_control = _WatcherControlSpy()
    window = _FakeArchiveWindow()
    item = _item("/photos/root/a.jpg")
    item.db_metadata = {"title": "Title"}
    dialog = ArchiveDialog(
        window,
        root_folder="/photos/root",
        archive_path="/archive/root",
        items=[item],
        source_folders=["/photos/root"],
        watcher_control=watcher_control,
    )
    started: list[bool] = []
    dialog._start_move_stage = lambda: started.append(True)

    dialog.save_exif_checkbox.setChecked(True)
    dialog._start_archive()
    dialog._on_ok_clicked()
    window.media_manager.write_all_completed.emit()

    assert window.media_manager.stop_write_calls == 1
    assert watcher_control.suspend_calls == 1
    assert watcher_control.resume_calls == 1
    assert started == []
    assert dialog._finished is True
    assert dialog.summary_label.text() == "Archive cancelled. The folder was not moved."


def test_archive_dialog_exif_failure_stops_before_move(qapp, settings_store):  # noqa: ARG001
    window = _FakeArchiveWindow()
    watcher_control = _WatcherControlSpy()
    item = _item("/photos/root/a.jpg")
    item.db_metadata = {"title": "Title"}
    dialog = ArchiveDialog(
        window,
        root_folder="/photos/root",
        archive_path="/archive/root",
        items=[item],
        source_folders=["/photos/root"],
        watcher_control=watcher_control,
    )
    dialog.save_exif_checkbox.setChecked(True)
    started: list[bool] = []
    dialog._start_move_stage = lambda: started.append(True)

    dialog._start_archive()
    window.media_manager.write_file_completed.emit(item.path, False, "boom")
    window.media_manager.write_all_completed.emit()

    assert len(window.media_manager.write_calls) == 1
    assert watcher_control.suspend_calls == 1
    assert watcher_control.resume_calls == 1
    assert started == []
    assert dialog._finished is True
    assert "The folder was not moved" in dialog.summary_label.text()


def test_archive_dialog_exif_success_keeps_watcher_suspended_until_move(
    qapp, settings_store  # noqa: ARG001
):
    watcher_control = _WatcherControlSpy()
    window = _FakeArchiveWindow()
    item = _item("/photos/root/a.jpg")
    item.db_metadata = {"title": "Title"}
    dialog = ArchiveDialog(
        window,
        root_folder="/photos/root",
        archive_path="/archive/root",
        items=[item],
        source_folders=["/photos/root"],
        watcher_control=watcher_control,
    )
    started: list[bool] = []
    dialog._start_move_stage = lambda: started.append(True)

    dialog.save_exif_checkbox.setChecked(True)
    dialog._start_archive()
    window.media_manager.write_all_completed.emit()

    assert watcher_control.suspend_calls == 1
    assert watcher_control.resume_calls == 0
    assert started == [True]


def test_archive_dialog_move_prepare_failure_after_exif_success_resumes_watcher(
    qapp, settings_store  # noqa: ARG001
):
    watcher_control = _WatcherControlSpy()
    window = _FakeArchiveWindow()
    item = _item("/photos/root/a.jpg")
    item.db_metadata = {"title": "Title"}
    dialog = ArchiveDialog(
        window,
        root_folder="/photos/root",
        archive_path="/archive/root",
        items=[item],
        source_folders=["/photos/root"],
        watcher_control=watcher_control,
    )

    def _raise_prepare() -> None:
        raise RuntimeError("boom")

    window._prepare_workspace_for_archive_move = _raise_prepare

    dialog.save_exif_checkbox.setChecked(True)
    dialog._start_archive()
    window.media_manager.write_all_completed.emit()

    assert watcher_control.suspend_calls == 1
    assert watcher_control.resume_calls == 1
    assert dialog._finished is True
    assert dialog.summary_label.text() == "Archive could not start."
    assert dialog.error_label.text() == "boom"


def test_archive_dialog_move_stage_uses_current_root_and_source_folders(
    qapp, settings_store, monkeypatch  # noqa: ARG001
):
    window = _FakeArchiveWindow()
    dialog = ArchiveDialog(
        window,
        root_folder="/photos/root",
        archive_path="/archive/root",
        items=[],
        source_folders=["/photos/root", "/photos/root/xs20"],
    )

    captured: dict[str, object] = {}

    class _WorkerStub:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self.signals = type(
                "_Signals",
                (),
                {"finished": type("_Finished", (), {"connect": lambda self, cb: None})()},
            )()

    class _FakePool:
        def __init__(self):
            self.started: list[object] = []

        def start(self, worker) -> None:
            self.started.append(worker)

    fake_pool = _FakePool()
    monkeypatch.setattr("piqopiqo.tools.archive.ArchiveMoveWorker", _WorkerStub)
    monkeypatch.setattr(
        "piqopiqo.tools.archive.QThreadPool",
        type(
            "_FakeThreadPool",
            (),
            {"globalInstance": staticmethod(lambda: fake_pool)},
        ),
    )

    dialog._start_move_stage()

    assert window.prepare_calls == 1
    assert captured == {
        "root_folder": "/photos/root",
        "archive_path": "/archive/root",
        "source_folders": ["/photos/root", "/photos/root/xs20"],
    }
    assert len(fake_pool.started) == 1


def test_archive_move_worker_cleans_only_loaded_source_folders(monkeypatch):
    thumb_calls: list[list[str]] = []
    metadata_calls: list[list[str]] = []
    moved: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "piqopiqo.tools.archive.shutil.move",
        lambda src, dst: moved.append((src, dst)) or dst,
    )
    monkeypatch.setattr(
        "piqopiqo.tools.archive.clear_thumb_cache_for_folders",
        lambda folders: thumb_calls.append(list(folders)),
    )
    monkeypatch.setattr(
        "piqopiqo.tools.archive.clear_metadata_cache_for_folders",
        lambda folders: metadata_calls.append(list(folders)),
    )
    worker = ArchiveMoveWorker(
        root_folder="/photos/root",
        archive_path="/archive/root",
        source_folders=["/photos/root", "/photos/root/xs20"],
    )
    results: list[ArchiveMoveResult] = []
    worker.signals.finished.connect(lambda result: results.append(result))

    worker.run()

    assert moved == [("/photos/root", "/archive/root")]
    assert metadata_calls == [["/photos/root", "/photos/root/xs20"]]
    assert thumb_calls == [["/photos/root", "/photos/root/xs20"]]
    assert results == [
        ArchiveMoveResult(success=True, archive_path="/archive/root", cleanup_error="")
    ]


def test_archive_dialog_move_failure_restores_workspace_when_source_still_exists(
    qapp, settings_store  # noqa: ARG001
):
    window = _FakeArchiveWindow()
    dialog = ArchiveDialog(
        window,
        root_folder="/photos/root",
        archive_path="/archive/root",
        items=[],
        source_folders=[],
    )

    dialog._on_move_finished(
        ArchiveMoveResult(
            success=False,
            archive_path="/archive/root",
            move_error="boom",
            source_exists_after_failure=True,
        )
    )

    assert window.resume_calls == 1
    assert window.unload_calls == []
    assert dialog._finished is True


def test_archive_dialog_success_does_not_override_folder_dialog_hint(
    qapp, settings_store  # noqa: ARG001
):
    window = _FakeArchiveWindow()
    dialog = ArchiveDialog(
        window,
        root_folder="/photos/root",
        archive_path="/archive/root",
        items=[],
        source_folders=[],
    )

    dialog._on_move_finished(
        ArchiveMoveResult(
            success=True,
            archive_path="/archive/root",
            cleanup_error="",
        )
    )

    assert window.folder_dialog_hint_updates == []
    assert window.removed_recent_folders == ["/photos/root"]
    assert window.unload_calls == [True]


def test_unload_workspace_clears_current_folder_state(main_window, settings_store):
    get_state().set(StateKey.LAST_FOLDER, str(main_window.root_folder))
    main_window._last_visible_paths = [main_window.photo_model.all_photos[0].path]
    active_filter = FilterCriteria(search_text="missing")
    main_window._current_filter = main_window.photo_model.normalize_filter_criteria(
        active_filter
    )
    main_window.photo_model.set_filter(active_filter)

    main_window._unload_workspace(clear_last_folder=True)

    assert main_window.root_folder is None
    assert main_window.source_folders == []
    assert main_window._current_filter is None
    assert main_window.photo_model._filter is None
    assert main_window.photo_model.all_photos == []
    assert main_window.photo_model.source_folders == []
    assert main_window.filter_panel.folder_combo.isEnabled() is False
    assert main_window._items_by_path == {}
    assert main_window._last_visible_paths == []
    assert get_state_value(StateKey.LAST_FOLDER) == ""


def test_open_folder_after_unload_does_not_keep_stale_filter(
    main_window,
    tmp_path,
    monkeypatch,
):
    active_filter = FilterCriteria(search_text="missing")
    main_window._current_filter = main_window.photo_model.normalize_filter_criteria(
        active_filter
    )
    main_window.photo_model.set_filter(active_filter)
    assert main_window.photo_model.photos == []

    main_window._unload_workspace(clear_last_folder=True)

    new_root = tmp_path / "new-root"
    new_root.mkdir()
    new_image = new_root / "visible.jpg"
    new_image.write_bytes(b"jpg")

    monkeypatch.setattr(
        "piqopiqo.main_window.scan_folder",
        lambda folder: (
            [
                {
                    "path": str(new_image),
                    "name": new_image.name,
                    "state": 0,
                    "created": "2026-01-02 10:00:00",
                    "source_folder": str(new_root),
                }
            ],
            [str(new_root)],
        ),
    )

    main_window._clear_filters_before_folder_load()
    main_window._load_folder(str(new_root), reset_grid_to_top=True)

    assert [item.path for item in main_window.photo_model.photos] == [str(new_image)]

    main_window.filter_panel.clear_filter()
    if main_window._filter_apply_scheduled:
        main_window._apply_pending_filter_change()

    assert [item.path for item in main_window.photo_model.photos] == [str(new_image)]
