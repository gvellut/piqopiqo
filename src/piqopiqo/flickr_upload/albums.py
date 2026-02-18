"""Album resolution helpers for Flickr upload workflows."""

from __future__ import annotations

from collections.abc import Mapping
import re

from attrs import define

from .constants import API_RETRIES, QUICK_TIMEOUT_S
from .service import retry


@define(frozen=True)
class FlickrAlbumInfo:
    album_id: str
    title: str = ""
    user_nsid: str = ""
    url: str = ""


@define(frozen=True)
class FlickrAlbumPlan:
    raw_text: str = ""
    album_id: str = ""
    album_title: str = ""
    user_nsid: str = ""
    album_url: str = ""
    is_create: bool = False

    def normalized_raw_text(self) -> str:
        return str(self.raw_text).strip()

    def has_input(self) -> bool:
        return bool(self.normalized_raw_text())

    def is_existing_album(self) -> bool:
        return bool(self.album_id) and not self.is_create

    def to_dict(self) -> dict[str, object]:
        return {
            "raw_text": self.raw_text,
            "album_id": self.album_id,
            "album_title": self.album_title,
            "user_nsid": self.user_nsid,
            "album_url": self.album_url,
            "is_create": self.is_create,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> FlickrAlbumPlan | None:
        if not data:
            return None
        return cls(
            raw_text=str(data.get("raw_text") or ""),
            album_id=str(data.get("album_id") or ""),
            album_title=str(data.get("album_title") or ""),
            user_nsid=str(data.get("user_nsid") or ""),
            album_url=str(data.get("album_url") or ""),
            is_create=bool(data.get("is_create")),
        )


def build_album_url(user_nsid: str, album_id: str) -> str:
    nsid = str(user_nsid).strip()
    aid = str(album_id).strip()
    if not nsid or not aid:
        return ""
    return f"https://flickr.com/photos/{nsid}/albums/{aid}"


def extract_album_id(value: str) -> str:
    """Extract Flickr album ID from numeric ID or supported Flickr URL."""
    text = str(value or "").strip()
    if not text:
        raise ValueError("Album value is empty.")

    if text.isdigit():
        return text

    m = re.search(r"flickr\.com/photos/[^/]+/(?:albums|sets)/(\d+)", text)
    if m:
        return str(m.group(1))

    raise ValueError(f"Not a valid Flickr album URL or ID: {text}")


def _extract_title(value: object) -> str:
    if isinstance(value, dict):
        content = value.get("_content")
        if content is None:
            return ""
        return str(content).strip()
    if value is None:
        return ""
    return str(value).strip()


def fetch_album_info(flickr, album_id: str) -> FlickrAlbumInfo:
    """Fetch album info and return ID/title/owner NSID/url."""
    aid = str(album_id or "").strip()
    if not aid:
        raise ValueError("Album ID is empty.")

    response = retry(
        API_RETRIES,
        lambda: flickr.photosets.getInfo(photoset_id=aid, timeout=QUICK_TIMEOUT_S),
    )
    if not isinstance(response, dict):
        raise ValueError(f"Album '{aid}' was not found on Flickr.")

    photoset = response.get("photoset")
    if not isinstance(photoset, dict):
        raise ValueError(f"Album '{aid}' was not found on Flickr.")

    resolved_id = str(photoset.get("id") or aid).strip()
    title = _extract_title(photoset.get("title"))
    user_nsid = str(photoset.get("owner") or "").strip()
    return FlickrAlbumInfo(
        album_id=resolved_id,
        title=title,
        user_nsid=user_nsid,
        url=build_album_url(user_nsid, resolved_id),
    )


def find_album_by_exact_title(flickr, title: str) -> FlickrAlbumInfo | None:
    """Find first exact title match from first page of albums list."""
    wanted = str(title or "").strip()
    if not wanted:
        return None

    response = retry(
        API_RETRIES,
        lambda: flickr.photosets.getList(per_page=100, page=1, timeout=QUICK_TIMEOUT_S),
    )
    if not isinstance(response, dict):
        return None

    photosets_container = response.get("photosets")
    if not isinstance(photosets_container, dict):
        return None

    raw_sets = photosets_container.get("photoset")
    if raw_sets is None:
        return None
    if isinstance(raw_sets, list):
        photosets = raw_sets
    else:
        photosets = [raw_sets]

    for photoset in photosets:
        if not isinstance(photoset, dict):
            continue
        current_title = _extract_title(photoset.get("title"))
        if current_title != wanted:
            continue

        album_id = str(photoset.get("id") or "").strip()
        user_nsid = str(photosets_container.get("owner") or "").strip()
        if not album_id:
            continue
        return FlickrAlbumInfo(
            album_id=album_id,
            title=current_title,
            user_nsid=user_nsid,
            url=build_album_url(user_nsid, album_id),
        )

    return None


def resolve_album_plan(
    flickr,
    album_text: str,
    *,
    cached_plan: FlickrAlbumPlan | None = None,
) -> FlickrAlbumPlan:
    """Resolve user album input into an existing-album or create-album plan."""
    raw_text = str(album_text or "").strip()
    if not raw_text:
        return FlickrAlbumPlan()

    if (
        cached_plan is not None
        and cached_plan.is_existing_album()
        and cached_plan.normalized_raw_text() == raw_text
    ):
        return cached_plan

    try:
        album_id = extract_album_id(raw_text)
    except ValueError:
        found = find_album_by_exact_title(flickr, raw_text)
        if found is None:
            return FlickrAlbumPlan(
                raw_text=raw_text,
                album_title=raw_text,
                is_create=True,
            )
        return FlickrAlbumPlan(
            raw_text=raw_text,
            album_id=found.album_id,
            album_title=found.title,
            user_nsid=found.user_nsid,
            album_url=found.url,
            is_create=False,
        )

    info = fetch_album_info(flickr, album_id)
    return FlickrAlbumPlan(
        raw_text=raw_text,
        album_id=info.album_id,
        album_title=info.title,
        user_nsid=info.user_nsid,
        album_url=info.url,
        is_create=False,
    )
