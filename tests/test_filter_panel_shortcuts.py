"""Tests for FilterPanel folder refreshes and shortcut action helpers."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.panels.filter_panel import ALL_FOLDERS, FilterPanel
from piqopiqo.ssf.settings_state import (
    UserSettingKey,
    get_user_setting,
    init_qsettings_store,
    set_user_setting,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-filter-shortcuts-{uuid.uuid4().hex}")
    return app


def test_toggle_label_filter_and_no_label(qapp):
    init_qsettings_store(dyn=True)
    panel = FilterPanel()
    panel.set_folders(["/photos/a", "/photos/b"])

    label_name = get_user_setting(UserSettingKey.STATUS_LABELS)[0].name
    assert panel.toggle_label_filter(label_name) is True
    assert panel._label_checkboxes[label_name].isChecked() is True
    assert panel.toggle_label_filter(label_name) is True
    assert panel._label_checkboxes[label_name].isChecked() is False

    assert panel.toggle_label_filter(None) is True
    assert panel._no_label_checkbox is not None
    assert panel._no_label_checkbox.isChecked() is True
    assert panel.toggle_label_filter(None) is True
    assert panel._no_label_checkbox.isChecked() is False

    assert panel.toggle_label_filter("does-not-exist") is False


def test_current_filter_includes_current_explicit_labels(qapp):
    init_qsettings_store(dyn=True)
    panel = FilterPanel()
    panel.set_folders(["/photos/a", "/photos/b"])

    criteria = panel.get_current_filter()

    assert criteria.explicit_labels == set(panel._label_checkboxes)


@pytest.mark.parametrize(
    "value,include_no_label",
    [
        ("123", False),
        ("1 2 3", False),
        (" 12  3 1 ", False),
        ("0123", True),
        ("0 1 2 3", True),
        (" 012  3 1 0 ", True),
    ],
)
def test_base_labels_replace_labels_preserving_other_filters(
    qapp, value, include_no_label
):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.BASE_LABELS, value)
    panel = FilterPanel()
    panel.set_folders(["/photos/a", "/photos/b"])
    panel.folder_combo.setCurrentIndex(2)
    panel.search_field.setText("sunset")
    panel.toggle_label_filter(get_user_setting(UserSettingKey.STATUS_LABELS)[-1].name)
    panel.toggle_label_filter(None)
    emitted = []
    panel.filter_changed.connect(emitted.append)

    assert panel.apply_base_labels() is True

    criteria = panel.get_current_filter()
    assert criteria.labels == {
        label.name for label in get_user_setting(UserSettingKey.STATUS_LABELS)[:3]
    }
    assert criteria.include_no_label is include_no_label
    assert criteria.folder == "/photos/b"
    assert criteria.search_text == "sunset"
    assert panel.search_field.text() == "sunset"
    assert emitted == [criteria]
    assert panel.apply_base_labels() is False
    assert panel.get_current_filter() == criteria
    assert emitted == [criteria]


@pytest.mark.parametrize("value", ["0", " 0 0 "])
def test_base_labels_no_label_only_and_empty_have_distinct_filters(qapp, value):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.BASE_LABELS, value)
    panel = FilterPanel()
    panel.set_folders(["/photos/a", "/photos/b"])
    panel.folder_combo.setCurrentIndex(2)
    panel.search_field.setText("sunset")
    panel.toggle_label_filter(get_user_setting(UserSettingKey.STATUS_LABELS)[0].name)

    assert panel.apply_base_labels() is True
    criteria = panel.get_current_filter()
    assert criteria.labels == set()
    assert criteria.include_no_label is True
    assert criteria.folder == "/photos/b"
    assert criteria.search_text == "sunset"
    assert panel.apply_base_labels() is False

    set_user_setting(UserSettingKey.BASE_LABELS, "")
    assert panel.apply_base_labels() is True
    criteria = panel.get_current_filter()
    assert criteria.labels == set()
    assert criteria.include_no_label is False
    assert criteria.folder == "/photos/b"
    assert criteria.search_text == "sunset"
    assert panel.apply_base_labels() is False


def test_empty_base_labels_clear_only_label_filters(qapp):
    init_qsettings_store(dyn=True)
    panel = FilterPanel()
    panel.set_folders(["/photos/a", "/photos/b"])
    panel.folder_combo.setCurrentIndex(1)
    panel.search_field.setText("sunset")
    panel.toggle_label_filter(None)

    assert panel.apply_base_labels() is True

    criteria = panel.get_current_filter()
    assert criteria.labels == set()
    assert criteria.include_no_label is False
    assert criteria.folder == "/photos/a"
    assert criteria.search_text == "sunset"


@pytest.mark.parametrize("value", ["19", "09", "0,1"])
def test_invalid_base_labels_leave_filters_unchanged(qapp, value):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.BASE_LABELS, value)
    panel = FilterPanel()
    panel.set_folders(["/photos/a"])
    panel.toggle_label_filter(None)
    before = panel.get_current_filter()

    assert panel.apply_base_labels() is False
    assert panel.get_current_filter() == before


@pytest.mark.parametrize(
    "folders",
    [
        ["/root/one/photos", "/root/two/photos"],
        ["/root/two/photos", "/root/one/photos", "/root/new"],
        ["/root/two/photos"],
    ],
)
def test_folder_refresh_preserves_selected_folder_and_other_filters(qapp, folders):
    init_qsettings_store(dyn=True)
    panel = FilterPanel()
    panel.set_folders(["/root/one/photos", "/root/two/photos"])
    panel.folder_combo.setCurrentIndex(2)
    panel.toggle_label_filter(None)
    panel.search_field.setText("sunset")
    before = panel.get_current_filter()
    emitted_filters = []
    panel.filter_changed.connect(emitted_filters.append)

    panel.set_folders(folders)

    assert panel.folder_combo.currentData() == "/root/two/photos"
    assert panel.get_current_filter() == before
    assert panel.folder_combo.isEnabled() is (len(folders) > 1)
    assert emitted_filters == []


@pytest.mark.parametrize("folders", [["/photos/a", "/photos/c"], []])
def test_folder_refresh_resets_missing_folder_and_emits_filter(qapp, folders):
    init_qsettings_store(dyn=True)
    panel = FilterPanel()
    panel.set_folders(["/photos/a", "/photos/b"])
    panel.folder_combo.setCurrentIndex(2)
    panel.toggle_label_filter(None)
    panel.search_field.setText("sunset")
    emitted_filters = []
    panel.filter_changed.connect(emitted_filters.append)

    panel.set_folders(folders)

    criteria = panel.get_current_filter()
    assert panel.folder_combo.currentData() == ALL_FOLDERS
    assert criteria.folder is None
    assert criteria.include_no_label is True
    assert criteria.search_text == "sunset"
    assert emitted_filters == [criteria]


def test_folder_refresh_preserves_all_folders_without_emitting_filter(qapp):
    init_qsettings_store(dyn=True)
    panel = FilterPanel()
    panel.set_folders(["/photos/a", "/photos/b"])
    emitted_filters = []
    panel.filter_changed.connect(emitted_filters.append)

    panel.set_folders(["/photos/b", "/photos/c"])

    assert panel.folder_combo.currentData() == ALL_FOLDERS
    assert panel.get_current_filter().folder is None
    assert emitted_filters == []


def test_cycle_folder_filter_skips_all_folders_and_wraps(qapp):
    init_qsettings_store(dyn=True)
    panel = FilterPanel()
    folders = ["/root/tx95", "/root/xs20"]
    panel.set_folders(folders)

    assert panel.folder_combo.currentIndex() == 0
    assert panel.cycle_folder_filter(1) is True
    assert panel.folder_combo.currentData() == folders[0]
    assert panel.cycle_folder_filter(1) is True
    assert panel.folder_combo.currentData() == folders[1]
    assert panel.cycle_folder_filter(1) is True
    assert panel.folder_combo.currentData() == folders[0]

    assert panel.set_all_folders() is True
    assert panel.folder_combo.currentIndex() == 0
    assert panel.cycle_folder_filter(-1) is True
    assert panel.folder_combo.currentData() == folders[1]


def test_folder_shortcuts_no_effect_with_single_folder(qapp):
    init_qsettings_store(dyn=True)
    panel = FilterPanel()
    panel.set_folders(["/root/tx95"])

    assert panel.folder_combo.isEnabled() is False
    assert panel.cycle_folder_filter(1) is False
    assert panel.cycle_folder_filter(-1) is False
    assert panel.set_all_folders() is False


def test_focus_search_field_selects_text(qapp):
    init_qsettings_store(dyn=True)
    panel = FilterPanel()
    panel.set_folders(["/photos/a", "/photos/b"])
    panel.show()
    qapp.processEvents()

    panel.search_field.setText("abc")
    assert panel.focus_search_field(select_all=True) is True
    qapp.processEvents()
    assert panel.search_field.hasFocus() is True
    assert panel.search_field.selectedText() == "abc"


def test_search_clear_button_clears_only_search_and_applies(qapp):
    init_qsettings_store(dyn=True)
    panel = FilterPanel()
    folders = ["/photos/a", "/photos/b"]
    panel.set_folders(folders)

    label_name = get_user_setting(UserSettingKey.STATUS_LABELS)[0].name
    panel.folder_combo.setCurrentIndex(1)
    assert panel.toggle_label_filter(label_name) is True
    panel.search_field.setText("sunset")
    qapp.processEvents()

    assert panel.search_clear_button.objectName() == "filter_search_clear_button"
    assert panel.search_clear_button.isEnabled() is True

    emitted_filters = []
    finished = []
    panel.filter_changed.connect(emitted_filters.append)
    panel.interaction_finished.connect(lambda: finished.append(True))

    panel.search_clear_button.click()
    qapp.processEvents()

    assert panel.search_field.text() == ""
    assert panel.search_clear_button.isEnabled() is False

    criteria = panel.get_current_filter()
    assert criteria.folder == folders[0]
    assert criteria.labels == {label_name}
    assert criteria.search_text == ""

    assert len(emitted_filters) == 1
    emitted = emitted_filters[0]
    assert emitted.folder == folders[0]
    assert emitted.labels == {label_name}
    assert emitted.search_text == ""
    assert finished == [True]


def test_clear_filter_can_leave_single_label_active(qapp):
    init_qsettings_store(dyn=True)
    panel = FilterPanel()
    folders = ["/photos/a", "/photos/b"]
    panel.set_folders(folders)

    status_labels = get_user_setting(UserSettingKey.STATUS_LABELS)
    active_label = status_labels[0].name
    other_label = status_labels[1].name
    panel.folder_combo.setCurrentIndex(1)
    assert panel.toggle_label_filter(other_label) is True
    assert panel.toggle_label_filter(None) is True
    panel.search_field.setText("sunset")

    emitted_filters = []
    finished = []
    panel.filter_changed.connect(emitted_filters.append)
    panel.interaction_finished.connect(lambda: finished.append(True))

    panel.clear_filter(label_name=active_label)
    qapp.processEvents()

    criteria = panel.get_current_filter()
    assert criteria.folder is None
    assert criteria.labels == {active_label}
    assert criteria.include_no_label is False
    assert criteria.search_text == ""
    assert panel._label_checkboxes[active_label].isChecked() is True
    assert panel._label_checkboxes[other_label].isChecked() is False

    assert len(emitted_filters) == 1
    assert emitted_filters[0].labels == {active_label}
    assert emitted_filters[0].search_text == ""
    assert finished == [True]


def test_clear_filter_with_unknown_label_falls_back_to_full_clear(qapp):
    init_qsettings_store(dyn=True)
    panel = FilterPanel()
    folders = ["/photos/a", "/photos/b"]
    panel.set_folders(folders)

    label_name = get_user_setting(UserSettingKey.STATUS_LABELS)[0].name
    panel.folder_combo.setCurrentIndex(1)
    assert panel.toggle_label_filter(label_name) is True
    assert panel.toggle_label_filter(None) is True
    panel.search_field.setText("sunset")

    panel.clear_filter(label_name="does-not-exist")
    qapp.processEvents()

    criteria = panel.get_current_filter()
    assert criteria.folder is None
    assert criteria.labels == set()
    assert criteria.include_no_label is False
    assert criteria.search_text == ""
