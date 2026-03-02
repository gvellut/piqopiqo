"""Tests for the column number selector component."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.components.column_number_selector import ColumnNumberSelector


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-column-selector-{uuid.uuid4().hex}")
    return app


def test_selector_updates_value_and_button_bounds(qapp):
    selector = ColumnNumberSelector()

    selector.set_value(3, 3, 10)
    assert selector.value_label.text() == "3"
    assert selector.decrement_button.isEnabled() is False
    assert selector.increment_button.isEnabled() is True

    selector.set_value(10, 3, 10)
    assert selector.value_label.text() == "10"
    assert selector.decrement_button.isEnabled() is True
    assert selector.increment_button.isEnabled() is False


def test_selector_emits_increment_decrement_signals(qapp):
    selector = ColumnNumberSelector()
    events: list[str] = []
    selector.decrement_requested.connect(lambda: events.append("dec"))
    selector.increment_requested.connect(lambda: events.append("inc"))

    selector.decrement_button.click()
    selector.increment_button.click()
    assert events == ["dec", "inc"]
