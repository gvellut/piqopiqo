"""Tests for duplicate and external-edit context menu actions."""

from __future__ import annotations

from datetime import datetime
import shutil
import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.cache_paths import set_cache_base_dir
import piqopiqo.grid.context_menu as context_menu
from piqopiqo.grid.context_menu import duplicate_photos, edit_in_external_app
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDBManager
from piqopiqo.model import ImageItem
from piqopiqo.photo_model import PhotoListModel, SortOrder
from piqopiqo.ssf.settings_state import init_qsettings_store


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-context-menu-{uuid.uuid4().hex}")
    return app


@pytest.fixture(autouse=True)
def _test_environment(tmp_path):
    set_cache_base_dir(tmp_path / "cache")
    init_qsettings_store(dyn=True)


class _StatusBarStub:
    def __init__(self) -> None:
        self.messages: list[tuple[str, int]] = []

    def showMessage(self, text: str, timeout: int) -> None:
        self.messages.append((text, timeout))


class _WindowStub:
    def __init__(
        self,
        items: list[ImageItem],
        *,
        source_folder: str,
        sort_order: SortOrder = SortOrder.FILE_NAME,
    ) -> None:
        self.db_manager = MetadataDBManager()
        self.photo_model = PhotoListModel(self.db_manager)
        self.photo_model.set_photos(items, [source_folder])
        self.photo_model.set_sort_order(sort_order, emit_signals=False)
        self.status_bar = _StatusBarStub()
        self.suppressed_paths: list[list[str]] = []
        self.selection_calls: list[tuple[list[str], str | None, str | None]] = []

    @property
    def images_data(self) -> list[ImageItem]:
        return self.photo_model.photos

    def _suppress_watcher_paths(self, paths: list[str]) -> None:
        self.suppressed_paths.append(list(paths))

    def select_paths_in_grid(
        self,
        paths: list[str],
        *,
        anchor_path: str | None = None,
        reveal_path: str | None = None,
    ) -> None:
        visible = {item.path for item in self.images_data}
        selected_paths = [path for path in paths if path in visible]
        self.selection_calls.append((selected_paths, anchor_path, reveal_path))
        path_set = set(selected_paths)
        for item in self.images_data:
            item.is_selected = item.path in path_set

    def selected_paths(self) -> list[str]:
        return [item.path for item in self.images_data if item.is_selected]


def _write_file(path) -> None:
    path.write_bytes(b"not-a-real-image")


def _item(
    path: str,
    *,
    created: str = "2020-01-01 00:00:00",
    selected: bool = False,
    metadata: dict | None = None,
) -> ImageItem:
    return ImageItem(
        path=path,
        name=path.split("/")[-1],
        created=created,
        source_folder=str(path.rsplit("/", 1)[0]),
        is_selected=selected,
        db_metadata=metadata,
    )


def _full_metadata(*, time_taken: datetime | None = None) -> dict:
    return {
        DBFields.TITLE: "Title",
        DBFields.DESCRIPTION: "Description",
        DBFields.LATITUDE: 48.8566,
        DBFields.LONGITUDE: 2.3522,
        DBFields.KEYWORDS: "alpha, beta",
        DBFields.TIME_TAKEN: time_taken,
        DBFields.LABEL: "Approved",
        DBFields.ORIENTATION: 6,
        DBFields.MANUAL_LENS_MAKE: "Leica",
        DBFields.MANUAL_LENS_MODEL: "Summicron",
        DBFields.MANUAL_FOCAL_LENGTH: "35",
        DBFields.MANUAL_FOCAL_LENGTH_35MM: "35",
    }


def test_duplicate_photos_clones_metadata_and_selects_duplicates(qapp, tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    original_path = folder / "a.jpg"
    _write_file(original_path)

    metadata = _full_metadata(time_taken=datetime(2026, 1, 1, 10, 0, 0))
    source = _item(str(original_path), selected=True)
    window = _WindowStub([source], source_folder=str(folder))
    db = window.db_manager.get_db_for_folder(str(folder))
    db.save_metadata(str(original_path), metadata)

    duplicate_photos(window, [source])

    duplicated_path = str(folder / "a copy.jpg")
    duplicated_item = next(
        item for item in window.photo_model.all_photos if item.path == duplicated_path
    )

    assert original_path.exists()
    assert (folder / "a copy.jpg").exists()
    assert db.get_metadata(duplicated_path) == metadata
    assert duplicated_item.db_metadata == metadata
    assert duplicated_item.db_metadata is not source.db_metadata
    assert duplicated_item.created == source.created
    assert window.selected_paths() == [duplicated_path]
    assert source.is_selected is False
    assert window.selection_calls == [
        ([duplicated_path], duplicated_path, duplicated_path)
    ]

    window.db_manager.close_all()


def test_edit_in_external_app_clones_metadata_selects_duplicates_and_opens_them(
    qapp, tmp_path, monkeypatch
):
    folder = tmp_path / "photos"
    folder.mkdir()
    original_path = folder / "a.jpg"
    _write_file(original_path)

    metadata = _full_metadata(time_taken=datetime(2026, 1, 1, 10, 0, 0))
    source = _item(str(original_path), selected=True)
    window = _WindowStub([source], source_folder=str(folder))
    db = window.db_manager.get_db_for_folder(str(folder))
    db.save_metadata(str(original_path), metadata)

    opened: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        context_menu,
        "open_in_external_app_macos",
        lambda app_name, paths: opened.append((app_name, list(paths))),
    )
    monkeypatch.setattr(
        context_menu,
        "get_user_setting",
        lambda _key: "/Applications/TestEditor.app",
    )

    edit_in_external_app(window, [source])

    duplicated_path = str(folder / "a copy.jpg")
    assert db.get_metadata(duplicated_path) == metadata
    assert window.selected_paths() == [duplicated_path]
    assert opened == [
        ("/Applications/TestEditor.app", [duplicated_path]),
    ]

    window.db_manager.close_all()


def test_duplicate_stays_adjacent_when_sorting_by_time_taken(qapp, tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    older_path = folder / "a.jpg"
    newer_path = folder / "b.jpg"
    _write_file(older_path)
    _write_file(newer_path)

    older_metadata = _full_metadata(time_taken=datetime(2026, 1, 1, 10, 0, 0))
    newer_metadata = _full_metadata(time_taken=datetime(2026, 1, 1, 12, 0, 0))
    older_metadata[DBFields.TITLE] = "Older"
    newer_metadata[DBFields.TITLE] = "Newer"

    older = _item(str(older_path), metadata=older_metadata.copy(), selected=True)
    newer = _item(str(newer_path), metadata=newer_metadata.copy())
    window = _WindowStub(
        [newer, older],
        source_folder=str(folder),
        sort_order=SortOrder.TIME_TAKEN,
    )
    db = window.db_manager.get_db_for_folder(str(folder))
    db.save_metadata(str(older_path), older_metadata)
    db.save_metadata(str(newer_path), newer_metadata)

    duplicate_photos(window, [older])

    paths = [item.path for item in window.images_data]
    duplicated_path = str(folder / "a copy.jpg")
    assert paths == [duplicated_path, str(older_path), str(newer_path)]

    window.db_manager.close_all()


def test_duplicate_stays_adjacent_when_time_taken_is_missing(qapp, tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    first_path = folder / "a.jpg"
    second_path = folder / "b.jpg"
    _write_file(first_path)
    _write_file(second_path)

    first_metadata = _full_metadata(time_taken=None)
    second_metadata = _full_metadata(time_taken=None)
    first_metadata[DBFields.TITLE] = "First"
    second_metadata[DBFields.TITLE] = "Second"

    first = _item(
        str(first_path),
        created="2020-01-01 00:00:00",
        metadata=first_metadata.copy(),
        selected=True,
    )
    second = _item(
        str(second_path),
        created="2020-01-02 00:00:00",
        metadata=second_metadata.copy(),
    )
    window = _WindowStub(
        [second, first],
        source_folder=str(folder),
        sort_order=SortOrder.TIME_TAKEN,
    )
    db = window.db_manager.get_db_for_folder(str(folder))
    db.save_metadata(str(first_path), first_metadata)
    db.save_metadata(str(second_path), second_metadata)

    duplicate_photos(window, [first])

    paths = [item.path for item in window.images_data]
    duplicated_path = str(folder / "a copy.jpg")
    assert paths == [duplicated_path, str(first_path), str(second_path)]

    window.db_manager.close_all()


@pytest.mark.parametrize("action", [duplicate_photos, edit_in_external_app])
def test_duplicate_actions_abort_while_metadata_is_still_loading(
    qapp, tmp_path, monkeypatch, action
):
    folder = tmp_path / "photos"
    folder.mkdir()
    original_path = folder / "a.jpg"
    _write_file(original_path)

    source = _item(str(original_path), selected=True)
    window = _WindowStub([source], source_folder=str(folder))

    beeps: list[str] = []
    opened: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(QApplication, "beep", lambda: beeps.append("beep"))
    monkeypatch.setattr(
        context_menu,
        "open_in_external_app_macos",
        lambda app_name, paths: opened.append((app_name, list(paths))),
    )
    monkeypatch.setattr(
        context_menu,
        "get_user_setting",
        lambda _key: "/Applications/TestEditor.app",
    )

    action(window, [source])

    assert beeps == ["beep"]
    assert window.status_bar.messages == [("Reading...", 2000)]
    assert not (folder / "a copy.jpg").exists()
    assert len(window.photo_model.all_photos) == 1
    assert window.selection_calls == []
    assert opened == []

    window.db_manager.close_all()


def test_edit_in_external_app_keeps_best_effort_on_partial_copy_failure(
    qapp, tmp_path, monkeypatch
):
    folder = tmp_path / "photos"
    folder.mkdir()
    first_path = folder / "a.jpg"
    second_path = folder / "b.jpg"
    _write_file(first_path)
    _write_file(second_path)

    first_metadata = _full_metadata(time_taken=datetime(2026, 1, 1, 10, 0, 0))
    second_metadata = _full_metadata(time_taken=datetime(2026, 1, 1, 11, 0, 0))

    first = _item(str(first_path), selected=True)
    second = _item(str(second_path), selected=True)
    window = _WindowStub([first, second], source_folder=str(folder))
    db = window.db_manager.get_db_for_folder(str(folder))
    db.save_metadata(str(first_path), first_metadata)
    db.save_metadata(str(second_path), second_metadata)

    real_copy2 = shutil.copy2

    def _flaky_copy2(src: str, dst: str) -> str:
        if src == str(second_path):
            raise OSError("disk full")
        return real_copy2(src, dst)

    opened: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(context_menu.shutil, "copy2", _flaky_copy2)
    monkeypatch.setattr(
        context_menu,
        "open_in_external_app_macos",
        lambda app_name, paths: opened.append((app_name, list(paths))),
    )
    monkeypatch.setattr(
        context_menu,
        "get_user_setting",
        lambda _key: "/Applications/TestEditor.app",
    )

    edit_in_external_app(window, [first, second])

    duplicated_first = str(folder / "a copy.jpg")
    duplicated_second = str(folder / "b copy.jpg")
    assert db.get_metadata(duplicated_first) == first_metadata
    assert not (folder / "b copy.jpg").exists()
    assert window.selected_paths() == [duplicated_first]
    assert opened == [
        ("/Applications/TestEditor.app", [duplicated_first]),
    ]
    assert duplicated_second not in [
        item.path for item in window.photo_model.all_photos
    ]

    window.db_manager.close_all()
