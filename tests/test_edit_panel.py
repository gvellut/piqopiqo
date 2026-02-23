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


def test_keywords_height_change_keeps_edit_panel_rows_stable(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.SHOW_DESCRIPTION_FIELD, True)

    panel = EditPanel(_DummyDBManager())
    panel.resize(420, 700)
    panel.show()
    qapp.processEvents()

    keyword_label_item = panel.layout.itemAtPosition(4, 0)
    assert keyword_label_item is not None
    keyword_label = keyword_label_item.widget()
    assert keyword_label is not None

    def snapshot() -> dict[str, int]:
        return {
            "title_y": panel.title_edit.y(),
            "description_y": panel.description_edit.y(),
            "lat_y": panel.lat_edit.y(),
            "lon_y": panel.lon_edit.y(),
            "keywords_y": panel.keywords_edit.y(),
            "keywords_h": panel.keywords_edit.height(),
            "keyword_tree_y": panel.keyword_tree_btn.y(),
            "time_y": panel.time_edit.y(),
            "keyword_label_y": keyword_label.y(),
            "keyword_label_h": keyword_label.height(),
        }

    panel.keywords_edit.set_value("")
    qapp.processEvents()
    base = snapshot()

    long_keywords = ", ".join(
        [
            "alpha",
            "beta",
            "gamma",
            "delta",
            "epsilon",
            "zeta",
            "eta",
            "theta",
            "iota",
            "kappa",
            "lambda",
            "mu",
            "nu",
            "xi",
            "omicron",
            "pi",
            "rho",
            "sigma",
            "tau",
            "upsilon",
            "phi",
            "chi",
            "psi",
            "omega",
        ]
    )

    panel.keywords_edit.set_value(long_keywords)
    qapp.processEvents()
    long_pass1 = snapshot()
    qapp.processEvents()
    long_pass2 = snapshot()
    assert long_pass1 == long_pass2
    long_state = long_pass2

    panel.keywords_edit.set_value("a")
    qapp.processEvents()
    short_pass1 = snapshot()
    qapp.processEvents()
    short_pass2 = snapshot()
    assert short_pass1 == short_pass2
    short_state = short_pass2

    assert long_state["keywords_h"] > base["keywords_h"]
    assert short_state["keywords_h"] == base["keywords_h"]

    for key in ("title_y", "description_y", "lat_y", "lon_y"):
        assert long_state[key] == base[key]
        assert short_state[key] == base[key]

    assert long_state["keywords_y"] == base["keywords_y"]
    assert short_state["keywords_y"] == base["keywords_y"]

    keyword_height_delta = long_state["keywords_h"] - base["keywords_h"]
    assert keyword_height_delta > 0
    assert long_state["keyword_tree_y"] - base["keyword_tree_y"] == keyword_height_delta
    assert long_state["time_y"] - base["time_y"] == keyword_height_delta
    assert short_state["keyword_tree_y"] == base["keyword_tree_y"]
    assert short_state["time_y"] == base["time_y"]

    assert long_state["keyword_label_y"] == base["keyword_label_y"]
    assert short_state["keyword_label_y"] == base["keyword_label_y"]
    assert long_state["keyword_label_h"] == base["keyword_label_h"]
    assert short_state["keyword_label_h"] == base["keyword_label_h"]
