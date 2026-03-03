"""Tests for the workspace property dialog."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QAbstractItemView, QMessageBox
import pytest

from piqopiqo.dialogs.workspace_properties_dialog import (
    WorkspaceFolderSummary,
    WorkspacePropertiesDialog,
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
    core.setApplicationName(f"piqopiqo-test-workspace-dialog-{uuid.uuid4().hex}")
    return app


def _make_summaries() -> list[WorkspaceFolderSummary]:
    return [
        WorkspaceFolderSummary(
            folder_path="/photos",
            relative_path=".",
            cache_folder_name="cache_root",
            photo_count=5,
        ),
        WorkspaceFolderSummary(
            folder_path="/photos/trip_a",
            relative_path="trip_a",
            cache_folder_name="cache_trip_a",
            photo_count=2,
        ),
        WorkspaceFolderSummary(
            folder_path="/photos/trip_b",
            relative_path="trip_b",
            cache_folder_name="cache_trip_b",
            photo_count=1,
        ),
        WorkspaceFolderSummary(
            folder_path="/photos/trip_c",
            relative_path="trip_c",
            cache_folder_name="cache_trip_c",
            photo_count=3,
        ),
    ]


def _make_dialog() -> WorkspacePropertiesDialog:
    return WorkspacePropertiesDialog(
        root_folder="/photos",
        total_photo_count=11,
        folder_summaries=_make_summaries(),
    )


def test_folder_list_shows_relative_labels_including_root_dot(qapp):
    dialog = _make_dialog()
    labels = [dialog.folder_list_widget.item(i).text() for i in range(4)]
    assert labels == [".", "trip_a", "trip_b", "trip_c"]


def test_folder_list_is_single_selection(qapp):
    dialog = _make_dialog()
    assert (
        dialog.folder_list_widget.selectionMode()
        == QAbstractItemView.SelectionMode.SingleSelection
    )

    dialog.folder_list_widget.setCurrentRow(1)
    qapp.processEvents()
    assert len(dialog.folder_list_widget.selectedItems()) == 1
    assert dialog.folder_list_widget.selectedItems()[0].text() == "trip_a"

    dialog.folder_list_widget.setCurrentRow(3)
    qapp.processEvents()
    assert len(dialog.folder_list_widget.selectedItems()) == 1
    assert dialog.folder_list_widget.selectedItems()[0].text() == "trip_c"


def test_folder_list_reserves_height_for_at_least_three_rows(qapp):
    dialog = _make_dialog()
    row_height = dialog.folder_list_widget.sizeHintForRow(0)
    assert row_height > 0
    assert dialog.folder_list_widget.minimumHeight() >= (row_height * 3)


def test_thumb_clear_button_sets_pending_flag_and_disables_button(qapp):
    dialog = _make_dialog()
    assert dialog.clear_thumb_cache_requested is False
    assert dialog.clear_thumb_cache_button.isEnabled() is True

    dialog.clear_thumb_cache_button.click()

    assert dialog.clear_thumb_cache_requested is True
    assert dialog.clear_thumb_cache_button.isEnabled() is False


def test_metadata_clear_button_requires_confirmation(monkeypatch, qapp):
    dialog = _make_dialog()
    calls: list[str] = []

    def _warning_stub(*_args, **_kwargs):
        calls.append("called")
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "warning", _warning_stub)
    dialog.clear_metadata_button.click()

    assert calls == ["called"]
    assert dialog.clear_metadata_requested is False
    assert dialog.clear_metadata_button.isEnabled() is True


def test_metadata_clear_button_sets_pending_flag_after_confirmation(monkeypatch, qapp):
    dialog = _make_dialog()

    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )
    dialog.clear_metadata_button.click()

    assert dialog.clear_metadata_requested is True
    assert dialog.clear_metadata_button.isEnabled() is False


def test_selected_folder_detail_updates_with_selection(qapp):
    dialog = _make_dialog()

    dialog.folder_list_widget.setCurrentRow(2)
    qapp.processEvents()

    assert dialog.selected_folder_value.text() == "trip_b"
    assert dialog.selected_cache_value.text() == "cache_trip_b"
    assert dialog.selected_photo_count_value.text() == "1"
