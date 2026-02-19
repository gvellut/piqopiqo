"""Tests for GPX time-shift memory helpers."""

from piqopiqo.tools.gpx2exif.time_shift_memory import (
    remember_timeshift_value,
    resolve_timeshift_for_folder,
)


def test_resolve_timeshift_prefers_folder_db_value():
    value, from_state = resolve_timeshift_for_folder(
        db_value="10s",
        folder_key="abc/def",
        cache_by_folder={"abc/def": "20s"},
        last_timeshift="30s",
        ignore_unknown_folder_last=False,
    )
    assert value == "10s"
    assert from_state is False


def test_resolve_timeshift_uses_folder_cache_when_db_missing():
    value, from_state = resolve_timeshift_for_folder(
        db_value=None,
        folder_key="abc/def",
        cache_by_folder={"abc/def": "20s"},
        last_timeshift="30s",
        ignore_unknown_folder_last=False,
    )
    assert value == "20s"
    assert from_state is True


def test_resolve_timeshift_uses_global_last_when_allowed():
    value, from_state = resolve_timeshift_for_folder(
        db_value="",
        folder_key="missing/folder",
        cache_by_folder={"abc/def": "20s"},
        last_timeshift="30s",
        ignore_unknown_folder_last=False,
    )
    assert value == "30s"
    assert from_state is True


def test_resolve_timeshift_ignores_global_last_when_configured():
    value, from_state = resolve_timeshift_for_folder(
        db_value="",
        folder_key="missing/folder",
        cache_by_folder={"abc/def": "20s"},
        last_timeshift="30s",
        ignore_unknown_folder_last=True,
    )
    assert value == ""
    assert from_state is False


def test_relative_folder_keys_are_distinct_in_cache():
    cache = {
        "abc/def": "1s",
        "poi/def": "2s",
    }
    value_a, _ = resolve_timeshift_for_folder(
        db_value=None,
        folder_key="abc/def",
        cache_by_folder=cache,
        last_timeshift=None,
        ignore_unknown_folder_last=True,
    )
    value_b, _ = resolve_timeshift_for_folder(
        db_value=None,
        folder_key="poi/def",
        cache_by_folder=cache,
        last_timeshift=None,
        ignore_unknown_folder_last=True,
    )
    assert value_a == "1s"
    assert value_b == "2s"


def test_remember_timeshift_lru_refresh_and_evict():
    cache = {"a": "1s", "b": "2s", "c": "3s"}
    refreshed = remember_timeshift_value(
        cache,
        folder_key="b",
        value="20s",
        limit=3,
    )
    assert list(refreshed.items()) == [("a", "1s"), ("c", "3s"), ("b", "20s")]

    evicted = remember_timeshift_value(
        refreshed,
        folder_key="d",
        value="4s",
        limit=3,
    )
    assert list(evicted.items()) == [("c", "3s"), ("b", "20s"), ("d", "4s")]
