"""Tests for FilterPanel shortcut action helpers."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.panels.filter_panel import FilterPanel
from piqopiqo.ssf.settings_state import (
    UserSettingKey,
    get_user_setting,
    init_qsettings_store,
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
