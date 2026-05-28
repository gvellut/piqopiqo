"""Tests for metadata-driven model refresh behavior."""

from __future__ import annotations

from datetime import datetime

from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDBManager
from piqopiqo.model import FilterCriteria, ImageItem
from piqopiqo.photo_model import PhotoListModel, SortOrder


def _item(
    path: str,
    *,
    title: str | None = None,
    keywords: str | None = None,
    label: str | None = None,
    time_taken: datetime | None = None,
    selected: bool = False,
    source_folder: str = "/photos",
) -> ImageItem:
    return ImageItem(
        path=path,
        name=path.split("/")[-1],
        created="2020-01-01 00:00:00",
        source_folder=source_folder,
        is_selected=selected,
        db_metadata={
            DBFields.TITLE: title,
            DBFields.KEYWORDS: keywords,
            DBFields.LABEL: label,
            DBFields.TIME_TAKEN: time_taken,
        },
    )


def test_refresh_filters_out_item_after_label_change():
    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/a.jpg", label="Approved", selected=True)
    second = _item("/photos/b.jpg", label="Rejected")

    model.set_photos([first, second], ["/photos"])
    model.set_filter(FilterCriteria(labels={"Approved"}))
    assert [item.path for item in model.photos] == ["/photos/a.jpg"]

    first.db_metadata[DBFields.LABEL] = "Rejected"
    model.refresh_after_metadata_update()

    assert model.photos == []
    assert first.is_selected is False


def test_refresh_filters_out_item_after_search_field_change():
    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/a.jpg", title="Golden Sunset", selected=True)
    second = _item("/photos/b.jpg", title="Forest")

    model.set_photos([first, second], ["/photos"])
    model.set_filter(FilterCriteria(search_text="sunset"))
    assert [item.path for item in model.photos] == ["/photos/a.jpg"]

    first.db_metadata[DBFields.TITLE] = "Mountains"
    model.refresh_after_metadata_update()

    assert model.photos == []
    assert first.is_selected is False


def test_refresh_resorts_after_time_taken_change():
    model = PhotoListModel(MetadataDBManager())
    older = _item("/photos/a.jpg", time_taken=datetime(2026, 1, 1, 10, 0, 0))
    newer = _item("/photos/b.jpg", time_taken=datetime(2026, 1, 1, 12, 0, 0))

    model.set_photos([newer, older], ["/photos"])
    model.set_sort_order(SortOrder.TIME_TAKEN)
    assert [item.path for item in model.photos] == ["/photos/a.jpg", "/photos/b.jpg"]

    older.db_metadata[DBFields.TIME_TAKEN] = datetime(2026, 1, 1, 13, 0, 0)
    model.refresh_after_metadata_update()

    assert [item.path for item in model.photos] == ["/photos/b.jpg", "/photos/a.jpg"]


def test_set_filter_normalizes_empty_criteria_and_skips_unchanged_updates():
    model = PhotoListModel(MetadataDBManager())
    model.set_photos([_item("/photos/a.jpg", label="Approved")], ["/photos"])

    emitted: list[int] = []
    model.photos_changed.connect(lambda: emitted.append(1))

    changed = model.set_filter(FilterCriteria())
    assert changed is False
    assert model._filter is None
    assert emitted == []

    changed = model.set_filter(FilterCriteria(search_text="   "))
    assert changed is False
    assert model._filter is None
    assert emitted == []

    changed = model.set_filter(FilterCriteria(labels={"Approved"}))
    assert changed is True
    assert emitted == [1]

    changed = model.set_filter(FilterCriteria(labels={"Approved"}))
    assert changed is False
    assert emitted == [1]


def test_set_filter_can_update_silently_without_emitting():
    model = PhotoListModel(MetadataDBManager())
    model.set_photos([_item("/photos/a.jpg", title="Sunset")], ["/photos"])

    emitted: list[int] = []
    model.photos_changed.connect(lambda: emitted.append(1))

    changed = model.set_filter(FilterCriteria(search_text="sunset"), emit_signals=False)

    assert changed is True
    assert model._filter == FilterCriteria(
        folder=None,
        labels=set(),
        include_no_label=False,
        explicit_labels=set(),
        search_text="sunset",
    )
    assert [item.path for item in model.photos] == ["/photos/a.jpg"]
    assert emitted == []


def test_no_label_filter_includes_unknown_labels_from_old_settings():
    model = PhotoListModel(MetadataDBManager())
    renamed = _item("/photos/a.jpg", label="Renamed")
    current = _item("/photos/b.jpg", label="Approved")
    empty = _item("/photos/c.jpg", label=None)

    model.set_photos([renamed, current, empty], ["/photos"])
    model.set_filter(
        FilterCriteria(
            include_no_label=True,
            explicit_labels={"Approved", "Rejected"},
        )
    )

    assert [item.path for item in model.photos] == ["/photos/a.jpg", "/photos/c.jpg"]


def test_update_photo_paths_preserves_selection_and_metadata():
    model = PhotoListModel(MetadataDBManager())
    first = _item("/photos/old/a.jpg", label="Approved", selected=True)
    second = _item("/photos/b.jpg", label="Rejected")
    model.set_photos([first, second], ["/photos/old", "/photos"])

    applied = model.update_photo_paths([
        ("/photos/old/a.jpg", "/photos/new/a-renamed.jpg")
    ])

    assert applied == [("/photos/old/a.jpg", "/photos/new/a-renamed.jpg")]
    assert first.path == "/photos/new/a-renamed.jpg"
    assert first.name == "a-renamed.jpg"
    assert first.source_folder == "/photos/new"
    assert first.is_selected is True
    assert first.db_metadata[DBFields.LABEL] == "Approved"
    assert model.source_folders == ["/photos", "/photos/new"]
    assert model.get_selected_photos() == [first]


def test_update_photo_paths_respects_folder_filter_and_clears_hidden_selection():
    model = PhotoListModel(MetadataDBManager())
    first = _item(
        "/photos/old/a.jpg",
        selected=True,
        source_folder="/photos/old",
    )
    second = _item(
        "/photos/old/b.jpg",
        selected=True,
        source_folder="/photos/old",
    )
    model.set_photos([first, second], ["/photos/old"])
    model.set_filter(FilterCriteria(folder="/photos/old"))

    model.update_photo_paths([("/photos/old/a.jpg", "/photos/new/a.jpg")])

    assert [item.path for item in model.photos] == ["/photos/old/b.jpg"]
    assert first.is_selected is False
    assert second.is_selected is True
    assert model.source_folders == ["/photos/new", "/photos/old"]
