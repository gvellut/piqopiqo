"""Pure helpers for Flickr upload workflows."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto
import time

from piqopiqo.keyword_utils import parse_keywords
from piqopiqo.metadata.db_fields import DBFields

from .constants import API_RETRY_DELAY_S


class TicketStatus(Enum):
    INCOMPLETE = auto()
    COMPLETE = auto()
    INVALID = auto()


def format_flickr_tags(tags: list[str] | None) -> str | None:
    """Format tags for Flickr API: quoted and space-separated."""
    if not tags:
        return None

    cleaned: list[str] = []
    for tag in tags:
        text = str(tag).strip()
        if not text:
            continue
        if '"' in text:
            raise ValueError('" should not be in a Flickr tag')
        cleaned.append(f'"{text}"')

    if not cleaned:
        return None

    return " ".join(cleaned)


def format_flickr_tags_from_db_keywords(db_keywords: str | None) -> str | None:
    """Format Flickr tags from DB keyword string."""
    if not db_keywords:
        return None
    tags = parse_keywords(str(db_keywords))
    return format_flickr_tags(tags)


def has_required_flickr_upload_metadata(db_metadata: dict | None) -> bool:
    """Return whether metadata has a non-empty title and at least one valid keyword."""
    if not isinstance(db_metadata, dict):
        return False

    title = db_metadata.get(DBFields.TITLE)
    if not str(title or "").strip():
        return False

    tags = format_flickr_tags_from_db_keywords(db_metadata.get(DBFields.KEYWORDS))
    return bool(tags)


def generate_timestamps(now_ts: int, num_photos: int) -> list[int]:
    """Generate stable upload timestamps to preserve visible ordering on Flickr."""
    count = max(0, int(num_photos))
    # so not in the future (Flickr error) : but not too much in the past to prevent
    # 2 uploads from having same time (if the other upload was manual for ex)
    base = int(now_ts) - 2 * count
    return [base + i for i in range(count)]


def retry[T](
    num_retries: int,
    func: Callable[[], T],
    error_callback: Callable[[Exception], tuple[bool, bool]] | None = None,
) -> T | None:
    """Retry helper aligned with flickr_api_utils semantics.

    Returns early with None when error_callback asks for return_now.
    Raises when retries are exhausted or callback asks for raise_now.
    """
    remaining = max(1, int(num_retries))
    while remaining > 0:
        try:
            return func()
        except Exception as ex:
            if error_callback is not None:
                return_now, raise_now = error_callback(ex)
                if return_now:
                    return None
                if raise_now:
                    raise

            remaining -= 1
            if remaining > 0:
                time.sleep(API_RETRY_DELAY_S)
                continue
            raise

    return None


def classify_ticket_complete(value: object) -> TicketStatus:
    """Classify Flickr upload ticket completion value."""
    if value in (1, "1"):
        return TicketStatus.COMPLETE
    if value in (2, "2"):
        return TicketStatus.INVALID
    return TicketStatus.INCOMPLETE
