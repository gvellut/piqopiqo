"""Shared Flickr album date ordering and backup helpers."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import json
import os
from pathlib import Path
import tempfile

from attrs import define

BACKUP_FOLDER_NAME = "flickr-album-orders"
BACKUP_PREFIX = "flickr-album-order-"


@define(frozen=True)
class FlickrAlbumOrderEntry:
    album_id: str
    title: str


def album_title(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("_content") or "").strip()
    return str(value or "").strip()


def _taken_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def modal_photo_date(photos: list[object]) -> tuple[date | None, int]:
    """Return the modal taken date and count of photos with invalid dates."""
    counts: Counter[date] = Counter()
    first_seen: list[date] = []
    invalid_count = 0
    for photo in photos:
        if not isinstance(photo, dict):
            invalid_count += 1
            continue
        taken_date = _taken_date(photo.get("datetaken"))
        if taken_date is None:
            invalid_count += 1
            continue
        if taken_date not in counts:
            first_seen.append(taken_date)
        counts[taken_date] += 1
    if not counts:
        return None, invalid_count
    highest = max(counts.values())
    return next(
        value for value in first_seen if counts[value] == highest
    ), invalid_count


def build_reordered_album_ids(
    albums: list[FlickrAlbumOrderEntry],
    modal_dates: dict[str, date],
    *,
    from_album_id: str = "",
) -> list[str]:
    """Build the complete album order, sorting only the requested prefix."""
    if not albums:
        return []
    selected_count = len(albums)
    if from_album_id:
        for index, album in enumerate(albums):
            if album.album_id == from_album_id:
                selected_count = index + 1
                break
        else:
            raise ValueError(f"Album {from_album_id} is not in your album list.")

    selected = albums[:selected_count]
    tail = albums[selected_count:]
    ordered = sorted(
        selected,
        key=lambda album: modal_dates[album.album_id],
        reverse=True,
    )
    return [album.album_id for album in (*ordered, *tail)]


def save_album_order_backup(
    album_ids: list[str],
    *,
    support_dir: str | Path,
    keep: int,
    now: datetime | None = None,
) -> tuple[Path, list[str]]:
    """Atomically save an ID-array backup and prune older tool backups."""
    backup_dir = Path(support_dir) / BACKUP_FOLDER_NAME
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    target = backup_dir / f"{BACKUP_PREFIX}{stamp}.json"
    suffix = 2
    while target.exists():
        target = backup_dir / f"{BACKUP_PREFIX}{stamp}-{suffix}.json"
        suffix += 1

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=backup_dir,
            prefix=".flickr-album-order-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            json.dump([str(album_id) for album_id in album_ids], stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            temp_path = stream.name
        os.replace(temp_path, target)
    except Exception:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass
        raise

    warnings: list[str] = []
    dated_backups: list[tuple[int, str, Path]] = []
    for path in backup_dir.glob(f"{BACKUP_PREFIX}*.json"):
        try:
            dated_backups.append((path.stat().st_mtime_ns, path.name, path))
        except OSError as ex:
            warnings.append(f"Could not inspect old backup {path.name}: {ex}")
    backups = [row[2] for row in sorted(dated_backups, reverse=True)]
    for old_path in backups[max(1, int(keep)) :]:
        try:
            old_path.unlink()
        except OSError as ex:
            warnings.append(f"Could not remove old backup {old_path.name}: {ex}")
    return target, warnings
