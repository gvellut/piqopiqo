"""Tests for workspace property and about integration in MainWindow."""

from __future__ import annotations

import os
from types import SimpleNamespace
import uuid

from PySide6.QtCore import QCoreApplication, QPoint, QThreadPool
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox
import pytest

from piqopiqo.background.media_man import FolderPrimingResult
from piqopiqo.components.status_bar import NO_FOLDER_LOADED_TEXT
from piqopiqo.main_window import MainWindow
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.model import ImageItem, MapLinkOption, QgisRemoteControlSettings
from piqopiqo.photo_model import SortOrder
from piqopiqo.qgis_remote_control import QgisMapStatus, QgisRemoteControlError
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


def _intercept_context_menu_exec(monkeypatch, callback):
    class ContextMenu(QMenu):
        def exec(self, pos):
            callback(self, pos)

    monkeypatch.setattr("piqopiqo.grid.context_menu.QMenu", ContextMenu)


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


def test_status_bar_folder_label_defaults_to_no_folder_loaded(window):
    assert window.status_bar.folder_label.full_text == NO_FOLDER_LOADED_TEXT


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


def test_status_bar_folder_label_relabels_when_favorite_folder_changes(
    window,
    tmp_path,
):
    favorite_folder = tmp_path / "favorite"
    recent_folder = favorite_folder / "trip" / "shoot"
    window.root_folder = str(recent_folder)

    set_user_setting(UserSettingKey.FAVORITE_FOLDER, "")
    window._update_status_bar_folder_label()
    assert (
        window.status_bar.folder_label.full_text
        == MainWindow._canonicalize_recent_folder_path(str(recent_folder))
    )

    set_user_setting(UserSettingKey.FAVORITE_FOLDER, str(favorite_folder))
    window._apply_settings_changes({UserSettingKey.FAVORITE_FOLDER})

    assert window.status_bar.folder_label.full_text == "trip/shoot"


def test_status_bar_folder_label_uses_favorite_relative_after_load(
    window,
    monkeypatch,
    tmp_path,
):
    favorite_folder = tmp_path / "favorite"
    loaded_folder = favorite_folder / "trip" / "shoot"
    loaded_folder.mkdir(parents=True)
    set_user_setting(UserSettingKey.FAVORITE_FOLDER, str(favorite_folder))
    monkeypatch.setattr(
        "piqopiqo.main_window.scan_folder",
        lambda folder: ([], [folder]),
    )
    monkeypatch.setattr(window, "_start_folder_watcher", lambda: None)
    monkeypatch.setattr(window, "_stop_folder_watcher", lambda: None)

    window._load_folder(str(loaded_folder))

    assert window.status_bar.folder_label.full_text == "trip/shoot"


def test_status_bar_folder_label_resets_when_workspace_unloads(window):
    window.root_folder = "/Volumes/Archive/photos"
    window._update_status_bar_folder_label()
    assert window.status_bar.folder_label.full_text == "/Volumes/Archive/photos"

    window._unload_workspace(clear_last_folder=True)

    assert window.status_bar.folder_label.full_text == NO_FOLDER_LOADED_TEXT


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
        lambda folder, *, reset_grid_to_top=False: calls.append((
            "load",
            folder,
            reset_grid_to_top,
        )),
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
        lambda folder, *, reset_grid_to_top=False: load_calls.append((
            folder,
            reset_grid_to_top,
        )),
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


@pytest.mark.parametrize("entry", ["metadata", "grid"])
def test_qgis_map_failure_warning_and_retry_update_inline_status(
    window, qapp, monkeypatch, entry
):
    window.root_folder = "/photos"
    monkeypatch.delenv("PIQO_QGIS_REMOTE_CONTROL_ZOOM", raising=False)
    set_user_setting(UserSettingKey.QGIS_REMOTE_CONTROL_ZOOM, 18)
    monkeypatch.setattr(
        window.db_manager,
        "get_db_for_image",
        lambda _path: SimpleNamespace(has_metadata=lambda _path: True),
    )
    key = UserSettingKey.QGIS_REMOTE_CONTROL
    set_user_setting(
        key, QgisRemoteControlSettings(True, f"missing-{uuid.uuid4().hex}")
    )
    window._apply_settings_changes({key})
    panel = window.edit_panel
    photo = ImageItem(
        path="/photos/test.JPG",
        name="test.JPG",
        created="",
        db_metadata={DBFields.LATITUDE: "48", DBFields.LONGITUDE: "2"},
    )
    panel.update_for_selection([photo])
    monkeypatch.setattr(window.photo_model, "get_selected_photos", lambda: [photo])

    def trigger_map(menu, _pos):
        action = next(action for action in menu.actions() if action.text() == "Map")
        assert action.isEnabled()
        action.trigger()

    _intercept_context_menu_exec(monkeypatch, trigger_map)
    label = panel.qgis_map_status_label

    def click_and_finish():
        if entry == "grid":
            window._show_context_menu(0, QPoint())
        else:
            panel.map_btn.click()
        assert label.isHidden()
        assert QThreadPool.globalInstance().waitForDone(1000)
        qapp.processEvents()

    click_and_finish()
    assert not label.isHidden()
    assert label.full_text == "Cannot connect to QGIS Remote Control"

    results = iter([
        QgisRemoteControlError("Technical details"),
        QgisMapStatus.ZOOMED_TO_POSITION,
        None,
    ])

    def select_photo(*_args, coordinates, zoom):
        assert coordinates == (48.0, 2.0)
        assert zoom == 18
        result = next(results)
        if isinstance(result, QgisRemoteControlError):
            raise result
        return result

    monkeypatch.setattr("piqopiqo.qgis_remote_control.select_photo", select_photo)
    click_and_finish()
    assert not label.isHidden()
    assert label.full_text == "Error in QGIS Remote Control"
    red = label.styleSheet()

    click_and_finish()
    assert not label.isHidden()
    assert label.full_text == "Image not found. Zoomed to position"
    assert label.styleSheet() == f"color: {QColor('olive').name()};"
    assert label.styleSheet() != red

    click_and_finish()
    assert label.isHidden()


def test_grid_context_menu_preserves_sections_and_map_eligibility(window, monkeypatch):
    monkeypatch.setattr(
        window.db_manager,
        "get_db_for_image",
        lambda _path: SimpleNamespace(has_metadata=lambda _path: True),
    )
    set_user_setting(
        UserSettingKey.QGIS_REMOTE_CONTROL, QgisRemoteControlSettings(enabled=True)
    )
    set_user_setting(
        UserSettingKey.MAP_LINKS,
        [MapLinkOption("HTTP Map", "https://example.com/{lat}/{lon}")],
    )
    window._apply_settings_changes({
        UserSettingKey.QGIS_REMOTE_CONTROL,
        UserSettingKey.MAP_LINKS,
    })
    valid = ImageItem(
        path="/photos/position.JPG",
        name="position.JPG",
        created="",
        db_metadata={DBFields.LATITUDE: 0.0, DBFields.LONGITUDE: 2.0},
    )
    missing = ImageItem(
        path="/photos/no-position.JPG",
        name="no-position.JPG",
        created="",
        db_metadata={},
    )
    menus = []
    _intercept_context_menu_exec(monkeypatch, lambda menu, _pos: menus.append(menu))

    def open_menu(selection):
        monkeypatch.setattr(
            window.photo_model, "get_selected_photos", lambda: selection
        )
        window.edit_panel.update_for_selection(selection)
        window._show_context_menu(0, QPoint())
        return menus[-1].actions()

    actions = open_menu([valid])
    map_action = next(action for action in actions if action.text() == "Map")
    index = actions.index(map_action)
    assert actions[index - 1].isSeparator() and actions[index + 1].isSeparator()
    assert map_action.isEnabled()
    assert [action.text() for action in map_action.menu().actions()] == [
        "HTTP Map",
        "QGIS Remote Control",
    ]
    other_commands = actions[-1]
    assert other_commands.text() == "Other commands"
    assert [
        action.text() if not action.isSeparator() else None
        for action in other_commands.menu().actions()
    ] == [
        "Regenerate Thumbnail",
        "Reload EXIF",
        None,
        "Duplicate",
        None,
        "Move to Trash",
    ]

    for selection in ([missing], [valid, missing]):
        actions_by_name = {action.text(): action for action in open_menu(selection)}
        assert not actions_by_name["Map"].isEnabled()
        assert actions_by_name["Extract GPS Time Shift"].isEnabled() == (
            len(selection) == 1
        )


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

        def deleteLater(self):
            self.deletion_scheduled = True

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

        def deleteLater(self):
            self.deletion_scheduled = True

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


def test_metadata_cleanup_initializes_deferred_time_taken_resort(window):
    item = ImageItem(
        path="/photos/a.jpg",
        name="a.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/photos",
        db_metadata={DBFields.TIME_TAKEN: "old"},
    )
    window.photo_model.set_photos([item], ["/photos"])
    window.photo_model.set_sort_order(SortOrder.TIME_TAKEN, emit_signals=False)
    window._items_by_path = {item.path: item}
    window._workspace_cleanup_running = True
    window._workspace_cleanup_context = {
        "source_folders": ["/photos"],
        "file_paths": [item.path],
        "clear_thumb_cache": False,
        "clear_metadata": True,
    }
    _MediaManagerStub.next_priming_result = FolderPrimingResult({}, {item.path})

    window._on_workspace_cleanup_finished(None)

    state = window._deferred_time_taken_load_resort_state
    assert state is not None
    assert state.pending_paths == {item.path}
    assert state.processed_since_last_resort == 0


def test_metadata_only_cleanup_keeps_thumbnail_runtime_state(window):
    embedded = object()
    hq = object()
    display = object()
    item = ImageItem(
        path="/photos/a.jpg",
        name="a.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/photos",
        embedded_pixmap=embedded,
        hq_pixmap=hq,
        pixmap=display,
        state=7,
        exif_data={"File:FileName": "a.jpg"},
        db_metadata={DBFields.TIME_TAKEN: "old"},
    )
    item._cache_state_dirty = False
    window.photo_model.set_photos([item], ["/photos"])
    window._items_by_path = {item.path: item}
    window._workspace_cleanup_running = True
    window._workspace_cleanup_context = {
        "source_folders": ["/photos"],
        "file_paths": [item.path],
        "clear_thumb_cache": False,
        "clear_metadata": True,
    }
    _MediaManagerStub.next_priming_result = FolderPrimingResult({}, {item.path})

    window._on_workspace_cleanup_finished(None)

    assert item.embedded_pixmap is embedded
    assert item.hq_pixmap is hq
    assert item.pixmap is display
    assert item.state == 7
    assert item._cache_state_dirty is False
    assert item.db_metadata is None
    assert item.exif_data is None


def test_thumbnail_cleanup_keeps_metadata_runtime_state(window):
    item = ImageItem(
        path="/photos/a.jpg",
        name="a.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/photos",
        embedded_pixmap=object(),
        hq_pixmap=object(),
        pixmap=object(),
        state=7,
        exif_data={"File:FileName": "a.jpg"},
        db_metadata={DBFields.TIME_TAKEN: "old"},
    )
    item._cache_state_dirty = False
    window.photo_model.set_photos([item], ["/photos"])
    window._items_by_path = {item.path: item}
    window._workspace_cleanup_running = True
    window._workspace_cleanup_context = {
        "source_folders": ["/photos"],
        "file_paths": [item.path],
        "clear_thumb_cache": True,
        "clear_metadata": False,
    }

    window._on_workspace_cleanup_finished(None)

    assert item.embedded_pixmap is None
    assert item.hq_pixmap is None
    assert item.pixmap is None
    assert item.state == 0
    assert item.db_metadata == {DBFields.TIME_TAKEN: "old"}
    assert item.exif_data == {"File:FileName": "a.jpg"}


def test_about_dialog_contains_version_date_and_github_link(window, monkeypatch):
    captured: list[tuple[str, str]] = []

    def _about_stub(_parent, title: str, text: str):
        captured.append((title, text))

    monkeypatch.setattr(QMessageBox, "about", _about_stub)

    window.on_about()

    assert len(captured) == 1
    title, message = captured[0]
    assert title == f"About {APP_NAME}"
