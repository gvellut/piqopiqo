from enum import Enum

import attr
from PySide6.QtGui import QPixmap


@attr.s(auto_attribs=True)
class ImageItem:
    path: str
    name: str
    created: str
    is_selected: bool = False
    pixmap: QPixmap | None = None
    state: int = 0
    _global_index: int = -1
    exif_data: dict | None = None


class OnFullscreenExitMultipleSelected(Enum):
    KEEP_SELECTION = "keep_selection"
    SELECT_LAST_VIEWED = "select_last_viewed"
