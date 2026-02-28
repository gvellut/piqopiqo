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
) -> ImageItem:
    return ImageItem(
        path=path,
        name=path.split("/")[-1],
        created="2020-01-01 00:00:00",
        source_folder="/photos",
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
