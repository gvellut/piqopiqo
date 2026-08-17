"""Tests for atomic thumbnail writes and full-storage propagation."""

from __future__ import annotations

import errno

from PIL import Image
import pytest

from piqopiqo.background.media_worker import (
    SourceChangedDuringReadError,
    _extract_embedded_previews,
    generate_hq_thumbnail,
    run_hq_thumb_task,
)
from piqopiqo.storage import StorageFullError


def _write_jpeg(path, *, color: str) -> None:
    Image.new("RGB", (24, 16), color=color).save(path, "JPEG")


def test_hq_thumbnail_atomically_replaces_existing_file(tmp_path):
    source = tmp_path / "source.jpg"
    destination = tmp_path / "hq" / "source.jpg"
    _write_jpeg(source, color="red")
    destination.parent.mkdir()
    destination.write_bytes(b"old-thumbnail")

    generate_hq_thumbnail(str(source), str(destination), 12)

    assert destination.read_bytes() != b"old-thumbnail"
    assert not list(destination.parent.glob("*.tmp"))
    assert not list(destination.parent.glob(".*.tmp"))


def test_hq_thumbnail_failure_preserves_existing_file_and_removes_temp(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.jpg"
    destination = tmp_path / "hq" / "source.jpg"
    _write_jpeg(source, color="red")
    destination.parent.mkdir()
    destination.write_bytes(b"old-thumbnail")

    monkeypatch.setattr(
        Image.Image,
        "save",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError(errno.ENOSPC, "No space left on device")
        ),
    )

    with pytest.raises(OSError, match="No space left"):
        generate_hq_thumbnail(str(source), str(destination), 12)

    assert destination.read_bytes() == b"old-thumbnail"
    assert not list(destination.parent.glob("*.tmp"))
    assert not list(destination.parent.glob(".*.tmp"))


def test_hq_source_change_preserves_existing_thumbnail(tmp_path, monkeypatch):
    source = tmp_path / "source.jpg"
    destination = tmp_path / "hq" / "source.jpg"
    _write_jpeg(source, color="red")
    destination.parent.mkdir()
    destination.write_bytes(b"old-thumbnail")
    fingerprints = iter([(1, 100, 1, 1), (2, 200, 1, 1)])
    monkeypatch.setattr(
        "piqopiqo.background.media_worker._source_fingerprint",
        lambda _path: next(fingerprints),
    )

    with pytest.raises(SourceChangedDuringReadError):
        generate_hq_thumbnail(str(source), str(destination), 12)

    assert destination.read_bytes() == b"old-thumbnail"
    assert not list(destination.parent.glob(".*.tmp"))


def test_hq_worker_returns_exact_storage_fault(tmp_path, monkeypatch):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    thumb_dir = tmp_path / "thumb"
    monkeypatch.setattr(
        "piqopiqo.background.media_worker.generate_hq_thumbnail",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError(errno.ENOSPC, "No space left on device")
        ),
    )

    result = run_hq_thumb_task({
        "task_id": 7,
        "file_path": str(source),
        "thumb_dir": str(thumb_dir),
        "max_dim": 128,
    })

    assert result["ok"] is False
    assert result["error"] == "[Errno 28] No space left on device"
    assert result["storage_full_fault"].target_path == str(thumb_dir / "hq")


def test_embedded_failure_preserves_existing_preview(tmp_path):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    thumb_dir = tmp_path / "thumb"
    destination = thumb_dir / "embedded" / "source.jpg"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old-preview")

    class _FullHelper:
        def execute(self, *_args):
            raise OSError(errno.ENOSPC, "No space left on device")

    with pytest.raises(StorageFullError):
        _extract_embedded_previews(
            _FullHelper(),
            file_paths=[str(source)],
            thumb_dir=str(thumb_dir),
            exiftool_path=None,
        )

    assert destination.read_bytes() == b"old-preview"
    assert not list(destination.parent.glob(".piqopiqo-embedded-*"))


def test_embedded_transient_read_failure_preserves_existing_preview(tmp_path):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    thumb_dir = tmp_path / "thumb"
    destination = thumb_dir / "embedded" / "source.jpg"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old-preview")

    class _BrokenHelper:
        def execute(self, *_args):
            raise RuntimeError("source is still being written")

    with pytest.raises(RuntimeError, match="still being written"):
        _extract_embedded_previews(
            _BrokenHelper(),
            file_paths=[str(source)],
            thumb_dir=str(thumb_dir),
            exiftool_path=None,
        )

    assert destination.read_bytes() == b"old-preview"
    assert not list(destination.parent.glob(".piqopiqo-embedded-*"))


def test_embedded_source_change_preserves_existing_preview(tmp_path, monkeypatch):
    source = tmp_path / "source.jpg"
    _write_jpeg(source, color="red")
    thumb_dir = tmp_path / "thumb"
    destination = thumb_dir / "embedded" / "source.jpg"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old-preview")
    fingerprints = iter([(1, 100, 1, 1), (2, 200, 1, 1)])
    monkeypatch.setattr(
        "piqopiqo.background.media_worker._source_fingerprint",
        lambda _path: next(fingerprints),
    )

    class _WritingHelper:
        def execute(self, *_args):
            pattern = _args[3]
            _write_jpeg(pattern.replace("%f", "source"), color="blue")

    cache_paths, changed_paths = _extract_embedded_previews(
        _WritingHelper(),
        file_paths=[str(source)],
        thumb_dir=str(thumb_dir),
        exiftool_path=None,
    )

    assert cache_paths == {str(source): None}
    assert changed_paths == {str(source)}
    assert destination.read_bytes() == b"old-preview"
    assert not list(destination.parent.glob(".piqopiqo-embedded-*"))
