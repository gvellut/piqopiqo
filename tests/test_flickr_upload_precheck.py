"""Tests for Flickr upload required-metadata precheck orchestration."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.ssf.settings_state import UserSettingKey
from piqopiqo.tools.flickr_upload import dialogs


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakeItem:
    def __init__(self, path: str, db_metadata: dict | None):
        self.path = path
        self.db_metadata = db_metadata


class _FakeDb:
    def __init__(self, by_path: dict[str, dict | None], *, fail: bool):
        self._by_path = by_path
        self._fail = fail

    def get_metadata(self, _file_path: str):
        if self._fail:
            raise RuntimeError("db error")
        return self._by_path.get(_file_path)


class _FakeDbManager:
    def __init__(self, by_path: dict[str, dict | None] | None = None, *, fail: bool = False):
        self._by_path = by_path or {}
        self._fail = fail

    def get_db_for_image(self, _file_path: str):
        return _FakeDb(self._by_path, fail=self._fail)


class _FakeParent:
    def __init__(self, items: list[_FakeItem], db_manager):
        self.images_data = items
        self.db_manager = db_manager
        self._active_flickr_metadata_precheck_worker = None
        self.selection_calls: list[tuple[list[str], str | None, str | None]] = []

    def select_paths_in_grid(
        self,
        paths: list[str],
        *,
        anchor_path: str | None = None,
        reveal_path: str | None = None,
    ) -> None:
        self.selection_calls.append((list(paths), anchor_path, reveal_path))


class _ImmediateThreadPool:
    def start(self, worker) -> None:
        worker.run()


def _patch_settings(
    monkeypatch,
    *,
    require_metadata: bool,
) -> None:
    values = {
        UserSettingKey.FLICKR_API_KEY: "key",
        UserSettingKey.FLICKR_API_SECRET: "secret",
        UserSettingKey.FLICKR_UPLOAD_REQUIRE_TITLE_AND_KEYWORDS: require_metadata,
    }
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.get_user_setting",
        lambda key: values[key],
    )


def test_launch_flickr_upload_skips_precheck_when_setting_disabled(qapp, monkeypatch):  # noqa: ARG001
    parent = _FakeParent(
        [
            _FakeItem(
                "/a.jpg",
                {"title": "A", "keywords": "one"},
            )
        ],
        _FakeDbManager(),
    )
    _patch_settings(monkeypatch, require_metadata=False)

    launch_calls: list[list[dict]] = []

    def _capture_launch(_parent, *, api_key, api_secret, upload_scope_items):
        assert api_key == "key"
        assert api_secret == "secret"
        launch_calls.append(list(upload_scope_items))

    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs._launch_flickr_upload_flow",
        _capture_launch,
    )

    dialogs.launch_flickr_upload(parent)

    assert len(launch_calls) == 1
    assert launch_calls[0][0]["file_path"] == "/a.jpg"
    assert parent._active_flickr_metadata_precheck_worker is None


def test_launch_flickr_upload_rejects_and_selects_missing_paths(qapp, monkeypatch):  # noqa: ARG001
    parent = _FakeParent(
        [
            _FakeItem(
                "/a.jpg",
                {"title": "", "keywords": "one"},
            ),
            _FakeItem(
                "/b.jpg",
                {"title": "B", "keywords": "two"},
            ),
        ],
        _FakeDbManager(),
    )
    _patch_settings(monkeypatch, require_metadata=True)

    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.QThreadPool.globalInstance",
        lambda: _ImmediateThreadPool(),
    )

    warnings: list[str] = []
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.QMessageBox.warning",
        lambda _parent, _title, text: warnings.append(text),
    )

    launch_calls: list[object] = []
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs._launch_flickr_upload_flow",
        lambda *_args, **_kwargs: launch_calls.append("called"),
    )

    dialogs.launch_flickr_upload(parent)

    assert launch_calls == []
    assert len(warnings) == 1
    assert "Upload rejected" in warnings[0]
    assert parent.selection_calls == [(["/a.jpg"], "/a.jpg", "/a.jpg")]
    assert parent._active_flickr_metadata_precheck_worker is None


def test_launch_flickr_upload_continues_when_precheck_passes(qapp, monkeypatch):  # noqa: ARG001
    parent = _FakeParent(
        [
            _FakeItem(
                "/a.jpg",
                {"title": "A", "keywords": "one"},
            )
        ],
        _FakeDbManager(),
    )
    _patch_settings(monkeypatch, require_metadata=True)

    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.QThreadPool.globalInstance",
        lambda: _ImmediateThreadPool(),
    )

    warnings: list[str] = []
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.QMessageBox.warning",
        lambda _parent, _title, text: warnings.append(text),
    )

    launch_calls: list[list[dict]] = []
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs._launch_flickr_upload_flow",
        lambda _parent, *, api_key, api_secret, upload_scope_items: launch_calls.append(
            list(upload_scope_items)
        ),
    )

    dialogs.launch_flickr_upload(parent)

    assert len(launch_calls) == 1
    assert warnings == []
    assert parent.selection_calls == []
    assert parent._active_flickr_metadata_precheck_worker is None


def test_launch_flickr_upload_fails_open_when_precheck_errors(qapp, monkeypatch):  # noqa: ARG001
    parent = _FakeParent(
        [_FakeItem("/a.jpg", None)],
        _FakeDbManager(fail=True),
    )
    _patch_settings(monkeypatch, require_metadata=True)

    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.QThreadPool.globalInstance",
        lambda: _ImmediateThreadPool(),
    )

    warnings: list[str] = []
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.QMessageBox.warning",
        lambda _parent, _title, text: warnings.append(text),
    )

    launch_calls: list[list[dict]] = []
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs._launch_flickr_upload_flow",
        lambda _parent, *, api_key, api_secret, upload_scope_items: launch_calls.append(
            list(upload_scope_items)
        ),
    )

    dialogs.launch_flickr_upload(parent)

    assert len(launch_calls) == 1
    assert warnings == []
    assert parent.selection_calls == []
    assert parent._active_flickr_metadata_precheck_worker is None
