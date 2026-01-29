"""Unified shortcut handling for PiqoPiqo.

This module provides consistent shortcut parsing and matching across the application
using Qt's QKeySequence for all operations.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QKeySequence

from .config import Config, Shortcut


def parse_shortcut(shortcut_str: str) -> QKeySequence:
    """Parse a shortcut string into a QKeySequence.

    Supports formats:
    - Simple keys: "=", "-", "0", "1", "`"
    - Modified keys: "ctrl+r", "cmd+alt+t", "shift+a"

    Modifier names (case-insensitive):
    - ctrl, alt, cmd/meta, shift

    Args:
        shortcut_str: Shortcut string like "ctrl+s" or "="

    Returns:
        QKeySequence representing the shortcut
    """
    parts = [p.strip().lower() for p in shortcut_str.split("+")]
    qt_parts = []

    for part in parts[:-1]:  # Process modifiers
        if part in ("cmd", "meta"):
            qt_parts.append("Meta")
        elif part == "ctrl":
            qt_parts.append("Ctrl")
        elif part == "alt":
            qt_parts.append("Alt")
        elif part == "shift":
            qt_parts.append("Shift")

    # Process key part
    key_part = parts[-1]
    qt_parts.append(key_part.upper() if len(key_part) > 1 else key_part)

    return QKeySequence("+".join(qt_parts))


def match_shortcut(event: QKeyEvent, shortcut_str: str) -> bool:
    """Check if a key event matches a shortcut string.

    Uses QKeySequence for consistent matching across the application.

    Args:
        event: The Qt key event to check
        shortcut_str: Shortcut string like "ctrl+s" or "="

    Returns:
        True if the event matches the shortcut
    """
    expected_sequence = parse_shortcut(shortcut_str)

    # Build the key combination from the event
    event_key = event.key()
    event_modifiers = event.modifiers()

    # Create a QKeySequence from the event
    key_with_modifiers = event_key | int(event_modifiers)
    event_sequence = QKeySequence(key_with_modifiers)

    return expected_sequence == event_sequence


def match_shortcut_enum(event: QKeyEvent, shortcut_enum: Shortcut) -> bool:
    """Check if a key event matches a configured shortcut enum.

    Looks up the shortcut string from Config.SHORTCUTS and matches against it.

    Args:
        event: The Qt key event to check
        shortcut_enum: The Shortcut enum value to match

    Returns:
        True if event matches, False if not or shortcut not configured
    """
    shortcut_str = Config.SHORTCUTS.get(shortcut_enum)
    if shortcut_str is None:
        return False
    return match_shortcut(event, shortcut_str)


def get_shortcut_sequence(shortcut_enum: Shortcut) -> QKeySequence | None:
    """Get the QKeySequence for a configured shortcut.

    Args:
        shortcut_enum: The Shortcut enum value

    Returns:
        QKeySequence or None if shortcut not configured
    """
    shortcut_str = Config.SHORTCUTS.get(shortcut_enum)
    if shortcut_str is None:
        return None
    return parse_shortcut(shortcut_str)


class HardcodedShortcut:
    """Non-configurable shortcuts for core navigation."""

    ESCAPE = Qt.Key_Escape
    SPACE = Qt.Key_Space
    LEFT = Qt.Key_Left
    RIGHT = Qt.Key_Right
    UP = Qt.Key_Up
    DOWN = Qt.Key_Down


def match_hardcoded(event: QKeyEvent, key: int) -> bool:
    """Check if event matches a hardcoded (non-configurable) shortcut.

    Args:
        event: The Qt key event
        key: The Qt.Key_* constant to match

    Returns:
        True if the event matches (with no modifiers)
    """
    return event.key() == key and event.modifiers() == Qt.NoModifier
