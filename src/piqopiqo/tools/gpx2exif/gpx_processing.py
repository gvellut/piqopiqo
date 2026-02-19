"""GPX loading, position interpolation, and KML output helpers."""

from __future__ import annotations

from bisect import bisect_left
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import re
from xml.etree import ElementTree

from attrs import define
import gpxpy
import simplekml

from .constants import KML_THUMBNAIL_SIZE


@define(frozen=True)
class GpxPoint:
    time: datetime
    latitude: float
    longitude: float


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_iso_datetime(text: str) -> datetime:
    normalized = text.strip().replace("Z", "+00:00")
    return _ensure_utc(datetime.fromisoformat(normalized))


def _load_gpx_with_gpxpy(gpx_path: str) -> list[list[GpxPoint]]:
    assert gpxpy is not None
    with open(gpx_path, encoding="utf-8") as gpx_file:
        gpx_data = gpxpy.parse(gpx_file)

    segments: list[list[GpxPoint]] = []
    for track in gpx_data.tracks:
        for segment in track.segments:
            points: list[GpxPoint] = []
            for point in segment.points:
                if point.time is None:
                    continue
                points.append(
                    GpxPoint(
                        time=_ensure_utc(point.time),
                        latitude=float(point.latitude),
                        longitude=float(point.longitude),
                    )
                )
            if points:
                points.sort(key=lambda row: row.time)
                segments.append(points)

    return segments


def _element_name(node: ElementTree.Element) -> str:
    if "}" in node.tag:
        return node.tag.split("}", 1)[1]
    return node.tag


def _load_gpx_with_xml(gpx_path: str) -> list[list[GpxPoint]]:
    root = ElementTree.parse(gpx_path).getroot()

    segments: list[list[GpxPoint]] = []
    for trkseg in root.iter():
        if _element_name(trkseg) != "trkseg":
            continue

        points: list[GpxPoint] = []
        for trkpt in trkseg:
            if _element_name(trkpt) != "trkpt":
                continue

            lat_raw = trkpt.attrib.get("lat")
            lon_raw = trkpt.attrib.get("lon")
            if lat_raw is None or lon_raw is None:
                continue

            time_text = None
            for child in trkpt:
                if _element_name(child) == "time" and child.text:
                    time_text = child.text
                    break
            if time_text is None:
                continue

            try:
                points.append(
                    GpxPoint(
                        time=_parse_iso_datetime(time_text),
                        latitude=float(lat_raw),
                        longitude=float(lon_raw),
                    )
                )
            except (TypeError, ValueError):
                continue

        if points:
            points.sort(key=lambda row: row.time)
            segments.append(points)

    return segments


def load_gpx_segments(gpx_path: str) -> list[list[GpxPoint]]:
    """Load all GPX track segments as sorted point sequences."""
    if gpxpy is not None:
        segments = _load_gpx_with_gpxpy(gpx_path)
    else:
        segments = _load_gpx_with_xml(gpx_path)

    if not segments:
        raise ValueError("No GPX track points found")

    return segments


def get_gpx_time_range(segments: list[list[GpxPoint]]) -> tuple[datetime, datetime]:
    starts = [segment[0].time for segment in segments if segment]
    ends = [segment[-1].time for segment in segments if segment]
    if not starts or not ends:
        raise ValueError("No GPX timestamps available")
    return min(starts), max(ends)


def compute_position(
    image_time_utc: datetime,
    segments: list[list[GpxPoint]],
    tolerance: timedelta,
) -> tuple[float, float] | None:
    """Compute a photo position from GPX segments using timestamp interpolation."""
    if image_time_utc.tzinfo is None:
        image_time = image_time_utc.replace(tzinfo=UTC)
    else:
        image_time = image_time_utc.astimezone(UTC)

    tol = abs(tolerance)

    for segment in segments:
        if not segment:
            continue

        timestamps = [point.time for point in segment]
        index = bisect_left(timestamps, image_time)

        if index < len(timestamps) and timestamps[index] == image_time:
            point = segment[index]
            return point.latitude, point.longitude

        if index == 0:
            delta = timestamps[0] - image_time
            if delta <= tol:
                first = segment[0]
                return first.latitude, first.longitude
            continue

        if index >= len(timestamps):
            delta = image_time - timestamps[-1]
            if delta <= tol:
                last = segment[-1]
                return last.latitude, last.longitude
            continue

        before = segment[index - 1]
        after = segment[index]
        gpx_gap = (after.time - before.time).total_seconds()
        if gpx_gap <= 0:
            return before.latitude, before.longitude

        image_gap = (image_time - before.time).total_seconds()
        ratio = image_gap / gpx_gap

        lat = before.latitude + (after.latitude - before.latitude) * ratio
        lon = before.longitude + (after.longitude - before.longitude) * ratio
        return lat, lon

    return None


def _file_uri(path: str) -> str:
    text = path
    if os.name == "nt":
        text = "/" + text.replace("\\", "/")
    return f"file://{text}"


def _kml_title(image_path: str) -> str:
    image_name = os.path.basename(image_path)
    return image_name


def _kml_description(image_path: str, kml_thumbnail_size: int) -> str:
    image_name = os.path.basename(image_path)
    src = _file_uri(image_path)
    return (
        "<![CDATA[\n"
        f"{image_name}<br/><br/>\n"
        f'<img src="{src}" width="{int(kml_thumbnail_size)}" />\n'
        "]]>"
    )


def write_kml(
    positions: list[tuple[tuple[float, float], str]],
    kml_path: str,
    kml_thumbnail_size: int = KML_THUMBNAIL_SIZE,
) -> None:
    """Write KML output with one placemark per georeferenced photo."""
    path = Path(kml_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    kml = simplekml.Kml()
    style = simplekml.Style()
    style.balloonstyle.text = "$[description]"
    for (lat, lon), image_path in positions:
        title = _kml_title(image_path)
        desc = _kml_description(image_path, kml_thumbnail_size)
        point = kml.newpoint(name=title, description=desc, coords=[(lon, lat)])
        point.style = style
    kml.save(str(path))


def to_relative_folder(root_folder: str, source_folder: str) -> str:
    rel = os.path.relpath(source_folder, root_folder)
    if rel in ("", "."):
        return "."
    return rel


def to_relative_folder_token(root_folder: str, source_folder: str) -> str:
    rel = to_relative_folder(root_folder, source_folder)
    if rel == ".":
        return "root"

    token = rel.replace("/", "_").replace("\\", "_")
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", token)
    token = token.strip("._")
    return token or "root"


def build_kml_output_path(root_folder: str, source_folder: str, kml_folder: str) -> str:
    root_name = os.path.basename(os.path.normpath(root_folder)) or "photos"
    token = to_relative_folder_token(root_folder, source_folder)
    file_name = f"photos_{root_name}_{token}.kml"

    base_folder = kml_folder.strip() if kml_folder else ""
    if not base_folder:
        base_folder = root_folder

    return str(Path(base_folder) / file_name)
