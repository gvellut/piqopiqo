"""Tests for keyword parsing and normalization helpers."""

from __future__ import annotations

from piqopiqo.keyword_utils import normalize_keywords


def test_normalize_keywords_drops_empty_tokens_and_duplicates() -> None:
    assert normalize_keywords("alpha,, beta, , ALPHA") == "alpha, beta"


def test_normalize_keywords_deduplicates_case_insensitively() -> None:
    assert normalize_keywords("Paris, paris, PARIS, Lyon") == "Paris, Lyon"


def test_normalize_keywords_returns_none_for_empty_keywords() -> None:
    assert normalize_keywords(" , , ") is None


def test_normalize_keywords_preserves_quoted_commas() -> None:
    assert normalize_keywords('one, "two,three"') == 'one, "two,three"'
