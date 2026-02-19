"""Tests for GPX time-shift parsing and formatting."""

from datetime import timedelta

import pytest

from piqopiqo.tools.gpx2exif.time_shift import (
    format_time_shift,
    is_valid_time_shift,
    parse_time_shift,
)


def test_parse_hms_expression() -> None:
    assert parse_time_shift("1h16m5s") == timedelta(hours=1, minutes=16, seconds=5)
    assert parse_time_shift("-59m9s") == timedelta(minutes=-59, seconds=-9)


def test_parse_time_range_expression() -> None:
    assert parse_time_shift("16:18:56-17:15:03") == timedelta(minutes=-56, seconds=-7)


def test_format_time_shift() -> None:
    assert format_time_shift(timedelta(0)) == "0"
    assert format_time_shift(timedelta(hours=-1, minutes=-16, seconds=-5)) == "-1h16m5s"
    assert format_time_shift(timedelta(minutes=59, seconds=9)) == "59m9s"
    assert format_time_shift(timedelta(seconds=3)) == "3s"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", False),
        ("abc", False),
        ("-", False),
        ("10m", True),
        ("-1h2m", True),
        ("16:18:56-17:15:03", True),
    ],
)
def test_is_valid_time_shift(value: str, expected: bool) -> None:
    assert is_valid_time_shift(value) is expected
