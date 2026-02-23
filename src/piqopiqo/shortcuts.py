from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import auto
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence

from .utils import UpperStrEnum

if TYPE_CHECKING:
    from piqopiqo.model import StatusLabel

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


# Configurable shortcut ownership by view (menu shortcuts such as Cmd+Q are
# separate QAction shortcuts and intentionally not listed here).
LABEL_SHORTCUTS: tuple[Shortcut, ...] = (
    Shortcut.LABEL_1,
    Shortcut.LABEL_2,
    Shortcut.LABEL_3,
    Shortcut.LABEL_4,
    Shortcut.LABEL_5,
    Shortcut.LABEL_6,
    Shortcut.LABEL_7,
    Shortcut.LABEL_8,
    Shortcut.LABEL_9,
    Shortcut.LABEL_NONE,
)

GRID_VIEW_CONFIGURABLE_SHORTCUTS: tuple[Shortcut, ...] = (
    *LABEL_SHORTCUTS,
    Shortcut.SELECT_ALL,
)

FULLSCREEN_VIEW_CONFIGURABLE_SHORTCUTS: tuple[Shortcut, ...] = (
    Shortcut.ZOOM_IN,
    Shortcut.ZOOM_OUT,
    Shortcut.ZOOM_RESET,
    *LABEL_SHORTCUTS,
)

# Hardcoded (non-settings) shortcuts for reference and ownership clarity.
GRID_VIEW_HARDCODED_SHORTCUTS: tuple[str, ...] = (
    "Space (open fullscreen from current selection)",
    "Arrow keys (grid navigation)",
)

FULLSCREEN_VIEW_HARDCODED_SHORTCUTS: tuple[str, ...] = (
    "Escape / Space (exit fullscreen)",
    "Left / Right (navigate fullscreen loop)",
    "Up / Down (ignored)",
)


def build_label_shortcut_bindings(
    shortcuts: Mapping[Shortcut | str, str] | None,
    status_labels: Iterable[StatusLabel] | Iterable[object] | None,
) -> list[tuple[str, str | None]]:
    """Resolve configured label shortcuts to concrete label names.

    Returns a list of ``(shortcut_str, label_name)`` pairs in display order
    (Label 1..9, then No label). Missing labels or empty shortcut strings are skipped.
    """

    shortcuts_mapping = shortcuts or {}
    labels_by_index: dict[int, str] = {}
    for status_label in status_labels or []:
        label_index = getattr(status_label, "index", None)
        label_name = getattr(status_label, "name", None)
        if isinstance(label_index, int) and isinstance(label_name, str) and label_name:
            labels_by_index[label_index] = label_name

    bindings: list[tuple[str, str | None]] = []
    for index in range(1, 10):
        shortcut_enum = Shortcut(f"LABEL_{index}")
        shortcut_str = _lookup_shortcut(shortcuts_mapping, shortcut_enum)
        if not shortcut_str:
            continue
        label_name = labels_by_index.get(index)
        if label_name is None:
            continue
        bindings.append((shortcut_str, label_name))

    label_none_shortcut = _lookup_shortcut(shortcuts_mapping, Shortcut.LABEL_NONE)
    if label_none_shortcut:
        bindings.append((label_none_shortcut, None))

    return bindings


def _lookup_shortcut(
    shortcuts_mapping: Mapping[Shortcut | str, str],
    shortcut_key: Shortcut,
) -> str | None:
    for candidate in (shortcut_key, shortcut_key.value, shortcut_key.name):
        value = shortcuts_mapping.get(candidate)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


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
