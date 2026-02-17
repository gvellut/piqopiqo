from __future__ import annotations

from enum import auto
from typing import TYPE_CHECKING

import attr
from attrs import define

from .utils import UpperStrEnum

if TYPE_CHECKING:
    from PySide6.QtGui import QPixmap


@define
class StatusLabel:
    name: str
    color: str
    index: int


@define
class ExifField:
    """EXIF field definition for display in the EXIF panel.

    Attributes:
        key: The exiftool key (e.g., "EXIF:DateTimeOriginal")
        label: Optional display label. If None, uses auto-formatted key or raw key.
    """

    key: str
    label: str | None = None


@define
class FilterCriteria:
    """Filter criteria for the photo model.

    All filters are combined with AND logic.
    Label filters within labels set use OR logic.
    """

    folder: str | None = None  # None means all folders
    labels: set[str] = attr.Factory(set)  # Label names to show (OR). Empty = no filter.
    include_no_label: bool = False  # Whether to include photos with no label
    search_text: str = ""  # Search in keywords + title (case insensitive)


@attr.s(auto_attribs=True)
class ImageItem:
    path: str
    name: str
    created: str
    source_folder: str = ""
    is_selected: bool = False
    # Embedded preview JPEG extracted from EXIF (low-res).
    # Evicted outside GRID_EMBEDDED_BUFFER_ROWS to save memory.
    embedded_pixmap: QPixmap | None = None
    # HQ thumbnail generated from full image.
    # Evicted outside GRID_THUMB_BUFFER_ROWS to save memory.
    hq_pixmap: QPixmap | None = None
    # Orientation-applied pixmap currently used for display in the grid.
    # Built from embedded_pixmap or hq_pixmap with orientation applied.
    pixmap: QPixmap | None = None
    state: int = 0
    _global_index: int = -1
    exif_data: dict | None = None
    db_metadata: dict | None = None  # Cached DB metadata for editable fields


class OnFullscreenExitMultipleSelected(UpperStrEnum):
    KEEP_SELECTION = auto()
    SELECT_LAST_VIEWED = auto()


@define
class LabelUndoEntry:
    """Stores the state for a single label undo/redo operation.

    Attributes:
        items: List of ImageItem references that were modified.
        previous_labels: Dict mapping item path to label value before the edit.
        new_labels: Dict mapping item path to label value after the edit.
    """

    items: list[ImageItem]
    previous_labels: dict[str, str | None]
    new_labels: dict[str, str | None]
