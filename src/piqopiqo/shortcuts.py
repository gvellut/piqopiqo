from __future__ import annotations

from enum import auto
import logging

from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence

from .utils import UpperStrEnum

logger = logging.getLogger(__name__)


class Shortcut(UpperStrEnum):
    ZOOM_IN = auto()
    ZOOM_OUT = auto()
    ZOOM_RESET = auto()
    LABEL_1 = auto()
    LABEL_2 = auto()
    LABEL_3 = auto()
    LABEL_4 = auto()
    LABEL_5 = auto()
    LABEL_6 = auto()
    LABEL_7 = auto()
    LABEL_8 = auto()
    LABEL_9 = auto()
    LABEL_NONE = auto()
    SELECT_ALL = auto()

    @property
    def label(self) -> str:
        return _SHORTCUT_LABELS[self]


_SHORTCUT_LABELS: dict[Shortcut, str] = {
    Shortcut.ZOOM_IN: "Zoom in",
    Shortcut.ZOOM_OUT: "Zoom out",
    Shortcut.ZOOM_RESET: "Zoom reset",
    Shortcut.LABEL_1: "Label 1",
    Shortcut.LABEL_2: "Label 2",
    Shortcut.LABEL_3: "Label 3",
    Shortcut.LABEL_4: "Label 4",
    Shortcut.LABEL_5: "Label 5",
    Shortcut.LABEL_6: "Label 6",
    Shortcut.LABEL_7: "Label 7",
    Shortcut.LABEL_8: "Label 8",
    Shortcut.LABEL_9: "Label 9",
    Shortcut.LABEL_NONE: "No label",
    Shortcut.SELECT_ALL: "Select all",
}


def parse_shortcut(shortcut_str: str) -> QKeySequence:
    return QKeySequence(shortcut_str)


def match_shortcut_sequence(event: QKeyEvent, shortcut_str: str) -> bool:
    if not shortcut_str:
        return False

    expected_sequence = parse_shortcut(shortcut_str)

    # Build the key combination from the event
    event_modifiers = event.modifiers()
    clean_modifiers = _clean_modifiers(event_modifiers)
    key_with_modifiers = QKeyCombination(clean_modifiers, Qt.Key(event.key()))

    # Create a QKeySequence from the event
    event_sequence = QKeySequence(key_with_modifiers)

    logger.debug(event_sequence.toString())

    return expected_sequence == event_sequence


def match_simple_shortcut(event: QKeyEvent, key: int) -> bool:
    event_modifiers = event.modifiers()
    clean_modifiers = _clean_modifiers(event_modifiers)
    return event.key() == key and clean_modifiers == Qt.NoModifier


def _clean_modifiers(modifiers):
    # just the basic ones
    standard_mods = (
        Qt.KeyboardModifier.ShiftModifier
        | Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.AltModifier
        | Qt.KeyboardModifier.MetaModifier
    )
    return modifiers & standard_mods
