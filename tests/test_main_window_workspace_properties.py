"""Tests for workspace property and about integration in MainWindow."""

from __future__ import annotations

import os
import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
import pytest

from piqopiqo.background.media_man import FolderPrimingResult
from piqopiqo.main_window import MainWindow
from piqopiqo.model import ImageItem, MapLinkOption
from piqopiqo.ssf.settings_state import (
    APP_NAME,
    StateKey,
    UserSettingKey,
    get_state_value,
    init_qsettings_store,
    set_state_value,
    set_user_setting,
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
        self.reset_calls: list[tuple[list[str], list[str]]] = []
        self.visible_calls: list[list[str]] = []
        self.pause_calls = 0
        self.resume_calls = 0

    def reset_for_folder(
        self, file_paths: list[str], source_folders: list[str]
    ) -> FolderPrimingResult:
        self.reset_calls.append((list(file_paths), list(source_folders)))
        return self.next_priming_result

    def pause_processing(self) -> None:
        self.pause_calls += 1

    def resume_processing(self) -> None:
        self.resume_calls += 1

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
    _MediaManagerStub.next_priming_result = FolderPrimingResult({}, set())
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


def _action_by_text(
    window: MainWindow, menu_title: str, action_text: str
) -> QAction | None:
    menu = _menu_by_title(window, menu_title)
    if menu is None:
        return None
    for action in menu.actions():
        if action.text() == action_text:
            return action
    return None


def _submenu_by_text(window: MainWindow, menu_title: str, submenu_text: str):
    action = _action_by_text(window, menu_title, submenu_text)
    if action is None:
        return None
    return action.menu()


def _submenu_action_texts(
    window: MainWindow,
    menu_title: str,
    submenu_text: str,
) -> list[str]:
    submenu = _submenu_by_text(window, menu_title, submenu_text)
    if submenu is None:
        return []
    return [action.text() for action in submenu.actions()]


def _submenu_action_tooltips(
    window: MainWindow,
    menu_title: str,
    submenu_text: str,
) -> list[str]:
    submenu = _submenu_by_text(window, menu_title, submenu_text)
    if submenu is None:
        return []
    return [action.toolTip() for action in submenu.actions()]


def test_file_menu_contains_property_and_not_clear_all_data(window):
    file_menu = _menu_by_title(window, "File")
    assert file_menu is not None

    action_texts = [action.text() for action in file_menu.actions()]
    assert "Property..." in action_texts
    assert "Clear All Data" not in action_texts


def test_file_menu_contains_open_recent_between_open_folder_and_property(window):
    file_menu = _menu_by_title(window, "File")
    assert file_menu is not None

    action_texts = [action.text() for action in file_menu.actions()]

    assert "Open Recent" in action_texts
    assert action_texts.index("Open Folder...") < action_texts.index("Open Recent")
    assert action_texts.index("Open Recent") < action_texts.index("Property...")


def test_open_recent_menu_is_disabled_when_empty(window):
    action = _action_by_text(window, "File", "Open Recent")

    assert action is not None
    assert action.isEnabled() is False
    assert action.menu() is not None
    assert action.menu().isEnabled() is False


def test_favorite_folder_action_is_hidden_when_setting_is_empty(window):
    action = _action_by_text(
        window,
        "File",
        "Open Favorite Folder...",
    )

    assert action is not None
    assert action.isVisible() is False


def test_favorite_folder_action_updates_visibility_when_setting_changes(window):
    action = _action_by_text(
        window,
        "File",
        "Open Favorite Folder...",
    )
    assert action is not None

    set_user_setting(UserSettingKey.FAVORITE_FOLDER, "/favorite")
    window._apply_settings_changes({UserSettingKey.FAVORITE_FOLDER})
    assert action.isVisible() is True

    set_user_setting(UserSettingKey.FAVORITE_FOLDER, "")
    window._apply_settings_changes({UserSettingKey.FAVORITE_FOLDER})
    assert action.isVisible() is False


def test_open_recent_menu_excludes_current_folder(window, tmp_path):
    current_folder = tmp_path / "current"
    other_a = tmp_path / "other-a"
    other_b = tmp_path / "other-b"
    window.root_folder = str(current_folder)

    window._set_recent_folder_history([str(current_folder), str(other_a), str(other_b)])

    assert _submenu_action_tooltips(window, "File", "Open Recent") == [
        MainWindow._canonicalize_recent_folder_path(str(other_a)),
        MainWindow._canonicalize_recent_folder_path(str(other_b)),
    ]


def test_recent_folder_history_moves_reopened_folder_to_top_without_duplication(window):
    folder_a = "/Volumes/Archive/folder-a"
    folder_b = "/Volumes/Archive/folder-b"

    window._remember_recent_folder_in_history(folder_a)
    window._remember_recent_folder_in_history(folder_b)
    window._remember_recent_folder_in_history(folder_a)

    assert get_state_value(StateKey.RECENT_FOLDERS) == [
        MainWindow._canonicalize_recent_folder_path(folder_a),
        MainWindow._canonicalize_recent_folder_path(folder_b),
    ]
    assert _submenu_action_tooltips(window, "File", "Open Recent") == [
        MainWindow._canonicalize_recent_folder_path(folder_a),
        MainWindow._canonicalize_recent_folder_path(folder_b),
    ]


def test_open_recent_menu_relabels_when_favorite_folder_changes(window, tmp_path):
    favorite_folder = tmp_path / "favorite"
    recent_folder = favorite_folder / "trip" / "shoot"

    set_user_setting(UserSettingKey.FAVORITE_FOLDER, "")
    window._set_recent_folder_history([str(recent_folder)])

    assert _submenu_action_texts(window, "File", "Open Recent") == [
        MainWindow._canonicalize_recent_folder_path(str(recent_folder))
    ]

    set_user_setting(UserSettingKey.FAVORITE_FOLDER, str(favorite_folder))
    window._apply_settings_changes({UserSettingKey.FAVORITE_FOLDER})

    assert _submenu_action_texts(window, "File", "Open Recent") == ["trip/shoot"]


def test_format_recent_folder_label_prefers_favorite_relative(window, tmp_path):
    favorite_folder = tmp_path / "favorite"
    recent_folder = favorite_folder / "trip" / "shoot"
    set_user_setting(UserSettingKey.FAVORITE_FOLDER, str(favorite_folder))

    assert window._format_recent_folder_label(str(recent_folder)) == "trip/shoot"


def test_format_recent_folder_label_uses_home_tilde(window):
    set_user_setting(UserSettingKey.FAVORITE_FOLDER, "")
    recent_folder = os.path.join(os.path.expanduser("~"), "photos", "trip")

    assert window._format_recent_folder_label(recent_folder) == "~/photos/trip"


def test_format_recent_folder_label_falls_back_to_full_path_without_trailing_slash(
    window,
):
    set_user_setting(UserSettingKey.FAVORITE_FOLDER, "")

    assert (
        window._format_recent_folder_label("/Volumes/Archive/photos/")
        == "/Volumes/Archive/photos"
    )


def test_open_recent_folder_clears_filters_and_loads(window, monkeypatch, tmp_path):
    recent_folder = tmp_path / "recent"
    recent_folder.mkdir()
    calls: list[object] = []

    monkeypatch.setattr(
        window,
        "_clear_filters_before_folder_load",
        lambda: calls.append("clear"),
    )
    monkeypatch.setattr(
        window,
        "_load_folder",
        lambda folder, *, reset_grid_to_top=False: calls.append(
            ("load", folder, reset_grid_to_top)
        ),
    )

    window._on_open_recent_folder(str(recent_folder))

    assert calls == [
        "clear",
        (
            "load",
            MainWindow._canonicalize_recent_folder_path(str(recent_folder)),
            True,
        ),
    ]


def test_open_recent_folder_missing_keeps_workspace_and_removes_history(
    window,
    monkeypatch,
    tmp_path,
):
    current_folder = tmp_path / "current"
    current_folder.mkdir()
    missing_folder = tmp_path / "missing"
    window.root_folder = str(current_folder)
    set_state_value(StateKey.RECENT_FOLDERS, [str(missing_folder)])
    window._refresh_open_recent_menu()

    warning_calls: list[tuple[str, str]] = []
    clear_calls: list[bool] = []
    load_calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "piqopiqo.main_window.QMessageBox.warning",
        lambda _parent, title, text: warning_calls.append((title, text)),
    )
    monkeypatch.setattr(
        window,
        "_clear_filters_before_folder_load",
        lambda: clear_calls.append(True),
    )
    monkeypatch.setattr(
        window,
        "_load_folder",
        lambda folder, *, reset_grid_to_top=False: load_calls.append(
            (folder, reset_grid_to_top)
        ),
    )

    window._on_open_recent_folder(str(missing_folder))

    assert warning_calls == [
        (
            "Open Recent",
            "The selected recent folder could not be found.\n\n"
            f"{MainWindow._canonicalize_recent_folder_path(str(missing_folder))}",
        )
    ]
    assert window.root_folder == str(current_folder)
    assert clear_calls == []
    assert load_calls == []
    assert get_state_value(StateKey.RECENT_FOLDERS) == []


def test_map_links_setting_updates_edit_panel_visibility_live(window):
    assert window.edit_panel.map_btn.isHidden() is True

    set_user_setting(
        UserSettingKey.MAP_LINKS,
        [
            MapLinkOption(
                name="Google Maps",
                url_template=(
                    "https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                ),
            )
        ],
    )
    window._apply_settings_changes({UserSettingKey.MAP_LINKS})
    assert window.edit_panel.map_btn.isHidden() is False

    set_user_setting(UserSettingKey.MAP_LINKS, [])
    window._apply_settings_changes({UserSettingKey.MAP_LINKS})
    assert window.edit_panel.map_btn.isHidden() is True


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
