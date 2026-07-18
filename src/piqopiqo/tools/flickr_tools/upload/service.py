"""Pure helpers for Flickr upload workflows."""

from __future__ import annotations

from enum import Enum, auto

from piqopiqo.keyword_utils import parse_keywords
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.tools.flickr_utils import format_flickr_tags, retry

__all__ = [
    "TicketStatus",
    "classify_ticket_complete",
    "format_flickr_tags",
    "format_flickr_tags_from_db_keywords",
    "generate_timestamps",
    "has_required_flickr_upload_metadata",
    "retry",
]


class TicketStatus(Enum):
    INCOMPLETE = auto()
    COMPLETE = auto()
    INVALID = auto()


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


def classify_ticket_complete(value: object) -> TicketStatus:
    """Classify Flickr upload ticket completion value."""
    if value in (1, "1"):
        return TicketStatus.COMPLETE
    if value in (2, "2"):
        return TicketStatus.INVALID
    return TicketStatus.INCOMPLETE
