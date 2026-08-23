"""Menu placement tests for editing and Flickr tools."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMainWindow
import pytest

from piqopiqo.main_window import MainWindow


class _MenuOnlyWindow(QMainWindow):
    def __getattr__(self, name: str):
        if name.startswith(("_on_", "on_", "_refresh_", "_initialize_")):
            return lambda *_args, **_kwargs: None
        raise AttributeError(name)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app
    app.closeAllWindows()
    app.processEvents()


def test_edit_and_flickr_tool_menu_order(qapp) -> None:  # noqa: ARG001
    window = _MenuOnlyWindow()
    MainWindow._create_menu_bar(window)

    menu_actions = list(window.menuBar().actions())
    menus = [action.text() for action in menu_actions]
    assert menus == ["File", "Edit", "Image", "View", "Tools", "Flickr", "Help"]

    edit_menu = menu_actions[1].menu()
    assert edit_menu is not None
    edit_labels = [
        action.text() for action in edit_menu.actions() if not action.isSeparator()
    ]
    assert edit_labels[-2:] == ["Reload EXIF", "Find && Replace..."]

    flickr_menu = menu_actions[5].menu()
    assert flickr_menu is not None
    flickr_actions = flickr_menu.actions()
    assert flickr_actions[0].text() == "Upload to Flickr..."
    assert flickr_actions[1].isSeparator()
    assert [action.text() for action in flickr_actions[2:]] == [
        "Reorder Albums...",
        "Find && Replace...",
    ]
