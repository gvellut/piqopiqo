from enum import Enum
from typing import Optional

import attr
from PySide6.QtGui import QPixmap


@attr.s(auto_attribs=True)
class ImageItem:
    path: str
    name: str
    created: str
    is_selected: bool = False
    pixmap: Optional[QPixmap] = None
    state: int = 0
    _global_index: int = -1


class OnFullscreenExit(Enum):
    KEEP_SELECTION = "keep_selection"
    SELECT_LAST_VIEWED = "select_last_viewed"
