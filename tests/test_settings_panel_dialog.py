"""Behavioral tests for settings dialog save modes."""

from __future__ import annotations

from copy import replace
import uuid

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QWidget,
)
import pytest

from piqopiqo.color_management import ScreenColorProfileMode
from piqopiqo.main_window import MainWindow
from piqopiqo.model import LabelTransitionRule, StatusLabel
from piqopiqo.settings_panel import label_transitions_editor as lte
from piqopiqo.settings_panel.dialog import (
    SettingsDialog,
    _native_group_box_background_color,
)
from piqopiqo.ssf import settings_state
from piqopiqo.ssf.settings_state import (
    MandatorySettingInputKind,
    MandatorySettingSpec,
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

    # Ensure QSettings identity exists for the dialog-backed store.
    core = QCoreApplication.instance()
    core.setOrganizationName("PiqoPiqoTests")
    core.setOrganizationDomain("tests.local")
    core.setApplicationName(f"piqopiqo-test-dialog-{uuid.uuid4().hex}")
    return app


def test_save_cancel_mode_tracks_dirty_state(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog()
    editor = dialog._editors[UserSettingKey.EXTERNAL_EDITOR]
    editor.set_value("EditorX")
    dialog._on_field_changed(UserSettingKey.EXTERNAL_EDITOR)

    assert dialog._dirty is True


def test_autosave_mode_commits_on_field_update(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("PIQO_SETTINGS_PANEL_SAVE_MODE", "autosave")
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog()
    app_path = tmp_path / "Viewer.app"
    app_path.mkdir()
    editor = dialog._editors[UserSettingKey.EXTERNAL_VIEWER]
    editor.set_value(str(app_path))
    dialog._autosave_field(UserSettingKey.EXTERNAL_VIEWER)

    assert get_user_setting(UserSettingKey.EXTERNAL_VIEWER) == str(app_path)
    assert UserSettingKey.EXTERNAL_VIEWER in dialog.changed_keys


def test_initial_tab_title_selects_requested_tab(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="External/Tools")

    assert dialog._tabs is not None
    current_title = dialog._tabs.tabText(dialog._tabs.currentIndex())
    assert current_title == "External/Tools"


def test_open_settings_for_key_uses_schema_tab_title():
    class _WindowStub:
        def __init__(self) -> None:
            self.calls: list[str | None] = []

        def open_settings(self, tab_title: str | None = None) -> None:
            self.calls.append(tab_title)

    window = _WindowStub()

    MainWindow.open_settings_for_key(window, UserSettingKey.FLICKR_API_SECRET)

    assert window.calls == ["External/Tools"]


def _settings_layout_rows(layout: QGridLayout) -> list[tuple[QLabel, object]]:
    rows: list[tuple[QLabel, object]] = []
    for row in range(layout.rowCount()):
        label_item = layout.itemAtPosition(row, 0)
        field_item = layout.itemAtPosition(row, 1)
        if label_item is None and field_item is None:
            continue
        assert label_item is not None
        assert field_item is not None
        label = label_item.widget()
        field = field_item.widget()
        assert isinstance(label, QLabel)
        assert field is not None
        rows.append((label, field))
    return rows


def _settings_layout_label_center_deltas(layout: QGridLayout) -> list[int]:
    deltas: list[int] = []
    previous_center: int | None = None
    for label, _field in _settings_layout_rows(layout):
        geometry = label.geometry()
        center = geometry.y() + geometry.height() // 2
        if previous_center is not None:
            deltas.append(center - previous_center)
        previous_center = center
    return deltas


def _section_panel(dialog: SettingsDialog, title: str) -> QGroupBox:
    panel = next(
        group
        for group in dialog.findChildren(QGroupBox)
        if group.property("settingsPanelSectionTitle") == title
    )
    assert panel.title() == ""
    return panel


def _section_layout(dialog: SettingsDialog, title: str) -> QGridLayout:
    layout = _section_panel(dialog, title).layout()
    assert isinstance(layout, QGridLayout)
    return layout


def _section_widgets(dialog: SettingsDialog) -> list[QWidget]:
    assert dialog._tabs is not None
    scroll = dialog._tabs.currentWidget()
    assert isinstance(scroll, QScrollArea)
    content = scroll.widget()
    assert content is not None
    layout = content.layout()
    widgets: list[QWidget] = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        widget = item.widget()
        if widget is None:
            continue
        if widget.property("settingsPanelSectionTitle"):
            widgets.append(widget)
    return widgets


def test_autosave_choice_enum_setting_roundtrip(qapp, monkeypatch):
    monkeypatch.setenv("PIQO_SETTINGS_PANEL_SAVE_MODE", "autosave")
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="Interface")
    editor = dialog._editors[UserSettingKey.SCREEN_COLOR_PROFILE]
    editor.set_value(ScreenColorProfileMode.BT2020)
    dialog._autosave_field(UserSettingKey.SCREEN_COLOR_PROFILE)

    assert (
        get_user_setting(UserSettingKey.SCREEN_COLOR_PROFILE)
        == ScreenColorProfileMode.BT2020
    )
    assert UserSettingKey.SCREEN_COLOR_PROFILE in dialog.changed_keys


def test_settings_dialog_builds_favorite_folder_editor(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="Interface")

    assert UserSettingKey.FAVORITE_FOLDER in dialog._editors


def test_settings_dialog_uses_unsaved_status_labels_for_transition_validation(
    qapp,  # noqa: ARG001
    monkeypatch,
):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.STATUS_LABELS,
        [
            StatusLabel("Approved", "#ff0000", 1),
            StatusLabel("Uploaded", "#00ff00", 2),
        ],
    )
    set_user_setting(
        UserSettingKey.FLICKR_UPLOAD_LABEL_TRANSITIONS,
        [LabelTransitionRule("Approved", "Uploaded")],
    )

    dialog = SettingsDialog(initial_tab_title="External/Tools")
    labels_editor = dialog._editors[UserSettingKey.STATUS_LABELS]
    transitions_editor = dialog._editors[
        UserSettingKey.FLICKR_UPLOAD_LABEL_TRANSITIONS
    ]

    labels_editor.set_value([StatusLabel("Approved", "#ff0000", 1)])
    dialog._on_field_changed(UserSettingKey.STATUS_LABELS)

    assert transitions_editor.is_valid() is False
    assert dialog._save_btn.isEnabled() is False


def test_settings_dialog_passes_unsaved_labels_to_transition_dialog(
    qapp,  # noqa: ARG001
    monkeypatch,
):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)
    set_user_setting(
        UserSettingKey.STATUS_LABELS,
        [StatusLabel("Approved", "#ff0000", 1)],
    )

    dialog = SettingsDialog(initial_tab_title="External/Tools")
    labels_editor = dialog._editors[UserSettingKey.STATUS_LABELS]
    labels_editor.set_value(
        [
            StatusLabel("Approved", "#ff0000", 1),
            StatusLabel("Unsaved", "#123456", 2),
        ]
    )
    dialog._on_field_changed(UserSettingKey.STATUS_LABELS)

    captured: dict[str, list[StatusLabel]] = {}

    class _DialogStub:
        def __init__(self, _rules, *, status_labels, parent=None):  # noqa: ARG002
            captured["status_labels"] = list(status_labels)

        def exec(self):
            return QDialog.DialogCode.Rejected

        def get_value(self):
            return []

    monkeypatch.setattr(lte, "_LabelTransitionsDialog", _DialogStub)

    transitions_editor = dialog._editors[
        UserSettingKey.FLICKR_UPLOAD_LABEL_TRANSITIONS
    ]
    transitions_editor._editor._on_edit()

    assert [label.name for label in captured["status_labels"]] == [
        "Approved",
        "Unsaved",
    ]


def test_settings_dialog_keeps_form_labels_vertically_centered(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="Interface")
    dialog.show()
    qapp.processEvents()
    layout = _section_layout(dialog, "Metadata Panel")
    for label_widget, field_widget in _settings_layout_rows(layout):
        assert label_widget.alignment() & Qt.AlignmentFlag.AlignVCenter
        label_center = label_widget.geometry().center().y()
        field_center = field_widget.geometry().center().y()
        assert abs(label_center - field_center) <= 1


def test_settings_dialog_wraps_each_tab_in_scroll_area(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="Interface")

    assert dialog._tabs is not None
    for i in range(dialog._tabs.count()):
        tab = dialog._tabs.widget(i)
        assert isinstance(tab, QScrollArea)
        assert tab.frameShape() == QFrame.Shape.NoFrame
        assert tab.widgetResizable() is True
        assert tab.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        assert tab.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert tab.viewport().autoFillBackground()
        page_background = _native_group_box_background_color(dialog)
        assert tab.viewport().palette().color(tab.viewport().backgroundRole()) == (
            page_background
        )
        assert tab.widget() is not None
        assert tab.widget().autoFillBackground()
        assert tab.widget().palette().color(tab.widget().backgroundRole()) == (
            page_background
        )
        margins = tab.widget().layout().contentsMargins()
        assert margins.top() == 0
        assert margins.left() > 0
        assert margins.right() > 0


def test_settings_dialog_uses_runtime_row_spacing(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    monkeypatch.setenv("PIQO_SETTINGS_PANEL_ROW_SPACING", "0")
    init_qsettings_store(dyn=True)

    zero_spacing_dialog = SettingsDialog(initial_tab_title="Interface")
    zero_spacing_dialog.show()
    qapp.processEvents()
    zero_spacing_layout = _section_layout(zero_spacing_dialog, "Metadata Panel")
    zero_spacing_deltas = _settings_layout_label_center_deltas(zero_spacing_layout)

    monkeypatch.setenv("PIQO_SETTINGS_PANEL_ROW_SPACING", "2")
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="Interface")
    dialog.show()
    qapp.processEvents()
    layout = _section_layout(dialog, "Metadata Panel")
    deltas = _settings_layout_label_center_deltas(layout)

    assert layout.property("settingsPanelRowSpacing") == 2
    assert deltas == [deltas[0]] * len(deltas)
    assert deltas[0] == zero_spacing_deltas[0] + 2


def test_settings_dialog_clamps_negative_runtime_row_spacing(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    monkeypatch.setenv("PIQO_SETTINGS_PANEL_ROW_SPACING", "-4")
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="Interface")
    dialog.show()
    qapp.processEvents()
    layout = _section_layout(dialog, "Metadata Panel")
    deltas = _settings_layout_label_center_deltas(layout)

    assert layout.property("settingsPanelRowSpacing") == 0
    assert deltas == [deltas[0]] * len(deltas)


def test_settings_dialog_harmonizes_dense_row_spacing_across_sections(
    qapp, monkeypatch
):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="External/Tools")
    dialog.show()
    qapp.processEvents()

    gpx_deltas = _settings_layout_label_center_deltas(_section_layout(dialog, "GPX"))
    flickr_deltas = _settings_layout_label_center_deltas(
        _section_layout(dialog, "Flickr")
    )

    assert gpx_deltas
    assert flickr_deltas
    assert gpx_deltas == [gpx_deltas[0]] * len(gpx_deltas)
    assert flickr_deltas == [gpx_deltas[0]] * len(flickr_deltas)


def test_settings_dialog_keeps_simple_rows_at_natural_height(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="Interface")
    dialog.show()
    qapp.processEvents()

    button_height = QPushButton("Edit...").sizeHint().height()
    map_links_editor = dialog._editors[UserSettingKey.MAP_LINKS]
    edit_btn = next(
        button
        for button in map_links_editor.findChildren(QPushButton)
        if button.text() == "Edit..."
    )
    summary_label = next(
        label
        for label in map_links_editor.findChildren(QLabel)
        if "options defined" in label.text()
    )
    summary_top = summary_label.mapTo(
        map_links_editor, summary_label.rect().topLeft()
    ).y()

    assert dialog._editors[UserSettingKey.SHOW_DESCRIPTION_FIELD].minimumHeight() < (
        button_height
    )
    assert dialog._editors[UserSettingKey.MAP_LINKS].minimumHeight() < button_height
    assert edit_btn.styleSheet() == ""
    assert edit_btn.testAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect)
    assert summary_top == 0
    assert summary_label.alignment() & Qt.AlignmentFlag.AlignVCenter


def test_settings_dialog_scroll_area_preserves_manual_lens_minimums(
    qapp, monkeypatch
):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="External/Tools")
    dialog.show()
    qapp.processEvents()

    manual_editor = dialog._editors[UserSettingKey.MANUAL_LENSES]
    lens_list = manual_editor.findChild(QListWidget)
    buttons = [
        button
        for button in manual_editor.findChildren(QPushButton)
        if button.text() in {"Add", "Edit", "Delete"}
    ]
    external_tools_scroll = dialog._tabs.currentWidget()

    assert isinstance(external_tools_scroll, QScrollArea)
    assert external_tools_scroll.verticalScrollBar().maximum() > 0
    assert lens_list is not None
    assert lens_list.height() >= lens_list.minimumSizeHint().height()
    assert buttons
    assert all(
        button.height() >= button.minimumSizeHint().height() for button in buttons
    )


def test_settings_dialog_section_titles_stay_outside_field_panels(
    qapp, monkeypatch
):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="External/Tools")
    dialog.show()
    qapp.processEvents()

    sections = _section_widgets(dialog)
    assert sections
    for section in sections:
        title = section.property("settingsPanelSectionTitle")
        title_labels = [
            label
            for label in section.findChildren(QLabel)
            if label.parent() is section
            and label.property("settingsPanelSectionTitle") == title
        ]
        assert len(title_labels) == 1
        panel = next(
            group
            for group in section.findChildren(QGroupBox)
            if group.parent() is section
            and group.property("settingsPanelSectionTitle") == title
        )
        assert title_labels[0].geometry().bottom() <= panel.geometry().top()


def test_settings_dialog_section_panels_are_inset_from_scroll_area(
    qapp, monkeypatch
):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="External/Tools")
    dialog.show()
    qapp.processEvents()

    assert dialog._tabs is not None
    scroll = dialog._tabs.currentWidget()
    assert isinstance(scroll, QScrollArea)
    viewport_width = scroll.viewport().width()

    for section in _section_widgets(dialog):
        section_geometry = section.geometry()
        assert section_geometry.left() > 0
        assert section_geometry.right() < viewport_width - 1


def test_settings_dialog_section_gaps_are_consistent(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="External/Tools")
    dialog.show()
    qapp.processEvents()

    gaps: list[int] = []
    previous_bottom: int | None = None
    for section in _section_widgets(dialog):
        title = section.property("settingsPanelSectionTitle")
        title_label = next(
            label
            for label in section.findChildren(QLabel)
            if label.parent() is section
            and label.property("settingsPanelSectionTitle") == title
        )
        panel = next(
            group
            for group in section.findChildren(QGroupBox)
            if group.parent() is section
            and group.property("settingsPanelSectionTitle") == title
        )
        title_to_panel_gap = panel.geometry().top() - title_label.geometry().bottom()
        if previous_bottom is not None:
            previous_panel_to_title_gap = section.geometry().top() - previous_bottom
            assert previous_panel_to_title_gap == title_to_panel_gap
            gaps.append(previous_panel_to_title_gap)
        previous_bottom = section.geometry().bottom()

    assert len(gaps) > 1
    assert gaps == [gaps[0]] * len(gaps)


def test_settings_dialog_top_aligns_multiline_field_labels(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="External/Tools")
    dialog.show()
    qapp.processEvents()

    copy_sd_layout = _section_layout(dialog, "Copy SD")
    manual_lens_layout = _section_layout(dialog, "Manual Lens")

    for layout, expected_label in (
        (copy_sd_layout, "SD Card Names"),
        (manual_lens_layout, "Lens presets"),
    ):
        label, field = next(
            (row_label, row_field)
            for row_label, row_field in _settings_layout_rows(layout)
            if row_label.text() == expected_label
        )
        assert label.alignment() & Qt.AlignmentFlag.AlignTop
        assert label.geometry().top() == field.geometry().top()


def test_settings_dialog_shows_gcp_fields_in_gcp_mode(qapp, monkeypatch):
    monkeypatch.setenv("PIQO_OCR_TIME_SHIFT_PROVIDER", "GCP_VISION")
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="External/Tools")

    assert UserSettingKey.GCP_SA_KEY_PATH in dialog._editors
    assert UserSettingKey.GCP_PROJECT in dialog._editors


def test_settings_dialog_hides_gcp_fields_in_apple_mode(qapp, monkeypatch):
    monkeypatch.setenv("PIQO_OCR_TIME_SHIFT_PROVIDER", "APPLE_VISION")
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="External/Tools")

    assert UserSettingKey.GCP_SA_KEY_PATH not in dialog._editors
    assert UserSettingKey.GCP_PROJECT not in dialog._editors


def test_save_shows_inline_auto_hint_for_invalid_mandatory_field(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="Core")
    editor = dialog._editors[UserSettingKey.EXIFTOOL_PATH]
    editor.set_value("/invalid/exiftool")
    dialog._on_field_changed(UserSettingKey.EXIFTOOL_PATH)

    auto_spec = MandatorySettingSpec(
        key=UserSettingKey.EXIFTOOL_PATH,
        label="Exiftool Path",
        input_kind=MandatorySettingInputKind.EXECUTABLE_PATH,
        can_create=False,
        validator=lambda value: value == "/valid/exiftool",
        default_resolver=lambda: "/auto/exiftool",
    )
    monkeypatch.setattr(
        "piqopiqo.settings_panel.dialog.get_mandatory_setting_spec",
        lambda key: auto_spec if key == UserSettingKey.EXIFTOOL_PATH else None,
    )
    monkeypatch.setattr(
        "piqopiqo.settings_panel.dialog.validate_mandatory_setting_value",
        lambda spec, value: spec.validator(str(value).strip()),
    )
    warning_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "piqopiqo.settings_panel.dialog.QMessageBox.warning",
        lambda _parent, title, text: warning_calls.append((title, text)),
    )

    dialog._on_save()

    assert warning_calls
    labels = [label.text() for label in editor.findChildren(QLabel)]
    assert any("Suggested auto value:" in text for text in labels)
    set_auto_btn = next(
        btn for btn in editor.findChildren(QPushButton) if btn.text() == "Set to auto"
    )
    set_auto_btn.click()
    assert editor.get_value() == "/auto/exiftool"


def test_mandatory_hint_clears_when_user_edits_field(qapp, monkeypatch):
    monkeypatch.delenv("PIQO_SETTINGS_PANEL_SAVE_MODE", raising=False)
    init_qsettings_store(dyn=True)

    dialog = SettingsDialog(initial_tab_title="Core")
    editor = dialog._editors[UserSettingKey.CACHE_BASE_DIR]
    editor.set_value("/invalid/cache")
    dialog._on_field_changed(UserSettingKey.CACHE_BASE_DIR)

    base_spec = settings_state.get_mandatory_setting_spec(UserSettingKey.CACHE_BASE_DIR)
    assert base_spec is not None
    fake_spec = replace(
        base_spec,
        default_resolver=lambda: "/auto/cache",
        validator=lambda value: value == "/valid/cache",
    )
    monkeypatch.setattr(
        "piqopiqo.settings_panel.dialog.get_mandatory_setting_spec",
        lambda key: fake_spec if key == UserSettingKey.CACHE_BASE_DIR else None,
    )
    monkeypatch.setattr(
        "piqopiqo.settings_panel.dialog.validate_mandatory_setting_value",
        lambda spec, value: spec.validator(str(value).strip()),
    )
    monkeypatch.setattr(
        "piqopiqo.settings_panel.dialog.QMessageBox.warning",
        lambda *_args, **_kwargs: None,
    )

    dialog._on_save()
    assert any(
        "Suggested auto value:" in label.text() for label in editor.findChildren(QLabel)
    )

    editor.set_value("/some/edit")
    dialog._on_field_changed(UserSettingKey.CACHE_BASE_DIR)
    assert not any(
        "Suggested auto value:" in label.text() and label.isVisible()
        for label in editor.findChildren(QLabel)
    )
