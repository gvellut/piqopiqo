"""Tests for edit panel UI behaviors."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.panels.edit_panel import EditPanel
from piqopiqo.settings_state import (
    UserSettingKey,
    init_qsettings_store,
    set_user_setting,
)


class _DummyDBManager:
    pass


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-edit-panel-{uuid.uuid4().hex}")
    return app


def test_description_field_visibility_follows_user_setting(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.SHOW_DESCRIPTION_FIELD, False)

    panel = EditPanel(_DummyDBManager())

    assert panel.description_label.isHidden() is True
    assert panel.description_edit.isHidden() is True

    panel.set_description_field_visible(True)
    assert panel.description_label.isHidden() is False
    assert panel.description_edit.isHidden() is False

    panel.set_description_field_visible(False)
    assert panel.description_label.isHidden() is True
    assert panel.description_edit.isHidden() is True
