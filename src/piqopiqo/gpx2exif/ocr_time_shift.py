"""Clock OCR via GCP Vision and time-shift extraction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
import re

from .time_shift import format_time_shift

_TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")


def _configure_gcp(project: str, sa_key_path: str) -> None:
    if sa_key_path.strip():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = sa_key_path.strip()
    if project.strip():
        os.environ["GOOGLE_CLOUD_PROJECT"] = project.strip()


def _extract_clock_time_with_vision(photo_path: str) -> str:
    # Keep import local to avoid expensive startup and optional import failures.
    from google.cloud import vision

    client = vision.ImageAnnotatorClient()
    with open(photo_path, "rb") as image_file:
        image = vision.Image(content=image_file.read())

    response = client.text_detection(
        image=image,
        image_context={"language_hints": ["en"]},
    )
    if response.error.message:
        raise RuntimeError(response.error.message)

    for annotation in response.text_annotations:
        text = annotation.description.strip()
        if _TIME_PATTERN.search(text):
            return text

    raise RuntimeError("No time found in photo: expected HH:MM:SS clock format")


def _find_most_likely_datetime(
    reference_utc: datetime, ambiguous_time: str
) -> datetime:
    ref = reference_utc.astimezone(UTC)
    base_time = datetime.strptime(ambiguous_time, "%H:%M:%S").time()
    alternatives = [base_time, base_time.replace(hour=(base_time.hour + 12) % 24)]

    candidates: list[datetime] = []
    for day_delta in (-1, 0, 1):
        target_date = ref.date() + timedelta(days=day_delta)
        for candidate_time in alternatives:
            candidates.append(datetime.combine(target_date, candidate_time, tzinfo=UTC))

    return min(candidates, key=lambda dt: abs(dt - ref))


def extract_time_shift_from_photo(
    *,
    photo_path: str,
    exif_time: datetime,
    gcp_project: str,
    gcp_sa_key_path: str,
) -> str:
    """Extract clock time from a photo and return canonical shift text."""
    if exif_time.tzinfo is None:
        exif_utc = exif_time.replace(tzinfo=UTC)
    else:
        exif_utc = exif_time.astimezone(UTC)

    _configure_gcp(gcp_project, gcp_sa_key_path)
    clock_text = _extract_clock_time_with_vision(photo_path)
    clock_utc = _find_most_likely_datetime(exif_utc, clock_text)
    delta = clock_utc - exif_utc
    return format_time_shift(delta)
