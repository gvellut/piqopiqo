from enum import Enum

import attr
from attrs import define
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
    pixmap: QPixmap | None = None
    state: int = 0
    _global_index: int = -1
    exif_data: dict | None = None
    db_metadata: dict | None = None  # Cached DB metadata for editable fields


class OnFullscreenExitMultipleSelected(Enum):
    KEEP_SELECTION = "keep_selection"
    SELECT_LAST_VIEWED = "select_last_viewed"
