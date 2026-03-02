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
