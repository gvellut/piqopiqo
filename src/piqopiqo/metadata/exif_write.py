"""EXIF write helpers shared by UI workflows and background operations."""

from __future__ import annotations

from datetime import datetime

from piqopiqo import __version__ as piqopiqo_version
from piqopiqo.keyword_utils import parse_keywords
from piqopiqo.metadata.db_fields import DB_TO_EXIF_WRITE_MAPPING, DBFields
from piqopiqo.ssf.settings_state import APP_NAME


def _normalize_decimal_text(value: object) -> str | None:
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace(",", ".")
    try:
        float(normalized)
    except ValueError:
        return None
    return normalized


def _apply_manual_lens_tags(db_metadata: dict, tags: dict[str, object]) -> None:
    lens_make = str(db_metadata.get(DBFields.MANUAL_LENS_MAKE) or "").strip()
    if lens_make:
        tags["lensmake"] = lens_make

    lens_model = str(db_metadata.get(DBFields.MANUAL_LENS_MODEL) or "").strip()
    if lens_model:
        tags["lensmodel"] = lens_model

    focal_length = _normalize_decimal_text(
        db_metadata.get(DBFields.MANUAL_FOCAL_LENGTH)
    )
    if focal_length is not None:
        tags["focallength"] = focal_length
        tags["lens"] = f"{focal_length} mm"
        tags["LensInfo"] = f"{focal_length}mm f/?"

    focal_length_35mm = _normalize_decimal_text(
        db_metadata.get(DBFields.MANUAL_FOCAL_LENGTH_35MM)
    )
    if focal_length_35mm is not None:
        tags["FocalLengthIn35mmFormat"] = focal_length_35mm


def build_exif_tags(db_metadata: dict) -> dict:
    """Build EXIF tags dict from DB metadata using the write mapping."""

    tags: dict[str, object] = {}

    for db_field, exif_config in DB_TO_EXIF_WRITE_MAPPING.items():
        value = db_metadata.get(db_field)
        if value is None:
            continue

        if db_field == DBFields.TIME_TAKEN:
            if isinstance(value, datetime):
                value = value.strftime("%Y:%m:%d %H:%M:%S")
            elif isinstance(value, str) and value:
                try:
                    dt = datetime.fromisoformat(value.replace(" ", "T"))
                    value = dt.strftime("%Y:%m:%d %H:%M:%S")
                except ValueError:
                    pass

        if db_field == DBFields.KEYWORDS and isinstance(value, str):
            value = parse_keywords(value)
            if not value:
                continue

        if db_field == DBFields.LATITUDE and value is not None:
            try:
                lat = float(value)
                if lat < 0:
                    tags["EXIF:GPSLatitudeRef"] = "S"
                    value = abs(lat)
                else:
                    tags["EXIF:GPSLatitudeRef"] = "N"
            except (ValueError, TypeError):
                continue

        if db_field == DBFields.LONGITUDE and value is not None:
            try:
                lon = float(value)
                if lon < 0:
                    tags["EXIF:GPSLongitudeRef"] = "W"
                    value = abs(lon)
                else:
                    tags["EXIF:GPSLongitudeRef"] = "E"
            except (ValueError, TypeError):
                continue

        if isinstance(exif_config, list):
            for tag in exif_config:
                tags[tag] = value
        else:
            tags[exif_config] = value

    _apply_manual_lens_tags(db_metadata, tags)

    now = datetime.now().strftime("%Y:%m:%d %H:%M:%S")
    software_agent = f"{APP_NAME} v{piqopiqo_version}"

    # TODO Add simple history
    tags["XMP-xmpMM:HistoryAction"] = "saved"
    tags["XMP-xmpMM:HistoryWhen"] = now
    tags["XMP-xmpMM:HistorySoftwareAgent"] = software_agent

    tags["XMP-xmp:ProcessingSoftware"] = software_agent
    tags["XMP-xmp:MetadataDate"] = now

    return tags
