"""Helpers for remembering and resolving GPX time-shift values."""

from __future__ import annotations


def normalize_time_shift(raw_value: object) -> str | None:
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    return text


def normalize_timeshift_cache(raw_value: object) -> dict[str, str]:
    if not isinstance(raw_value, dict):
        return {}

    out: dict[str, str] = {}
    for raw_key, raw_shift in raw_value.items():
        key = str(raw_key).strip()
        shift = normalize_time_shift(raw_shift)
        if not key or shift is None:
            continue
        out[key] = shift
    return out


def resolve_timeshift_for_folder(
    *,
    db_value: str | None,
    folder_key: str,
    cache_by_folder: dict[str, str],
    last_timeshift: str | None,
    ignore_unknown_folder_last: bool,
) -> tuple[str, bool]:
    """Resolve folder shift with precedence and whether it came from state."""
    db_shift = normalize_time_shift(db_value)
    if db_shift is not None:
        return db_shift, False

    cache = normalize_timeshift_cache(cache_by_folder)
    key = str(folder_key).strip()
    if key and key in cache:
        return cache[key], True

    last_shift = normalize_time_shift(last_timeshift)
    if last_shift is not None and not ignore_unknown_folder_last:
        return last_shift, True

    return "", False


def remember_timeshift_value(
    cache_by_folder: dict[str, str],
    *,
    folder_key: str,
    value: str,
    limit: int,
) -> dict[str, str]:
    """Return updated LRU cache with ``folder_key`` moved to most recent."""
    cache = normalize_timeshift_cache(cache_by_folder)
    key = str(folder_key).strip()
    shift = normalize_time_shift(value)
    if not key or shift is None:
        return cache

    cache.pop(key, None)
    cache[key] = shift

    max_items = max(0, int(limit))
    while len(cache) > max_items:
        oldest_key = next(iter(cache))
        cache.pop(oldest_key, None)

    return cache
