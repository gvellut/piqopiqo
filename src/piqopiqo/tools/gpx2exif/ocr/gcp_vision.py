"""Google Cloud Vision clock OCR provider."""

from __future__ import annotations

import os
import re

_TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")


class GcpVisionClockOcr:
    def __init__(self, *, gcp_project: str, gcp_sa_key_path: str) -> None:
        self._gcp_project = gcp_project
        self._gcp_sa_key_path = gcp_sa_key_path

    def _configure_gcp(self) -> None:
        if self._gcp_sa_key_path.strip():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = (
                self._gcp_sa_key_path.strip()
            )
        if self._gcp_project.strip():
            os.environ["GOOGLE_CLOUD_PROJECT"] = self._gcp_project.strip()

    def extract_clock_time(self, *, photo_path: str) -> str:
        """Return the first OCR item matching HH:MM:SS."""
        from google.cloud import vision

        self._configure_gcp()

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
