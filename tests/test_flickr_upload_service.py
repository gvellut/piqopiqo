"""Tests for Flickr upload pure helpers."""

from __future__ import annotations

import pytest

from piqopiqo.tools.flickr_upload.service import (
    TicketStatus,
    classify_ticket_complete,
    format_flickr_tags,
    format_flickr_tags_from_db_keywords,
    generate_timestamps,
    retry,
)


def test_format_flickr_tags_from_list() -> None:
    assert format_flickr_tags(["foo", "bar baz"]) == '"foo" "bar baz"'


def test_format_flickr_tags_from_db_keywords() -> None:
    assert (
        format_flickr_tags_from_db_keywords('one, "two,three"') == '"one" "two,three"'
    )


def test_format_flickr_tags_rejects_double_quote() -> None:
    with pytest.raises(ValueError):
        format_flickr_tags(['bad"tag'])


def test_generate_timestamps_keeps_order() -> None:
    assert generate_timestamps(100, 3) == [94, 95, 96]


def test_retry_succeeds_before_exhaustion() -> None:
    counter = {"n": 0}

    def _fn() -> str:
        counter["n"] += 1
        if counter["n"] < 3:
            raise ValueError("boom")
        return "ok"

    assert retry(3, _fn) == "ok"
    assert counter["n"] == 3


def test_retry_raises_after_exhaustion() -> None:
    def _fn() -> None:
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        retry(2, _fn)


def test_retry_returns_none_with_callback_short_circuit() -> None:
    def _fn() -> None:
        raise RuntimeError("fail")

    def _on_error(_ex: Exception) -> tuple[bool, bool]:
        return True, False

    assert retry(3, _fn, _on_error) is None


def test_classify_ticket_complete() -> None:
    assert classify_ticket_complete(0) == TicketStatus.INCOMPLETE
    assert classify_ticket_complete("1") == TicketStatus.COMPLETE
    assert classify_ticket_complete(2) == TicketStatus.INVALID
