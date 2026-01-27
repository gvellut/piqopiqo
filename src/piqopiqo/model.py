from enum import Enum

import attr
from attrs import define
from PySide6.QtGui import QPixmap


@define
class StatusLabel:
    name: str
    color: str
    index: int


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
