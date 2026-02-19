"""Time-shift parsing and formatting utilities."""

from __future__ import annotations

from datetime import datetime, timedelta
import re

_TIME_SHIFT_RE = re.compile(
    r"^(?P<negative>-)?(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$"
)


def _parse_time_or_datetime(text: str) -> datetime:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Empty time expression")

    # Full datetime first (with optional timezone)
    normalized = cleaned.replace(" ", "T")
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass

    # Time-only expression (HH:MM:SS), use a shared dummy date.
    try:
        t = datetime.strptime(cleaned, "%H:%M:%S").time()
    except ValueError as ex:
        raise ValueError(f"Invalid time expression: {text!r}") from ex
    return datetime.combine(datetime(2021, 10, 10).date(), t)


def parse_time_shift(expression: str) -> timedelta:
    """Parse a GPX time-shift expression.

    Supports:
    - Canonical deltas like ``-1h16m5s``
    - Time differences like ``16:18:56-17:15:03``
    """
    expr = expression.strip()
    if not expr:
        raise ValueError("Time shift cannot be empty")
    if expr == "0":
        return timedelta(0)

    if "-" in expr and not expr.startswith("-"):
        left_text, right_text = expr.split("-", 1)
        left = _parse_time_or_datetime(left_text)
        right = _parse_time_or_datetime(right_text)
        return left - right

    match = _TIME_SHIFT_RE.match(expr)
    if not match:
        raise ValueError(f"Invalid time shift expression: {expression!r}")

    parts = match.groupdict()
    has_component = any(parts.get(key) for key in ("hours", "minutes", "seconds"))
    if not has_component:
        raise ValueError(f"Invalid time shift expression: {expression!r}")

    mult = -1 if parts.get("negative") else 1
    hours = int(parts["hours"] or 0) * mult
    minutes = int(parts["minutes"] or 0) * mult
    seconds = int(parts["seconds"] or 0) * mult
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def format_time_shift(delta: timedelta) -> str:
    """Format a timedelta using the canonical GPX time-shift form."""
    total_seconds = int(round(delta.total_seconds()))
    if total_seconds == 0:
        return "0"

    negative = total_seconds < 0
    if negative:
        total_seconds = -total_seconds

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    out = ""
    if negative:
        out += "-"
    if hours:
        out += f"{hours}h"
    if minutes:
        out += f"{minutes}m"
    if seconds or not out or out == "-":
        out += f"{seconds}s"

    return out


def is_valid_time_shift(expression: str) -> bool:
    """Return True when the expression is a valid non-empty shift value."""
    try:
        parse_time_shift(expression)
    except ValueError:
        return False
    return True
