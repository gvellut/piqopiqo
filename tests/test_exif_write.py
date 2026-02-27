"""Tests for EXIF tag building helpers."""

from __future__ import annotations

from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.exif_write import build_exif_tags


def test_build_exif_tags_includes_manual_lens_fields():
    tags = build_exif_tags(
        {
            DBFields.MANUAL_LENS_MAKE: "Samyang",
            DBFields.MANUAL_LENS_MODEL: "Samyang 12mm f/2.0 NCS CS",
            DBFields.MANUAL_FOCAL_LENGTH: "12,5",
            DBFields.MANUAL_FOCAL_LENGTH_35MM: "18",
        }
    )

    assert tags["lensmake"] == "Samyang"
    assert tags["lensmodel"] == "Samyang 12mm f/2.0 NCS CS"
    assert tags["focallength"] == "12.5"
    assert tags["lens"] == "12.5 mm"
    assert tags["LensInfo"] == "12.5mm f/?"
    assert tags["FocalLengthIn35mmFormat"] == "18"


def test_build_exif_tags_skips_invalid_manual_focal_values():
    tags = build_exif_tags(
        {
            DBFields.MANUAL_LENS_MAKE: "Sigma",
            DBFields.MANUAL_LENS_MODEL: "Sigma 18-35mm F1.8",
            DBFields.MANUAL_FOCAL_LENGTH: "invalid",
            DBFields.MANUAL_FOCAL_LENGTH_35MM: "",
        }
    )

    assert tags["lensmake"] == "Sigma"
    assert tags["lensmodel"] == "Sigma 18-35mm F1.8"
    assert "focallength" not in tags
    assert "lens" not in tags
    assert "LensInfo" not in tags
    assert "FocalLengthIn35mmFormat" not in tags
