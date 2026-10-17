"""Tests for EXIF tag building helpers."""

from __future__ import annotations

from pathlib import Path
import shutil
import struct

import exiftool
from PIL import Image, TiffImagePlugin
import pytest

from piqopiqo.background.media_worker import run_write_exif_task
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.exif_write import build_exif_tags
from piqopiqo.tools.flickr_tools.upload.media_worker import _write_exif_to_temp_file


def test_build_exif_tags_includes_manual_lens_fields():
    tags = build_exif_tags({
        DBFields.MANUAL_LENS_MAKE: "Samyang",
        DBFields.MANUAL_LENS_MODEL: "Samyang 12mm f/2.0 NCS CS",
        DBFields.MANUAL_FOCAL_LENGTH: "12,5",
        DBFields.MANUAL_FOCAL_LENGTH_35MM: "18",
    })

    assert tags["lensmake"] == "Samyang"
    assert tags["lensmodel"] == "Samyang 12mm f/2.0 NCS CS"
    assert tags["focallength"] == "12.5"
    assert tags["lens"] == "12.5 mm"
    assert tags["LensInfo"] == "12.5 12.5 undef undef"
    assert tags["MinFocalLength"] == "12.5"
    assert tags["MaxFocalLength"] == "12.5"
    assert tags["FocalLengthIn35mmFormat"] == "18"


def test_build_exif_tags_skips_invalid_manual_focal_values():
    tags = build_exif_tags({
        DBFields.MANUAL_LENS_MAKE: "Sigma",
        DBFields.MANUAL_LENS_MODEL: "Sigma 18-35mm F1.8",
        DBFields.MANUAL_FOCAL_LENGTH: "invalid",
        DBFields.MANUAL_FOCAL_LENGTH_35MM: "",
    })

    assert tags["lensmake"] == "Sigma"
    assert tags["lensmodel"] == "Sigma 18-35mm F1.8"
    assert "focallength" not in tags
    assert "lens" not in tags
    assert "LensInfo" not in tags
    assert "MinFocalLength" not in tags
    assert "MaxFocalLength" not in tags
    assert "FocalLengthIn35mmFormat" not in tags


@pytest.mark.parametrize("value", [None, "", " "])
def test_build_exif_tags_skips_absent_or_cleared_manual_lens_fields(value):
    metadata = {field: value for field in DBFields.MANUAL_LENS_FIELDS}
    for db_metadata in ({}, metadata):
        tags = build_exif_tags(db_metadata)

        assert not {
            "lensmake",
            "lensmodel",
            "focallength",
            "lens",
            "LensInfo",
            "MinFocalLength",
            "MaxFocalLength",
            "FocalLengthIn35mmFormat",
        }.intersection(tags)


def _write_lens_jpeg(path: Path, *, with_maker_notes: bool) -> None:
    exif = Image.Exif()
    exif[0x010F] = "FUJIFILM"
    exif[0x0110] = "X-S20"
    exif_ifd = {
        0x920A: TiffImagePlugin.IFDRational(21),
        0xA405: 32,
        0xA432: (
            TiffImagePlugin.IFDRational(21),
            TiffImagePlugin.IFDRational(21),
            TiffImagePlugin.IFDRational(0, 0),
            TiffImagePlugin.IFDRational(0, 0),
        ),
    }
    if with_maker_notes:
        # Fujifilm IFD offsets are relative to the start of the MakerNote.
        entries = [(0x1404, 21), (0x1405, 21)]
        data_offset = 12 + 2 + len(entries) * 12 + 4
        maker_note = b"FUJIFILM" + struct.pack("<IH", 12, len(entries))
        maker_note += b"".join(
            struct.pack("<HHII", tag, 10, 1, data_offset + index * 8)
            for index, (tag, _) in enumerate(entries)
        )
        maker_note += struct.pack("<I", 0)
        maker_note += b"".join(struct.pack("<ii", value, 1) for _, value in entries)
        exif_ifd[0x927C] = maker_note
    exif[0x8769] = exif_ifd
    Image.new("RGB", (24, 16), color="white").save(path, "JPEG", exif=exif)


@pytest.mark.parametrize("workflow", ["save_exif", "flickr"])
@pytest.mark.parametrize("with_maker_notes", [False, True])
@pytest.mark.parametrize(
    "focal_length,focal_length_35mm", [("40", "60"), ("12,5", "18")]
)
def test_manual_lens_exif_round_trip(
    tmp_path, monkeypatch, workflow, with_maker_notes, focal_length, focal_length_35mm
):
    exiftool_path = shutil.which("exiftool")
    if exiftool_path is None:
        pytest.skip("ExifTool is required for EXIF round-trip tests")

    source = tmp_path / "source.jpg"
    _write_lens_jpeg(source, with_maker_notes=with_maker_notes)
    original_bytes = source.read_bytes()
    with exiftool.ExifToolHelper(executable=exiftool_path, common_args=[]) as helper:
        before = helper.get_tags(
            str(source),
            ["LensInfo", "MinFocalLength", "MaxFocalLength"],
            params=["-G1", "-n"],
        )[0]
    assert before["ExifIFD:LensInfo"] == "21 21 undef undef"
    if with_maker_notes:
        assert before["FujiFilm:MinFocalLength"] == 21
        assert before["FujiFilm:MaxFocalLength"] == 21

    warnings = []
    original_set_tags = exiftool.ExifToolHelper.set_tags

    def record_write_warnings(helper, *args, **kwargs):
        result = original_set_tags(helper, *args, **kwargs)
        warnings.append(helper.last_stderr)
        return result

    monkeypatch.setattr(exiftool.ExifToolHelper, "set_tags", record_write_warnings)
    metadata = {
        DBFields.MANUAL_LENS_MAKE: "TTArtisan",
        DBFields.MANUAL_LENS_MODEL: "TTArtisan APS-C 40mm F2.8 MACRO",
        DBFields.MANUAL_FOCAL_LENGTH: focal_length,
        DBFields.MANUAL_FOCAL_LENGTH_35MM: focal_length_35mm,
    }
    if workflow == "flickr":
        target = tmp_path / "upload.jpg"
        shutil.copyfile(source, target)
        _write_exif_to_temp_file(str(target), exiftool_path, metadata)
        assert source.read_bytes() == original_bytes
    else:
        target = source
        result = run_write_exif_task({
            "task_id": 1,
            "exiftool_path": exiftool_path,
            "items": [{"file_path": str(target), "tags": build_exif_tags(metadata)}],
        })
        assert result["results"] == [
            {"file_path": str(target), "ok": True, "error": ""}
        ]

    assert len(warnings) == 1
    assert "Lens" not in warnings[0]
    assert "Focal" not in warnings[0]
    with exiftool.ExifToolHelper(executable=exiftool_path, common_args=[]) as helper:
        after = helper.get_tags(
            str(target),
            [
                "LensMake",
                "LensModel",
                "Lens",
                "FocalLength",
                "FocalLengthIn35mmFormat",
                "LensInfo",
                "MinFocalLength",
                "MaxFocalLength",
                "MakerNotes",
            ],
            params=["-G1", "-n"],
        )[0]
        display = helper.get_tags(str(target), ["LensInfo"], params=["-G1"])[0]

    normalized_focal = focal_length.replace(",", ".")
    assert after["ExifIFD:LensMake"] == metadata[DBFields.MANUAL_LENS_MAKE]
    assert after["ExifIFD:LensModel"] == metadata[DBFields.MANUAL_LENS_MODEL]
    assert after["ExifIFD:FocalLength"] == float(normalized_focal)
    assert after["ExifIFD:FocalLengthIn35mmFormat"] == int(focal_length_35mm)
    assert after["XMP-aux:Lens"] == f"{normalized_focal} mm"
    assert (
        after["ExifIFD:LensInfo"]
        == f"{normalized_focal} {normalized_focal} undef undef"
    )
    assert display["ExifIFD:LensInfo"] == f"{normalized_focal}mm f/?"
    if with_maker_notes:
        assert after["FujiFilm:MinFocalLength"] == float(normalized_focal)
        assert after["FujiFilm:MaxFocalLength"] == float(normalized_focal)
    else:
        assert not any(key.startswith("FujiFilm:") for key in after)
        assert not any("MakerNote" in key for key in after)
