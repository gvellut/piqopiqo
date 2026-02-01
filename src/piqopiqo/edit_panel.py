"""Backward compatibility: re-export from panels/."""

from .panels import (
    CoordinateEdit,
    DescriptionEdit,
    EditPanel,
    KeywordsEdit,
    TimeEdit,
    TitleEdit,
)
from .panels.edit_widgets import MULTIPLE_VALUES

__all__ = [
    "CoordinateEdit",
    "DescriptionEdit",
    "EditPanel",
    "KeywordsEdit",
    "MULTIPLE_VALUES",
    "TimeEdit",
    "TitleEdit",
]
