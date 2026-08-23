"""Tests for shared and database-only Find & Replace behavior."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QTextEdit, QWidget
import pytest

from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDB
from piqopiqo.model import ImageItem
from piqopiqo.tools.edit_tools.find_replace import (
    LocalFindReplaceDialog,
    LocalFindReplaceResult,
    LocalFindReplaceWorker,
    launch_local_find_replace,
)
from piqopiqo.tools.edit_tools.service import (
    FindReplaceSpec,
    apply_replacement,
    validate_find_replace_spec,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app
    app.closeAllWindows()
    app.processEvents()


def _item(path: str, title: str = "Title", keywords: str = "one, two") -> ImageItem:
    return ImageItem(
        path=path,
        name=path.rsplit("/", 1)[-1],
        created="2026-01-01 10:00:00",
        source_folder=path.rsplit("/", 1)[0],
        db_metadata={
            DBFields.TITLE: title,
            DBFields.KEYWORDS: keywords,
            DBFields.DESCRIPTION: "unchanged",
        },
    )


def test_title_condition_gates_title_and_tag_changes() -> None:
    spec = FindReplaceSpec(
        title_pattern=r"^Trip (\d+)$",
        replace_title=True,
        title_replacement=r"Journey \1",
        remove_tags=("old",),
        add_tags=("new",),
    )
    matched = apply_replacement("Trip 12", ["old", "keep"], spec)
    assert matched.eligible is True
    assert matched.title == "Journey 12"
    assert matched.tags == ("keep", "new")
    assert matched.title_changed is True
    assert matched.removed_tags == 1
    assert matched.added_tags == 1

    unmatched = apply_replacement("Other", ["old"], spec)
    assert unmatched.eligible is False
    assert unmatched.title == "Other"
    assert unmatched.tags == ("old",)


def test_empty_title_replacement_is_an_actual_change() -> None:
    spec = FindReplaceSpec(
        title_pattern="prefix ",
        replace_title=True,
        title_replacement="",
    )
    outcome = apply_replacement("prefix title", [], spec)
    assert outcome.title == "title"
    assert outcome.title_changed is True


def test_conditional_tag_add_requires_exact_removal() -> None:
    spec = FindReplaceSpec(
        remove_tags=("Old",),
        add_tags=("New",),
        add_only_if_removed=True,
    )
    no_exact_match = apply_replacement("", ["old"], spec)
    assert no_exact_match.tags == ("old",)
    assert no_exact_match.added_tags == 0

    exact_match = apply_replacement("", ["Old", "keep"], spec)
    assert exact_match.tags == ("keep", "New")
    assert exact_match.removed_tags == 1
    assert exact_match.added_tags == 1


def test_validation_rejects_missing_action_and_invalid_regex() -> None:
    assert validate_find_replace_spec(FindReplaceSpec()) is not None
    assert (
        validate_find_replace_spec(
            FindReplaceSpec(title_pattern="[", replace_title=True)
        )
        is not None
    )


def test_local_worker_updates_only_database_metadata_fields() -> None:
    saved: list[tuple[str, dict]] = []

    class _Db:
        def update_title_and_keywords(self, file_path: str, changes: dict) -> bool:
            saved.append((file_path, changes.copy()))
            return True

    class _Manager:
        def get_db_for_image(self, _file_path: str):
            return _Db()

    worker = LocalFindReplaceWorker(
        db_manager=_Manager(),
        entries=[
            {
                "file_path": "/photos/a.jpg",
                "metadata": {
                    DBFields.TITLE: "Old title",
                    DBFields.KEYWORDS: "old, keep",
                    DBFields.DESCRIPTION: "untouched",
                },
            }
        ],
        spec=FindReplaceSpec(
            title_pattern="Old",
            replace_title=True,
            title_replacement="New",
            remove_tags=("old",),
            add_tags=("added",),
        ),
    )
    results = []
    worker.signals.finished.connect(results.append)
    worker.run()

    assert len(saved) == 1
    _, changes = saved[0]
    assert changes == {
        DBFields.TITLE: "New title",
        DBFields.KEYWORDS: "keep, added",
    }
    assert DBFields.DESCRIPTION not in changes
    assert results[0].photos_changed == 1


def test_targeted_db_update_preserves_other_metadata(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "piqopiqo.metadata.metadata_db.get_cache_dir_for_folder",
        lambda _folder: tmp_path,
    )
    db = MetadataDB("/photos")
    file_path = "/photos/a.jpg"
    db.save_metadata(
        file_path,
        {
            DBFields.TITLE: "Old",
            DBFields.KEYWORDS: "one",
            DBFields.DESCRIPTION: "preserve",
        },
    )

    assert db.update_title_and_keywords(
        file_path,
        {DBFields.TITLE: "New", DBFields.KEYWORDS: "two"},
    )
    metadata = db.get_metadata(file_path)
    assert metadata is not None
    assert metadata[DBFields.TITLE] == "New"
    assert metadata[DBFields.KEYWORDS] == "two"
    assert metadata[DBFields.DESCRIPTION] == "preserve"
    db.close()


def test_launcher_prefers_selection_and_falls_back_to_visible(monkeypatch) -> None:
    selected = _item("/photos/selected.jpg")
    visible = [_item("/photos/a.jpg"), _item("/photos/b.jpg")]

    class _PhotoModel:
        all_photos = [selected, *visible]

        def __init__(self):
            self.selection = [selected]

        def get_selected_photos(self):
            return list(self.selection)

    class _DbManager:
        def ensure_items_metadata_ready(self, _items) -> bool:
            return True

    class _Window:
        def __init__(self):
            self.photo_model = _PhotoModel()
            self.images_data = visible
            self.db_manager = _DbManager()

    calls: list[dict] = []

    class _Dialog:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def exec(self):
            return 0

    monkeypatch.setattr(
        "piqopiqo.tools.edit_tools.find_replace.LocalFindReplaceDialog",
        _Dialog,
    )
    window = _Window()
    launch_local_find_replace(window)
    assert calls[-1]["target_items"] == [selected]
    assert calls[-1]["used_visible_fallback"] is False

    window.photo_model.selection = []
    launch_local_find_replace(window)
    assert calls[-1]["target_items"] == visible
    assert calls[-1]["used_visible_fallback"] is True
    assert calls[-1]["selected_count"] == 0


def test_launcher_rejects_an_empty_resolved_scope(monkeypatch) -> None:
    class _PhotoModel:
        all_photos = []

        def get_selected_photos(self):
            return []

    class _Window:
        photo_model = _PhotoModel()
        images_data = []

    messages: list[str] = []
    monkeypatch.setattr(
        "piqopiqo.tools.edit_tools.find_replace.QMessageBox.information",
        lambda _parent, _title, message: messages.append(message),
    )

    launch_local_find_replace(_Window())

    assert messages == ["No selected or visible photos are available."]


def test_launcher_stops_when_stored_metadata_is_not_ready(monkeypatch) -> None:
    item = _item("/photos/a.jpg")

    class _PhotoModel:
        all_photos = [item]

        def get_selected_photos(self):
            return [item]

    class _DbManager:
        def ensure_items_metadata_ready(self, _items) -> bool:
            return False

    class _Window:
        photo_model = _PhotoModel()
        images_data = [item]
        db_manager = _DbManager()

    messages: list[str] = []
    monkeypatch.setattr(
        "piqopiqo.tools.edit_tools.find_replace.QMessageBox.information",
        lambda _parent, _title, message: messages.append(message),
    )

    launch_local_find_replace(_Window())

    assert len(messages) == 1
    assert "Try again when reading is complete" in messages[0]


def test_local_dialog_warns_for_visible_fallback_and_orders_buttons(qapp) -> None:
    class _Window(QWidget):
        db_manager = object()

        def sync_model_after_metadata_update(self, *_args, **_kwargs) -> None:
            return None

    window = _Window()
    item = _item("/photos/a.jpg")
    dialog = LocalFindReplaceDialog(
        window=window,
        target_items=[item],
        selected_count=0,
        visible_count=1,
        loaded_count=3,
        used_visible_fallback=True,
        parent=window,
    )
    dialog.show()
    qapp.processEvents()

    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert any("No photos are selected" in text for text in texts)
    assert any("Will process: 1" in text for text in texts)
    assert dialog.button("cancel").x() < dialog.button("apply").x()


def test_local_result_summary_is_read_only_selectable_multiline_text(qapp) -> None:
    class _Window(QWidget):
        db_manager = object()

        def sync_model_after_metadata_update(self, *_args, **_kwargs) -> None:
            return None

    window = _Window()
    dialog = LocalFindReplaceDialog(
        window=window,
        target_items=[_item("/photos/a.jpg")],
        selected_count=1,
        visible_count=1,
        loaded_count=1,
        used_visible_fallback=False,
        parent=window,
    )
    dialog._result = LocalFindReplaceResult(
        total=10,
        processed=8,
        eligible=7,
        title_changed=5,
        tags_removed=4,
        tags_added=3,
        photos_changed=6,
        unchanged=2,
        cancelled=True,
    )

    dialog.transition_to("result")
    summary = dialog.findChild(QTextEdit, "localFindReplaceSummaryText")

    assert summary is not None
    assert summary.isReadOnly() is True
    assert summary.lineWrapMode() == QTextEdit.LineWrapMode.NoWrap
    assert summary.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    assert summary.toPlainText() == (
        "Canceled. Processed 8 of 10 photos.\n"
        "Eligible: 7    Changed photos: 6    Unchanged: 2\n"
        "Titles changed: 5    Tags removed: 4    Tags added: 3\n\n"
        "Only the PiqoPiqo SQLite metadata database was changed. Image "
        "files and EXIF metadata were untouched."
    )
