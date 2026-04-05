"""Tests for OCR provider dispatch in GPX time-shift extraction."""

from __future__ import annotations

from datetime import UTC, datetime

from piqopiqo.ssf.settings_state import (
    UserSettingKey,
    init_qsettings_store,
    set_user_setting,
)
import piqopiqo.tools.gpx2exif.ocr_time_shift as ocr_time_shift


def test_extract_time_shift_uses_gcp_provider_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PIQO_OCR_TIME_SHIFT_PROVIDER", raising=False)
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.GCP_PROJECT, "project-a")
    set_user_setting(UserSettingKey.GCP_SA_KEY_PATH, "/tmp/key.json")

    calls: list[tuple[str, str, str]] = []

    class _GcpVisionClockOcrStub:
        def __init__(self, *, gcp_project: str, gcp_sa_key_path: str) -> None:
            self._gcp_project = gcp_project
            self._gcp_sa_key_path = gcp_sa_key_path

        def extract_clock_time(self, *, photo_path: str) -> str:
            calls.append((photo_path, self._gcp_project, self._gcp_sa_key_path))
            return "12:00:05"

    class _AppleVisionClockOcrStub:
        def extract_clock_time(self, *, photo_path: str) -> str:
            raise AssertionError(f"Unexpected Apple OCR for {photo_path}")

    monkeypatch.setattr(
        ocr_time_shift.gcp_vision,
        "GcpVisionClockOcr",
        _GcpVisionClockOcrStub,
    )
    monkeypatch.setattr(
        ocr_time_shift.apple_vision,
        "AppleVisionClockOcr",
        _AppleVisionClockOcrStub,
    )

    clock_text, shift = ocr_time_shift.extract_time_shift_from_photo(
        photo_path="/tmp/clock.jpg",
        exif_time=datetime(2026, 4, 5, 12, 0, 0, tzinfo=UTC),
    )

    assert calls == [("/tmp/clock.jpg", "project-a", "/tmp/key.json")]
    assert clock_text == "12:00:05"
    assert shift == "5s"


def test_extract_time_shift_uses_apple_provider_when_selected(monkeypatch) -> None:
    monkeypatch.setenv("PIQO_OCR_TIME_SHIFT_PROVIDER", "APPLE_VISION")
    init_qsettings_store(dyn=True)

    calls: list[str] = []

    class _AppleVisionClockOcrStub:
        def extract_clock_time(self, *, photo_path: str) -> str:
            calls.append(photo_path)
            return "06:00:48"

    class _GcpVisionClockOcrStub:
        def __init__(self, *, gcp_project: str, gcp_sa_key_path: str) -> None:
            raise AssertionError(
                f"Unexpected GCP OCR init for {gcp_project} {gcp_sa_key_path}"
            )

    monkeypatch.setattr(
        ocr_time_shift.apple_vision,
        "AppleVisionClockOcr",
        _AppleVisionClockOcrStub,
    )
    monkeypatch.setattr(
        ocr_time_shift.gcp_vision,
        "GcpVisionClockOcr",
        _GcpVisionClockOcrStub,
    )

    clock_text, shift = ocr_time_shift.extract_time_shift_from_photo(
        photo_path="/tmp/clock.jpg",
        exif_time=datetime(2026, 4, 5, 6, 0, 50, tzinfo=UTC),
    )

    assert calls == ["/tmp/clock.jpg"]
    assert clock_text == "06:00:48"
    assert shift == "-2s"
