"""Tests for edit panel UI behaviors."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent, QTextCursor, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox
import pytest

from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.model import ImageItem, MapLinkOption, QgisRemoteControlSettings
from piqopiqo.panels.edit_panel import EditPanel
from piqopiqo.panels.edit_widgets import MULTIPLE_VALUES, KeywordsEdit
from piqopiqo.panels.keyword.keyword_tree import KeywordTreeManager
from piqopiqo.panels.keyword.keyword_tree_dialog import KeywordTreeDialog
from piqopiqo.ssf.settings_state import (
    UserSettingKey,
    init_qsettings_store,
    set_user_setting,
)


class _DummyDBManager:
    pass


class _StubDB:
    def has_metadata(self, _path: str) -> bool:
        return True


class _StubDBManager:
    def __init__(self) -> None:
        self.db = _StubDB()

    def get_db_for_image(self, _path: str) -> _StubDB:
        return self.db


def _wrapped_line_count(widget: KeywordsEdit) -> int:
    total = 0
    block = widget.document().begin()
    while block.isValid():
        block_layout = block.layout()
        total += max(1, block_layout.lineCount() if block_layout else 1)
        block = block.next()
    return total


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


def test_hidden_description_reappears_when_non_empty_option_is_enabled(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.SHOW_DESCRIPTION_FIELD, False)
    set_user_setting(
        UserSettingKey.SHOW_HIDDEN_METADATA_FIELDS_IF_NOT_EMPTY,
        True,
    )

    panel = EditPanel(_StubDBManager())
    empty_item = ImageItem(
        path="/tmp/empty-description.jpg",
        name="empty-description.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.DESCRIPTION: ""},
    )
    panel.update_for_selection([empty_item])

    assert panel.description_label.isHidden() is True
    assert panel.description_edit.isHidden() is True

    item = ImageItem(
        path="/tmp/description.jpg",
        name="description.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.DESCRIPTION: "Existing caption"},
    )
    panel.update_for_selection([item])

    assert panel.description_label.isHidden() is False
    assert panel.description_edit.isHidden() is False
    assert panel.description_edit.toPlainText() == "Existing caption"


def test_lens_fields_follow_hidden_non_empty_setting_and_db_value_priority(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.SHOW_HIDDEN_METADATA_FIELDS_IF_NOT_EMPTY,
        False,
    )

    panel = EditPanel(_StubDBManager())
    manual_item = ImageItem(
        path="/tmp/manual-lens.jpg",
        name="manual-lens.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.MANUAL_LENS_MAKE: "Manual Make",
            DBFields.MANUAL_LENS_MODEL: "Manual Model",
            DBFields.MANUAL_FOCAL_LENGTH: "12",
            DBFields.MANUAL_FOCAL_LENGTH_35MM: "18",
        },
        exif_data={
            "EXIF:LensMake": "EXIF Make",
            "EXIF:LensModel": "EXIF Model",
            "EXIF:FocalLength": "13",
            "EXIF:FocalLengthIn35mmFormat": "19",
        },
    )
    panel.update_for_selection([manual_item])

    assert panel.lens_make_edit.isHidden() is True
    assert panel.lens_model_edit.isHidden() is True

    panel.set_show_hidden_metadata_fields_if_not_empty(True)

    assert panel.lens_make_edit.isHidden() is False
    assert panel.lens_model_edit.isHidden() is False
    assert panel.lens_make_edit.text() == "Manual Make"
    assert panel.lens_model_edit.text() == "Manual Model"
    assert panel.focal_length_edit.text() == "12"
    assert panel.focal_length_35mm_edit.text() == "18"

    exif_only_item = ImageItem(
        path="/tmp/exif-only-lens.jpg",
        name="exif-only-lens.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={},
        exif_data={
            "EXIF:LensMake": "EXIF Make",
            "EXIF:LensModel": "EXIF Model",
            "EXIF:FocalLength": "35",
            "EXIF:FocalLengthIn35mmFormat": "50",
        },
    )
    panel.update_for_selection([exif_only_item])

    assert panel.lens_make_edit.isHidden() is True
    assert panel.lens_model_edit.isHidden() is True
    assert panel.lens_make_edit.text() == ""
    assert panel.lens_model_edit.text() == ""
    assert panel.focal_length_edit.text() == ""
    assert panel.focal_length_35mm_edit.text() == ""

    empty_item = ImageItem(
        path="/tmp/empty-lens.jpg",
        name="empty-lens.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={},
        exif_data={
            "EXIF:LensMake": None,
            "EXIF:LensModel": None,
            "EXIF:FocalLength": None,
            "EXIF:FocalLengthIn35mmFormat": None,
        },
    )
    panel.update_for_selection([empty_item])

    assert panel.lens_make_edit.isHidden() is True
    assert panel.lens_model_edit.isHidden() is True


def test_keywords_edit_keeps_hidden_scroll_position_pinned(qapp):
    edit = KeywordsEdit()
    edit.show()
    qapp.processEvents()

    keywords = "alpha, beta, gamma, delta, epsilon, zeta"
    for width in range(180, 361, 10):
        edit.resize(width, edit.height())
        qapp.processEvents()
        edit.set_value(keywords)
        qapp.processEvents()
        if _wrapped_line_count(edit) == 2:
            break
    else:
        raise AssertionError("Could not produce a two-line keyword editor layout")

    assert edit.verticalScrollBar().value() == 0

    edit.verticalScrollBar().setRange(0, 1)
    edit.verticalScrollBar().setValue(1)
    edit._adjust_height()
    assert edit.verticalScrollBar().value() == 0

    wheel_event = QWheelEvent(
        QPointF(edit.viewport().rect().center()),
        QPointF(edit.viewport().mapToGlobal(edit.viewport().rect().center())),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )
    wheel_event.setAccepted(True)

    QApplication.sendEvent(edit.viewport(), wheel_event)

    assert wheel_event.isAccepted() is False
    assert edit.verticalScrollBar().value() == 0


def test_keywords_height_change_keeps_edit_panel_rows_stable(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.SHOW_DESCRIPTION_FIELD, True)

    panel = EditPanel(_DummyDBManager())
    panel.resize(420, 700)
    panel.show()
    qapp.processEvents()

    keywords_edit_index = panel.layout.indexOf(panel.keywords_edit)
    keyword_row, _, _, _ = panel.layout.getItemPosition(keywords_edit_index)
    keyword_label_item = panel.layout.itemAtPosition(keyword_row, 0)
    assert keyword_label_item is not None
    keyword_label = keyword_label_item.widget()
    assert keyword_label is not None
    container = panel.layout.parentWidget()
    assert container is not None

    def snapshot() -> dict[str, int]:
        return {
            "title_y": panel.title_edit.mapTo(container, QPoint(0, 0)).y(),
            "description_y": panel.description_edit.mapTo(container, QPoint(0, 0)).y(),
            "lat_y": panel.lat_edit.mapTo(container, QPoint(0, 0)).y(),
            "lon_y": panel.lon_edit.mapTo(container, QPoint(0, 0)).y(),
            "keywords_y": panel.keywords_edit.mapTo(container, QPoint(0, 0)).y(),
            "keywords_h": panel.keywords_edit.height(),
            "keyword_tree_y": panel.keyword_tree_btn.mapTo(container, QPoint(0, 0)).y(),
            "time_y": panel.time_edit.mapTo(container, QPoint(0, 0)).y(),
            "keyword_label_y": keyword_label.mapTo(container, QPoint(0, 0)).y(),
            "keyword_label_h": keyword_label.height(),
        }

    panel.keywords_edit.set_value("")
    qapp.processEvents()
    base = snapshot()

    long_keywords = ", ".join([
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
    ])

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

    assert long_state["keywords_y"] == base["keywords_y"]
    assert short_state["keywords_y"] == base["keywords_y"]

    keyword_height_delta = long_state["keywords_h"] - base["keywords_h"]
    assert keyword_height_delta > 0

    for key in (
        "time_y",
        "title_y",
        "description_y",
        "keyword_tree_y",
        "lat_y",
        "lon_y",
    ):
        if base[key] < base["keywords_y"]:
            assert long_state[key] == base[key]
            assert short_state[key] == base[key]
            continue

        assert base[key] > base["keywords_y"]
        assert long_state[key] - base[key] == keyword_height_delta
        assert short_state[key] == base[key]

    assert long_state["keyword_label_y"] == base["keyword_label_y"]
    assert short_state["keyword_label_y"] == base["keyword_label_y"]
    assert long_state["keyword_label_h"] == base["keyword_label_h"]
    assert short_state["keyword_label_h"] == base["keyword_label_h"]


def test_selection_pending_disables_editors_without_clearing_fields(qapp):
    init_qsettings_store(dyn=True)

    panel = EditPanel(_StubDBManager())
    keywords = ", ".join([
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "zeta",
        "eta",
        "theta",
    ])
    initial_item = ImageItem(
        path="/tmp/initial.jpg",
        name="initial.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.TITLE: "Initial",
            DBFields.KEYWORDS: keywords,
        },
    )
    panel.resize(320, 600)
    panel.show()
    panel.update_for_selection([initial_item])
    qapp.processEvents()
    initial_height = panel.keywords_edit.height()

    panel.show_selection_pending(1234)
    qapp.processEvents()

    assert panel.reading_label.isHidden() is True
    assert panel.title_edit.text() == "Initial"
    assert panel.keywords_edit.text() == keywords
    assert panel.keywords_edit.height() == initial_height
    assert panel.title_edit.isEnabled() is False
    assert panel.keywords_edit.isEnabled() is False

    item = ImageItem(
        path="/tmp/a.jpg",
        name="a.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.TITLE: "Test"},
    )
    panel.update_for_selection([item])

    assert panel.reading_label.isHidden() is True
    assert panel.title_edit.isEnabled() is True
    assert panel.keywords_edit.isEnabled() is True


def test_pending_same_keywords_keeps_multiline_keyword_height(qapp):
    init_qsettings_store(dyn=True)

    panel = EditPanel(_StubDBManager())
    panel.resize(300, 600)
    panel.show()
    qapp.processEvents()

    keywords = ", ".join([
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
    ])
    item1 = ImageItem(
        path="/tmp/same-a.jpg",
        name="same-a.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.KEYWORDS: keywords},
    )
    item2 = ImageItem(
        path="/tmp/same-b.jpg",
        name="same-b.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.KEYWORDS: keywords},
    )
    panel.update_for_selection([item1])
    qapp.processEvents()
    initial_height = panel.keywords_edit.height()

    panel.show_selection_pending(2)
    qapp.processEvents()
    assert panel.keywords_edit.text() == keywords
    assert panel.keywords_edit.height() == initial_height

    panel.update_for_selection([item1, item2])
    qapp.processEvents()
    assert panel.keywords_edit.text() == keywords
    assert panel.keywords_edit.height() == initial_height


def test_pending_different_keywords_changes_height_only_on_final_update(qapp):
    init_qsettings_store(dyn=True)

    panel = EditPanel(_StubDBManager())
    panel.resize(300, 600)
    panel.show()
    qapp.processEvents()

    keywords = ", ".join([
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
    ])
    item1 = ImageItem(
        path="/tmp/different-a.jpg",
        name="different-a.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.KEYWORDS: keywords},
    )
    item2 = ImageItem(
        path="/tmp/different-b.jpg",
        name="different-b.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.KEYWORDS: "other"},
    )
    panel.update_for_selection([item1])
    qapp.processEvents()
    initial_height = panel.keywords_edit.height()

    panel.show_selection_pending(2)
    qapp.processEvents()
    assert panel.keywords_edit.text() == keywords
    assert panel.keywords_edit.height() == initial_height

    panel.update_for_selection([item1, item2])
    qapp.processEvents()
    assert panel.keywords_edit.text() == MULTIPLE_VALUES
    assert panel.keywords_edit.height() < initial_height


def test_non_text_protection_read_only_toggle(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.SHOW_DESCRIPTION_FIELD, True)
    set_user_setting(UserSettingKey.PROTECT_NON_TEXT_METADATA, True)

    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/protected.jpg",
        name="protected.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.TITLE: "Test"},
    )
    panel.update_for_selection([item])

    assert panel.title_edit.isReadOnly() is False
    assert panel.description_edit.isReadOnly() is False
    assert panel.keywords_edit.isReadOnly() is False
    assert panel.time_edit.isReadOnly() is True
    assert panel.lat_edit.isReadOnly() is True
    assert panel.lon_edit.isReadOnly() is True
    assert panel.time_edit.toolTip() == "Protected field. Change in Settings Panel"
    assert panel.lat_edit.toolTip() == "Protected field. Change in Settings Panel"
    assert panel.lon_edit.toolTip() == "Protected field. Change in Settings Panel"
    assert panel.title_edit.toolTip() == ""
    assert panel.description_edit.toolTip() == ""
    assert panel.keywords_edit.toolTip() == ""
    assert panel.keyword_tree_btn.isEnabled() is True

    panel.set_non_text_metadata_protection(False)

    assert panel.title_edit.isReadOnly() is False
    assert panel.description_edit.isReadOnly() is False
    assert panel.keywords_edit.isReadOnly() is False
    assert panel.time_edit.isReadOnly() is False
    assert panel.lat_edit.isReadOnly() is False
    assert panel.lon_edit.isReadOnly() is False
    assert panel.time_edit.toolTip() == ""
    assert panel.lat_edit.toolTip() == ""
    assert panel.lon_edit.toolTip() == ""
    assert panel.keyword_tree_btn.isEnabled() is True


def test_lens_fields_use_non_text_protection_and_tooltip(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.SHOW_HIDDEN_METADATA_FIELDS_IF_NOT_EMPTY,
        True,
    )
    set_user_setting(UserSettingKey.PROTECT_NON_TEXT_METADATA, True)

    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/protected-lens.jpg",
        name="protected-lens.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.MANUAL_LENS_MODEL: "Manual Model",
        },
    )
    panel.update_for_selection([item])

    assert panel.lens_model_edit.isHidden() is False
    for widget in (
        panel.lens_make_edit,
        panel.lens_model_edit,
        panel.focal_length_edit,
        panel.focal_length_35mm_edit,
    ):
        assert widget.isReadOnly() is True
        assert widget.toolTip() == "Protected field. Change in Settings Panel"

    panel.set_non_text_metadata_protection(False)

    for widget in (
        panel.lens_make_edit,
        panel.lens_model_edit,
        panel.focal_length_edit,
        panel.focal_length_35mm_edit,
    ):
        assert widget.isReadOnly() is False
        assert widget.toolTip() == ""


def test_non_text_protection_preserves_multiple_values_on_focus(qapp):
    """Protected non-text fields must keep <Multiple Values> text when clicked."""
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.PROTECT_NON_TEXT_METADATA, True)

    panel = EditPanel(_StubDBManager())
    item1 = ImageItem(
        path="/tmp/multi-a.jpg",
        name="multi-a.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.TITLE: "A",
            DBFields.LATITUDE: "1.0",
            DBFields.LONGITUDE: "2.0",
            DBFields.TIME_TAKEN: "2020-01-01 00:00:00",
        },
    )
    item2 = ImageItem(
        path="/tmp/multi-b.jpg",
        name="multi-b.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.TITLE: "B",
            DBFields.LATITUDE: "3.0",
            DBFields.LONGITUDE: "4.0",
            DBFields.TIME_TAKEN: "2020-01-02 00:00:00",
        },
    )
    panel.update_for_selection([item1, item2])

    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QFocusEvent

    focus_in = QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason)

    # Simulate clicking on each protected field
    for widget in (panel.lat_edit, panel.lon_edit, panel.time_edit):
        assert widget.isReadOnly() is True
        assert widget.text() == "<Multiple Values>"
        widget.focusInEvent(focus_in)
        assert widget.text() == "<Multiple Values>"


def test_non_text_protection_blocks_gui_save_for_locked_fields(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.PROTECT_NON_TEXT_METADATA, True)

    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/save-guard.jpg",
        name="save-guard.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.TITLE: "Before"},
    )
    panel.update_for_selection([item])

    saved_fields: list[str] = []
    emitted: list[str] = []
    monkeypatch.setattr(
        panel,
        "_save_field_for_item",
        lambda _item, field_name, _value: saved_fields.append(field_name),
    )
    panel.metadata_saved.connect(emitted.append)

    panel.lat_edit.set_value(48.8566)
    panel._on_field_saved(DBFields.LATITUDE)

    assert saved_fields == []
    assert emitted == []

    panel.title_edit.set_value("After")
    panel._on_field_saved(DBFields.TITLE)

    assert saved_fields == [DBFields.TITLE]
    assert emitted == [DBFields.TITLE]


def test_lens_field_save_writes_manual_override_when_unprotected(qapp, monkeypatch):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.SHOW_HIDDEN_METADATA_FIELDS_IF_NOT_EMPTY,
        True,
    )
    set_user_setting(UserSettingKey.PROTECT_NON_TEXT_METADATA, False)

    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/lens-save.jpg",
        name="lens-save.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.MANUAL_LENS_MODEL: "Stored Manual Model"},
        exif_data={"EXIF:LensModel": "Ignored EXIF Model"},
    )
    panel.update_for_selection([item])

    saved: list[tuple[str, str | None]] = []
    emitted: list[str] = []
    monkeypatch.setattr(
        panel,
        "_save_field_for_item",
        lambda _item, field_name, value: saved.append((field_name, value)),
    )
    panel.metadata_saved.connect(emitted.append)

    panel.lens_model_edit.setText("Manual Override")
    panel._on_field_saved(DBFields.MANUAL_LENS_MODEL)

    assert saved == [(DBFields.MANUAL_LENS_MODEL, "Manual Override")]
    assert emitted == [DBFields.MANUAL_LENS_MODEL]


def test_exif_lens_data_does_not_reveal_or_overwrite_manual_lens_rows(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.SHOW_HIDDEN_METADATA_FIELDS_IF_NOT_EMPTY,
        True,
    )

    panel = EditPanel(_StubDBManager())
    exif_only_item = ImageItem(
        path="/tmp/exif-lens-refresh.jpg",
        name="exif-lens-refresh.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.TITLE: "Before"},
        exif_data=None,
    )
    panel.update_for_selection([exif_only_item])
    assert panel.lens_model_edit.isHidden() is True
    assert panel.lens_model_edit.text() == ""

    exif_only_item.exif_data = {
        "EXIF:LensMake": "EXIF Make",
        "EXIF:LensModel": "EXIF Model",
        "EXIF:FocalLength": "35",
        "EXIF:FocalLengthIn35mmFormat": "50",
    }
    panel.update_for_selection([exif_only_item])

    assert panel.lens_make_edit.isHidden() is True
    assert panel.lens_model_edit.isHidden() is True
    assert panel.lens_make_edit.text() == ""
    assert panel.lens_model_edit.text() == ""
    assert panel.focal_length_edit.text() == ""
    assert panel.focal_length_35mm_edit.text() == ""

    manual_item = ImageItem(
        path="/tmp/manual-lens-refresh.jpg",
        name="manual-lens-refresh.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.MANUAL_LENS_MODEL: "Manual Model"},
        exif_data={"EXIF:LensModel": "Ignored EXIF Model"},
    )
    panel.update_for_selection([manual_item])

    assert panel.lens_model_edit.isHidden() is False
    assert panel.lens_model_edit.text() == "Manual Model"


@pytest.mark.parametrize(
    "temporary_reason",
    [None, Qt.FocusReason.ActiveWindowFocusReason, Qt.FocusReason.PopupFocusReason],
)
@pytest.mark.parametrize(
    ("focus_reason", "key"),
    [
        (Qt.FocusReason.MouseFocusReason, None),
        (Qt.FocusReason.TabFocusReason, None),
        (None, Qt.Key.Key_Return),
        (None, Qt.Key.Key_Enter),
    ],
    ids=["mouse", "tab", "return", "enter"],
)
def test_keywords_save_normalizes_value_and_widget_text(
    qapp, monkeypatch, temporary_reason, focus_reason, key
):
    init_qsettings_store(dyn=True)

    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/keywords-save.jpg",
        name="keywords-save.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.KEYWORDS: "old"},
    )
    panel.update_for_selection([item])

    saved: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        panel,
        "_save_field_for_item",
        lambda _item, field_name, value: saved.append((field_name, value)),
    )

    panel.keywords_edit.setPlainText("alpha,, beta, , ALPHA")
    if temporary_reason is not None:
        panel.keywords_edit.focusOutEvent(
            QFocusEvent(QEvent.Type.FocusOut, temporary_reason)
        )
        assert saved == []
        panel.keywords_edit.focusInEvent(
            QFocusEvent(QEvent.Type.FocusIn, temporary_reason)
        )

    if focus_reason is not None:
        panel.keywords_edit.focusOutEvent(
            QFocusEvent(QEvent.Type.FocusOut, focus_reason)
        )
    else:
        panel.keywords_edit.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
        )

    assert saved == [(DBFields.KEYWORDS, "alpha, beta")]
    assert panel.keywords_edit.text() == "alpha, beta"
    assert panel.keywords_edit._original_value == "alpha, beta"


@pytest.mark.parametrize(
    "temporary_reason",
    [Qt.FocusReason.ActiveWindowFocusReason, Qt.FocusReason.PopupFocusReason],
)
@pytest.mark.parametrize(
    ("anchor", "position", "pasted_text", "expected_text"),
    [
        (7, 7, "gamma, ", "alpha, gamma, beta, "),
        (13, 13, "gamma", "alpha, beta, gamma"),
        (11, 7, "gamma", "alpha, gamma, "),
    ],
    ids=["middle", "trailing-separator", "selection"],
)
def test_keywords_temporary_focus_loss_preserves_edit_and_paste(
    qapp, monkeypatch, temporary_reason, anchor, position, pasted_text, expected_text
):
    init_qsettings_store(dyn=True)

    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/keywords-paste.jpg",
        name="keywords-paste.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.KEYWORDS: "alpha, beta"},
    )
    panel.update_for_selection([item])

    saved: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        panel,
        "_save_field_for_item",
        lambda _item, field_name, value: saved.append((field_name, value)),
    )

    edit = panel.keywords_edit
    cursor = edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    edit.setTextCursor(cursor)
    edit.insertPlainText(", ")
    cursor = edit.textCursor()
    cursor.setPosition(anchor)
    cursor.setPosition(position, QTextCursor.MoveMode.KeepAnchor)
    edit.setTextCursor(cursor)

    edit.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut, temporary_reason))
    edit.focusInEvent(QFocusEvent(QEvent.Type.FocusIn, temporary_reason))

    assert saved == []
    assert edit.text() == "alpha, beta, "
    assert edit._original_value == "alpha, beta"
    assert edit.document().isModified()
    assert edit.textCursor().anchor() == anchor
    assert edit.textCursor().position() == position

    source = QMimeData()
    source.setText(pasted_text)
    edit.insertFromMimeData(source)

    assert edit.text() == expected_text
    assert edit.textCursor().position() == min(anchor, position) + len(pasted_text)
    assert saved == []


def test_keyword_tree_modifications_normalize_existing_keywords(qapp, monkeypatch):
    init_qsettings_store(dyn=True)

    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/keyword-tree-save.jpg",
        name="keyword-tree-save.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.KEYWORDS: "alpha,, beta, , ALPHA, Gamma"},
    )
    panel.update_for_selection([item])

    saved: list[tuple[str, str | None]] = []

    def _save_field_for_item(
        save_item: ImageItem, field_name: str, value: str | None
    ) -> None:
        saved.append((field_name, value))
        save_item.db_metadata = dict(save_item.db_metadata or {})
        save_item.db_metadata[field_name] = value

    monkeypatch.setattr(panel, "_save_field_for_item", _save_field_for_item)

    panel._apply_keyword_modifications({
        "BETA": False,
        "delta": True,
        "gamma": True,
    })

    assert saved == [(DBFields.KEYWORDS, "alpha, Gamma, delta")]
    assert item.db_metadata[DBFields.KEYWORDS] == "alpha, Gamma, delta"
    assert panel.keywords_edit.text() == "alpha, Gamma, delta"


def test_add_keyword_targets_selected_occurrence(qapp, monkeypatch, tmp_path):
    init_qsettings_store(dyn=True)
    manager = KeywordTreeManager()
    manager.reset()
    tree_path = tmp_path / "keyword-tree.json"
    monkeypatch.setattr(manager, "get_tree_path", lambda: tree_path)

    events = manager.root.add_child("Events")
    events.add_child("Picnic")
    first_parent = events.add_child("Summer")
    selected_parent = manager.root.add_child("Seasons").add_child("Summer")

    dialog = KeywordTreeDialog([], manager)
    parent_item = dialog.tree.topLevelItem(0).child(1).child(0)
    dialog._add_keyword(parent_item)
    editor = dialog.tree.itemWidget(parent_item.child(0), 0)
    assert isinstance(editor, QLineEdit)
    editor.setText("Picnic")
    QTest.keyClick(editor, Qt.Key.Key_Return)

    assert [child.name for child in selected_parent.children] == ["Picnic"]
    assert first_parent.children == []
    current_item = dialog.tree.currentItem()
    assert current_item.text(0) == "Picnic"
    assert current_item.parent().text(0) == "Summer"
    assert current_item.parent().parent().text(0) == "Seasons"


def test_delete_keyword_targets_selected_occurrence(qapp, monkeypatch, tmp_path):
    init_qsettings_store(dyn=True)
    manager = KeywordTreeManager()
    manager.reset()
    tree_path = tmp_path / "keyword-tree.json"
    monkeypatch.setattr(manager, "get_tree_path", lambda: tree_path)

    first_parent = manager.root.add_child("Events").add_child("Summer")
    first_picnic = first_parent.add_child("Picnic")
    selected_parent = manager.root.add_child("Seasons").add_child("Summer")
    sibling = selected_parent.add_child("Picnic")
    target = selected_parent.add_child("Picnic")
    sibling.add_child("Blanket")
    target.add_child("Blanket")

    dialog = KeywordTreeDialog([], manager)
    parent_item = dialog.tree.topLevelItem(0).child(1).child(0)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes
    )
    dialog._delete_keyword(parent_item.child(1))

    assert first_parent.children == [first_picnic]
    assert len(selected_parent.children) == 1
    assert selected_parent.children[0] is sibling


def test_title_refresh_with_same_saved_value_preserves_cursor_position(qapp):
    init_qsettings_store(dyn=True)

    panel = EditPanel(_StubDBManager())
    panel.show()
    item = ImageItem(
        path="/tmp/cursor-title.jpg",
        name="cursor-title.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.TITLE: "Before"},
    )
    panel.update_for_selection([item])
    qapp.processEvents()

    panel.title_edit.setFocus()
    panel.title_edit.setText("Edited title")
    panel.title_edit.setCursorPosition(3)

    item.db_metadata[DBFields.TITLE] = "Edited title"
    panel.update_for_selection([item])

    assert panel.title_edit.text() == "Edited title"
    assert panel.title_edit.cursorPosition() == 3
    assert panel.title_edit._original_value == "Edited title"


def test_description_refresh_with_same_saved_value_preserves_cursor_position(qapp):
    init_qsettings_store(dyn=True)

    panel = EditPanel(_StubDBManager())
    panel.show()
    item = ImageItem(
        path="/tmp/cursor-description.jpg",
        name="cursor-description.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={DBFields.DESCRIPTION: "Before"},
    )
    panel.update_for_selection([item])
    qapp.processEvents()

    panel.description_edit.setFocus()
    panel.description_edit.setPlainText("Edited description")
    cursor = panel.description_edit.textCursor()
    cursor.setPosition(4)
    panel.description_edit.setTextCursor(cursor)

    item.db_metadata[DBFields.DESCRIPTION] = "Edited description"
    panel.update_for_selection([item])

    assert panel.description_edit.toPlainText() == "Edited description"
    assert panel.description_edit.textCursor().position() == 4
    assert panel.description_edit._original_value == "Edited description"


def test_map_button_hidden_when_no_options_are_configured(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.MAP_LINKS, [])

    panel = EditPanel(_StubDBManager())

    assert panel.map_btn.isHidden() is True


def test_map_button_state_follows_selection_and_coordinate_validity(qapp):
    init_qsettings_store(dyn=True)
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

    panel = EditPanel(_StubDBManager())
    assert panel.map_btn.isHidden() is False
    assert panel.map_btn.isEnabled() is False

    item = ImageItem(
        path="/tmp/map.jpg",
        name="map.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.LATITUDE: "48.8566",
            DBFields.LONGITUDE: "2.3522",
        },
    )
    panel.update_for_selection([item])
    assert panel.map_btn.isEnabled() is True

    panel.lon_edit.setText("")
    assert panel.map_btn.isEnabled() is False

    panel.lon_edit.setText("invalid")
    assert panel.map_btn.isEnabled() is False

    panel.lon_edit.setText("2.3522")
    assert panel.map_btn.isEnabled() is True

    panel.show_selection_pending(2)
    assert panel.map_btn.isEnabled() is False

    item2 = ImageItem(
        path="/tmp/map-2.jpg",
        name="map-2.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.LATITUDE: "50.0000",
            DBFields.LONGITUDE: "10.0000",
        },
    )
    panel.update_for_selection([item, item2])
    assert panel.lat_edit.text() == MULTIPLE_VALUES
    assert panel.lon_edit.text() == MULTIPLE_VALUES
    assert panel.map_btn.isEnabled() is False


def test_map_button_sits_below_longitude_and_keeps_fields_aligned(qapp):
    init_qsettings_store(dyn=True)
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

    panel = EditPanel(_StubDBManager())
    panel.resize(420, 700)
    item = ImageItem(
        path="/tmp/map-layout.jpg",
        name="map-layout.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.LATITUDE: "48.8566",
            DBFields.LONGITUDE: "2.3522",
        },
    )
    panel.update_for_selection([item])
    panel.show()
    qapp.processEvents()

    container = panel.layout.parentWidget()
    assert container is not None

    keywords_pos = panel.keywords_edit.mapTo(container, QPoint(0, 0))
    keyword_btn_pos = panel.keyword_tree_btn.mapTo(container, QPoint(0, 0))
    lat_pos = panel.lat_edit.mapTo(container, QPoint(0, 0))
    lon_pos = panel.lon_edit.mapTo(container, QPoint(0, 0))
    map_btn_pos = panel.map_btn.mapTo(container, QPoint(0, 0))

    assert panel.map_btn.isVisible() is True
    assert keyword_btn_pos.x() == lon_pos.x()
    assert lat_pos.x() == lon_pos.x()
    assert map_btn_pos.x() == lon_pos.x()
    assert panel.lat_edit.width() == panel.lon_edit.width()
    assert panel.lat_edit.height() == panel.lat_edit.sizeHint().height()
    assert panel.lon_edit.height() == panel.lon_edit.sizeHint().height()
    assert panel.keyword_tree_btn.height() == panel.keyword_tree_btn.sizeHint().height()
    assert panel.map_btn.height() == panel.map_btn.sizeHint().height()
    assert (
        keyword_btn_pos.y() - (keywords_pos.y() + panel.keywords_edit.height())
        == panel.layout.spacing()
    )
    assert (
        lat_pos.y() - (keyword_btn_pos.y() + panel.keyword_tree_btn.height())
        == panel.layout.spacing()
    )
    assert (
        lon_pos.y() - (lat_pos.y() + panel.lat_edit.height()) == panel.layout.spacing()
    )
    assert (
        map_btn_pos.y() - (lon_pos.y() + panel.lon_edit.height())
        == panel.layout.spacing()
    )


def test_map_button_opens_single_option_directly(monkeypatch, qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.MAP_LINKS,
        [
            MapLinkOption(
                name="OpenStreetMap",
                url_template="https://www.openstreetmap.org/#map=15/{lat}/{lon}",
            )
        ],
    )

    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/map.jpg",
        name="map.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.LATITUDE: "48.8566",
            DBFields.LONGITUDE: "2.3522",
        },
    )
    panel.update_for_selection([item])

    opened_urls: list[str] = []
    monkeypatch.setattr(
        "piqopiqo.panels.edit_panel.webbrowser.open_new_tab",
        lambda url: opened_urls.append(url) or True,
    )

    panel._on_open_map()

    assert opened_urls == ["https://www.openstreetmap.org/#map=15/48.8566/2.3522"]


def test_map_button_builds_menu_for_multiple_options(monkeypatch, qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.MAP_LINKS,
        [
            MapLinkOption(
                name="Google Maps",
                url_template=(
                    "https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                ),
            ),
            MapLinkOption(
                name="OpenStreetMap",
                url_template="https://www.openstreetmap.org/#map=15/{lat}/{lon}",
            ),
        ],
    )

    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/map.jpg",
        name="map.jpg",
        created="2020-01-01 00:00:00",
        source_folder="/tmp",
        db_metadata={
            DBFields.LATITUDE: "48.8566",
            DBFields.LONGITUDE: "2.3522",
        },
    )
    panel.update_for_selection([item])

    opened_urls: list[str] = []
    monkeypatch.setattr(
        "piqopiqo.panels.edit_panel.webbrowser.open_new_tab",
        lambda url: opened_urls.append(url) or True,
    )

    panel._on_open_map()

    assert panel._map_menu is not None
    assert [action.text() for action in panel._map_menu.actions()] == [
        "Google Maps",
        "OpenStreetMap",
    ]

    panel._map_menu.actions()[1].trigger()

    assert opened_urls == ["https://www.openstreetmap.org/#map=15/48.8566/2.3522"]


@pytest.mark.parametrize("include_http", [False, True])
def test_map_button_opens_qgis_only_for_single_photo_with_gps(
    include_http,
    monkeypatch,
    qapp,
):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.QGIS_REMOTE_CONTROL, QgisRemoteControlSettings(enabled=True)
    )
    if include_http:
        set_user_setting(
            UserSettingKey.MAP_LINKS,
            [
                MapLinkOption("HTTP Map", "https://example.com/{lat}/{lon}"),
            ],
        )
    monkeypatch.setattr("piqopiqo.panels.edit_panel.QMenu.popup", lambda *_args: None)
    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/Paris/DSCF1234.JPG", name="DSCF1234.JPG", created="", db_metadata={}
    )
    another = ImageItem(path="/tmp/Paris/DSCF1235.JPG", name="DSCF1235.JPG", created="")
    requested: list[str] = []
    panel.qgis_map_requested.connect(requested.append)

    assert not panel.map_btn.isHidden()
    panel.update_for_selection([item])
    assert not panel.map_btn.isEnabled()
    item.db_metadata = {DBFields.LATITUDE: "48", DBFields.LONGITUDE: "2"}
    another.db_metadata = item.db_metadata.copy()
    panel.update_for_selection([item, another])
    assert not panel.map_btn.isEnabled()
    panel.update_for_selection([item])
    assert panel.map_btn.isEnabled()

    panel.map_btn.click()
    if include_http:
        assert not requested
        actions = panel._map_menu.actions()
        assert [action.text() for action in actions] == [
            "HTTP Map",
            "QGIS Remote Control",
        ]
        actions[-1].trigger()
    else:
        assert panel._map_menu is None
    assert requested == [item.path]


def test_qgis_map_error_elides_and_clears_with_selection(qapp):
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.QGIS_REMOTE_CONTROL, QgisRemoteControlSettings(enabled=True)
    )
    panel = EditPanel(_StubDBManager())
    item = ImageItem(
        path="/tmp/first.JPG",
        name="first.JPG",
        created="",
        db_metadata={DBFields.LATITUDE: "48", DBFields.LONGITUDE: "2"},
    )
    panel.update_for_selection([item])
    panel.resize(300, 450)
    panel.show()

    message = "Cannot connect to QGIS Remote Control"
    panel.start_qgis_map_request()
    panel.finish_qgis_map_request(message)
    qapp.processEvents()

    label = panel.qgis_map_error_label
    assert label.isVisible()
    assert label.x() >= panel.map_btn.geometry().right()
    assert label.text().endswith("…")
    assert label.toolTip() == message

    panel.resize(700, 450)
    qapp.processEvents()
    assert label.text() == message
    panel.update_for_selection([item])
    assert label.isVisible()

    panel.start_qgis_map_request()
    panel.update_for_selection([])
    panel.finish_qgis_map_request(message)
    assert label.isHidden()
    panel.close()
