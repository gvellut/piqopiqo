"""Utility functions for status labels."""

from __future__ import annotations

from piqopiqo.model import StatusLabel
from piqopiqo.ssf.settings_state import UserSettingKey, get_user_setting


def parse_base_labels(
    value: str, status_labels: list[StatusLabel]
) -> tuple[set[str], bool]:
    """Resolve label digits and the 0/No Label flag, ignoring spaces/duplicates."""
    digits = set()
    for character in value:
        if character.isspace():
            continue
        if character not in "0123456789":
            raise ValueError(
                "Use label numbers with optional spaces, e.g. 0123 or 0 1 2 3. "
                "0 = No Label."
            )
        digits.add(int(character))

    include_no_label = 0 in digits
    digits.discard(0)
    labels_by_index = {label.index: label.name for label in status_labels}
    missing = digits - labels_by_index.keys()
    if missing:
        numbers = ", ".join(str(index) for index in sorted(missing))
        raise ValueError(f"Undefined status label numbers: {numbers}.")
    return {labels_by_index[index] for index in digits}, include_no_label


def get_label_color(label: str) -> str | None:
    """Get color hex for a label name from STATUS_LABELS.

    Args:
        label: The label name to look up.

    Returns:
        The color hex string, or None if not found.
    """
    for sl in get_user_setting(UserSettingKey.STATUS_LABELS):
        if sl.name == label:
            return sl.color
    return None
