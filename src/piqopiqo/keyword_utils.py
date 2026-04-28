"""Keyword parsing and formatting utilities.

Handles comma-separated keyword strings with support for quoted values
containing commas.
"""


def parse_keywords(text: str) -> list[str]:
    """Parse a comma-separated keyword string, respecting quoted values.

    Args:
        text: Comma-separated keywords like 'word1, word2, "word, with comma"'

    Returns:
        List of individual keywords (quotes stripped from quoted values).
        Double quotes within keywords are auto-removed.
    """
    if not text or not text.strip():
        return []

    keywords = []
    current: list[str] = []
    in_quotes = False

    for char in text:
        if char == '"':
            in_quotes = not in_quotes
            # Don't add the quote character to current
        elif char == "," and not in_quotes:
            kw = "".join(current).strip()
            if kw:
                keywords.append(kw)
            current = []
        else:
            current.append(char)

    # Handle last keyword
    kw = "".join(current).strip()
    if kw:
        keywords.append(kw)

    return keywords


def format_keywords(keywords: list[str]) -> str:
    """Format a list of keywords to comma-separated string.

    Keywords containing commas are quoted. Double quotes in keyword values
    are auto-removed.

    Args:
        keywords: List of keyword strings

    Returns:
        Comma-separated string with appropriate quoting
    """
    formatted = []
    for kw in keywords:
        # Remove any double quotes from the keyword
        clean_kw = kw.replace('"', "")
        if "," in clean_kw:
            formatted.append(f'"{clean_kw}"')
        else:
            formatted.append(clean_kw)
    return ", ".join(formatted)


def normalize_keyword_list(keywords: list[str]) -> list[str]:
    """Clean keyword values and remove case-insensitive duplicates.

    Empty values are dropped. For duplicates, the first spelling and position
    are kept.
    """
    normalized: list[str] = []
    seen: set[str] = set()

    for kw in keywords:
        clean_kw = kw.replace('"', "").strip()
        if not clean_kw:
            continue

        key = clean_kw.casefold()
        if key in seen:
            continue

        seen.add(key)
        normalized.append(clean_kw)

    return normalized


def normalize_keywords(text: str | None) -> str | None:
    """Normalize a comma-separated keyword string for DB storage."""
    if text is None:
        return None

    keywords = normalize_keyword_list(parse_keywords(text))
    if not keywords:
        return None

    return format_keywords(keywords)


def validate_keywords_balanced(text: str) -> bool:
    """Check if quotes are balanced in keyword string.

    Args:
        text: Keyword string to validate

    Returns:
        True if quotes are balanced, False otherwise
    """
    quote_count = text.count('"')
    return quote_count % 2 == 0
