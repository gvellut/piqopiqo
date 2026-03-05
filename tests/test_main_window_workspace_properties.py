"""Tests for workspace property and about integration in MainWindow."""

from __future__ import annotations

import re
import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
import pytest

from piqopiqo import __version__ as piqopiqo_version
from piqopiqo.main_window import MainWindow
from piqopiqo.model import ImageItem
from piqopiqo.ssf.settings_state import APP_NAME, init_qsettings_store


class _SignalStub:
    def connect(self, *_args, **_kwargs) -> None:
        return None


class _MediaManagerStub:
    def __init__(self, *_args, **_kwargs):
        self.thumb_ready = _SignalStub()
        self.thumb_progress_updated = _SignalStub()
        self.editable_ready = _SignalStub()
        self.exif_progress_updated = _SignalStub()
        self.panel_fields_ready = _SignalStub()
        self.all_completed = _SignalStub()
        self.reset_calls: list[tuple[list[str], list[str]]] = []
        self.visible_calls: list[list[str]] = []

    def reset_for_folder(
        self, file_paths: list[str], source_folders: list[str]
    ) -> None:
        self.reset_calls.append((list(file_paths), list(source_folders)))

    def update_visible(self, visible_paths_in_order: list[str]) -> None:
        self.visible_calls.append(list(visible_paths_in_order))

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

    def reload_exif(self, _file_paths: list[str]) -> None:
        return None

    def ensure_panel_fields_loaded_from_db(self, _file_paths: list[str]) -> None:
        return None

    def refresh_exif_field_keys(self, _field_keys: list[str]) -> None:
        return None

    def stop(self, timeout_s: float | None = None) -> None:  # noqa: ARG002
        return None


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-main-window-workspace-{uuid.uuid4().hex}")
    return app


@pytest.fixture
def window(qapp, monkeypatch):  # noqa: ARG001
    init_qsettings_store(dyn=True)
    monkeypatch.setattr("piqopiqo.main_window.MediaManager", _MediaManagerStub)
    monkeypatch.setattr(
        "piqopiqo.main_window.refresh_main_screen_color_space_cache_macos",
        lambda: None,
    )

    main_window = MainWindow([], [], None)
    yield main_window
    main_window.close()


def _menu_by_title(window: MainWindow, title: str):
    for menu_action in window.menuBar().actions():
        menu = menu_action.menu()
        if menu is not None and menu.title() == title:
            return menu
    return None


def test_file_menu_contains_property_and_not_clear_all_data(window):
    file_menu = _menu_by_title(window, "File")
    assert file_menu is not None

    action_texts = [action.text() for action in file_menu.actions()]
    assert "Property..." in action_texts
    assert "Clear All Data" not in action_texts


def test_about_action_uses_about_role_and_stays_in_help(window):
    about_text = f"About {APP_NAME}"
    about_actions = [
        action for action in window.findChildren(QAction) if action.text() == about_text
    ]
    assert about_actions
    about_action = about_actions[0]
    assert about_action.menuRole() == QAction.MenuRole.AboutRole

    help_menu = _menu_by_title(window, "Help")
    assert help_menu is not None
    assert about_action in help_menu.actions()


def test_open_workspace_properties_accept_without_flags_does_not_start_cleanup(
    window, monkeypatch
):
    window.root_folder = "/photos"

    class _DialogNoAction:
        def __init__(self, **_kwargs) -> None:
            self.clear_thumb_cache_requested = False
            self.clear_metadata_requested = False

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

    calls: list[dict] = []
    monkeypatch.setattr(
        "piqopiqo.main_window.WorkspacePropertiesDialog", _DialogNoAction
    )
    monkeypatch.setattr(
        window, "_start_workspace_cleanup", lambda **kwargs: calls.append(kwargs)
    )

    window._on_open_workspace_properties()

    assert calls == []


def test_open_workspace_properties_accept_with_flags_starts_cleanup(
    window, monkeypatch
):
    window.root_folder = "/photos"

    class _DialogWithAction:
        def __init__(self, **_kwargs) -> None:
            self.clear_thumb_cache_requested = True
            self.clear_metadata_requested = False

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

    calls: list[dict] = []
    monkeypatch.setattr(
        "piqopiqo.main_window.WorkspacePropertiesDialog", _DialogWithAction
    )
    monkeypatch.setattr(
        window, "_start_workspace_cleanup", lambda **kwargs: calls.append(kwargs)
    )

    window._on_open_workspace_properties()

    assert calls == [{"clear_thumb_cache": True, "clear_metadata": False}]


def test_start_workspace_cleanup_guard_prevents_reentry(window, monkeypatch):
    window._workspace_cleanup_running = True
    info_calls: list[tuple[str, str]] = []

    def _info_stub(_parent, title: str, text: str):
        info_calls.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", _info_stub)

    window._start_workspace_cleanup(clear_thumb_cache=True, clear_metadata=False)

    assert len(info_calls) == 1
    assert info_calls[0][0] == "Workspace Property"


def test_cleanup_finished_requeues_media_loading(window):
    item = ImageItem(
        path="/photos/a.jpg",
        name="a.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/photos",
    )
    window.photo_model.set_photos([item], ["/photos"])
    window._items_by_path = {item.path: item}
    window._last_visible_paths = [item.path]
    window._workspace_cleanup_running = True
    window._workspace_cleanup_context = {
        "source_folders": ["/photos"],
        "file_paths": [item.path],
    }

    window._on_workspace_cleanup_finished(None)

    assert window._workspace_cleanup_running is False
    assert window._workspace_cleanup_context is None
    assert window.media_manager.reset_calls[-1] == ([item.path], ["/photos"])
    assert window.media_manager.visible_calls[-1] == [item.path]
    assert item.state == 0
    assert item.embedded_pixmap is None
    assert item.hq_pixmap is None
    assert item.pixmap is None
    assert item.db_metadata is None
    assert item.exif_data is None


def test_about_dialog_contains_version_date_and_github_link(window, monkeypatch):
    captured: list[tuple[str, str]] = []

    def _about_stub(_parent, title: str, text: str):
        captured.append((title, text))

    monkeypatch.setattr(QMessageBox, "about", _about_stub)

    window.on_about()

    assert len(captured) == 1
    title, message = captured[0]
    assert title == f"About {APP_NAME}"
