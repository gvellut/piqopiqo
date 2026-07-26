"""Tests for startup cache writeability recovery."""

from __future__ import annotations

from pathlib import Path

import piqopiqo.__main__ as main_module
from piqopiqo.storage import StorageFullError, StorageWriteFault


def test_startup_cache_retry_returns_path_after_space_is_freed(monkeypatch, tmp_path):
    cache_path = tmp_path / "cache"
    fault = StorageWriteFault(
        target_path=str(cache_path),
        operation="startup_cache_probe",
        error_message="No space left on device",
    )
    attempts = {"count": 0}

    def _prepare(_cache_base, *, clear_on_start):
        assert clear_on_start is False
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise StorageFullError(fault)
        return cache_path

    def _wait(**kwargs):
        assert kwargs["fault"] == fault
        assert kwargs["retry"]() is None
        return True

    monkeypatch.setattr(main_module, "_prepare_cache_storage", _prepare)
    monkeypatch.setattr(main_module, "wait_for_storage_retry", _wait)

    result = main_module._prepare_cache_storage_with_retry(
        str(cache_path),
        clear_on_start=False,
    )

    assert result == cache_path
    assert attempts["count"] == 2


def test_startup_cache_exit_returns_none(monkeypatch, tmp_path):
    fault = StorageWriteFault(
        target_path=str(tmp_path),
        operation="startup_cache_probe",
        error_message="No space left on device",
    )
    monkeypatch.setattr(
        main_module,
        "_prepare_cache_storage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(StorageFullError(fault)),
    )
    monkeypatch.setattr(
        main_module,
        "wait_for_storage_retry",
        lambda **_kwargs: False,
    )

    result = main_module._prepare_cache_storage_with_retry(
        str(tmp_path),
        clear_on_start=False,
    )

    assert result is None


def test_prepare_cache_storage_performs_real_write_probe(tmp_path):
    cache_path = main_module._prepare_cache_storage(
        str(tmp_path / "cache"),
        clear_on_start=False,
    )

    assert cache_path == Path(tmp_path / "cache")
    assert list(cache_path.iterdir()) == []
