from __future__ import annotations

from enum import auto
import logging

from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence

from .utils import UpperStrEnum

logger = logging.getLogger(__name__)


class Shortcut(UpperStrEnum):
    ZOOM_IN = auto(), "Zoom in"
    ZOOM_OUT = auto(), "Zoom out"
    ZOOM_RESET = auto(), "Zoom reset"
    LABEL_1 = auto(), "Label 1"
    LABEL_2 = auto(), "Label 2"
    LABEL_3 = auto(), "Label 3"
    LABEL_4 = auto(), "Label 4"
    LABEL_5 = auto(), "Label 5"
    LABEL_6 = auto(), "Label 6"
    LABEL_7 = auto(), "Label 7"
    LABEL_8 = auto(), "Label 8"
    LABEL_9 = auto(), "Label 9"
    LABEL_NONE = auto(), "No label"
    SELECT_ALL = auto(), "Select all"

    def __new__(cls, name, label):
        obj = str.__new__(cls, name)

        obj._value_ = name
        return obj

    def __init__(self, name, label):
        self.label = label


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
