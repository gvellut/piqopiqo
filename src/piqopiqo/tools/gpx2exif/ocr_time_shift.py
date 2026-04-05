"""Clock OCR dispatch and time-shift extraction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from piqopiqo.model import TimeShiftOcrProvider
from piqopiqo.ssf.settings_state import (
    RuntimeSettingKey,
    UserSettingKey,
    get_runtime_setting,
    get_user_setting,
)

from .ocr import apple_vision, gcp_vision
from .time_shift import format_time_shift


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


def get_time_shift_ocr_provider() -> TimeShiftOcrProvider:
    return get_runtime_setting(RuntimeSettingKey.OCR_TIME_SHIFT_PROVIDER)


def get_time_shift_ocr_provider_display_name() -> str:
    provider = get_time_shift_ocr_provider()
    if provider == TimeShiftOcrProvider.APPLE_VISION:
        return "Apple Vision"
    return "Google Cloud Vision"


def _build_time_shift_ocr(
    *,
    provider: TimeShiftOcrProvider,
):
    if provider == TimeShiftOcrProvider.APPLE_VISION:
        return apple_vision.AppleVisionClockOcr()

    gcp_project = str(get_user_setting(UserSettingKey.GCP_PROJECT) or "")
    gcp_sa_key_path = str(get_user_setting(UserSettingKey.GCP_SA_KEY_PATH) or "")
    return gcp_vision.GcpVisionClockOcr(
        gcp_project=gcp_project,
        gcp_sa_key_path=gcp_sa_key_path,
    )


def extract_time_shift_from_photo(
    *,
    photo_path: str,
    exif_time: datetime,
) -> tuple[str, str]:
    """Extract clock time from a photo and return clock text + canonical shift."""
    if exif_time.tzinfo is None:
        exif_utc = exif_time.replace(tzinfo=UTC)
    else:
        exif_utc = exif_time.astimezone(UTC)

    provider = get_time_shift_ocr_provider()
    ocr = _build_time_shift_ocr(
        provider=provider,
    )
    clock_text = ocr.extract_clock_time(photo_path=photo_path)

    clock_utc = _find_most_likely_datetime(exif_utc, clock_text)
    delta = clock_utc - exif_utc
    return clock_text, format_time_shift(delta)
