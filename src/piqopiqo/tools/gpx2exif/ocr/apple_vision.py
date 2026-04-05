"""Apple Vision clock OCR provider."""

from __future__ import annotations

import re

_TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")


class AppleVisionClockOcr:
    def extract_clock_time(self, *, photo_path: str) -> str:
        """Return the first OCR item matching HH:MM:SS."""
        return self._extract_clock_time_macos(photo_path=photo_path)

    def _extract_clock_time_macos(self, *, photo_path: str) -> str:
        import Cocoa
        import Vision

        input_url = Cocoa.NSURL.fileURLWithPath_(photo_path)
        captured_text: list[str] = []
        callback_errors: list[str] = []

        def completion_handler(request, error) -> None:
            if error:
                callback_errors.append(str(error))
                return

            observations = request.results() or []
            for observation in observations:
                top_candidates = observation.topCandidates_(1)
                if not top_candidates:
                    continue
                captured_text.append(top_candidates[0].string().strip())

        request = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(
            completion_handler
        )
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        # TODO set in settings
        request.setRecognitionLanguages_(["fr-FR", "en-US"])

        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
            input_url, None
        )
        success, error = handler.performRequests_error_([request], None)
        if not success:
            raise RuntimeError(str(error))
        if callback_errors:
            raise RuntimeError(callback_errors[0])

        for text in captured_text:
            if _TIME_PATTERN.search(text):
                return text

        raise RuntimeError("No time found in photo: expected HH:MM:SS clock format")
