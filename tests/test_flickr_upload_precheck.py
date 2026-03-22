"""Tests for Flickr upload launch-flow scope selection."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMessageBox
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
    def __init__(self, by_path: dict[str, dict | None]):
        self._by_path = by_path

    def get_metadata(self, file_path: str):
        return self._by_path.get(file_path)


class _FakeDbManager:
    def __init__(self, by_path: dict[str, dict | None] | None = None):
        self._by_path = by_path or {}

    def get_db_for_image(self, _file_path: str):
        return _FakeDb(self._by_path)


class _FakePhotoModel:
    def __init__(
        self,
        all_photos: list[_FakeItem],
        *,
        sorted_paths: list[str] | None = None,
        source_folders: list[str] | None = None,
    ):
        self.all_photos = list(all_photos)
        self.source_folders = list(source_folders or ["/photos"])
        self._sorted_paths = list(sorted_paths or [item.path for item in all_photos])
        self.sort_calls: list[list[str]] = []

    def sort_photos_for_current_order(self, photos: list[_FakeItem]) -> list[_FakeItem]:
        self.sort_calls.append([item.path for item in photos])
        order = {path: index for index, path in enumerate(self._sorted_paths)}
        return sorted(photos, key=lambda item: order.get(item.path, len(order)))


class _FakeParent:
    def __init__(
        self,
        *,
        visible_items: list[_FakeItem],
        all_items: list[_FakeItem],
        db_manager: _FakeDbManager,
        sorted_paths: list[str] | None = None,
    ):
        self.images_data = list(visible_items)
        self.db_manager = db_manager
        self.photo_model = _FakePhotoModel(
            all_items,
            sorted_paths=sorted_paths,
        )
        self.open_settings_calls: list[UserSettingKey] = []

    def open_settings_for_key(self, key: UserSettingKey) -> None:
        self.open_settings_calls.append(key)


def _patch_settings(
    monkeypatch,
    *,
    require_metadata: bool,
    label_override: str = "",
) -> None:
    values = {
        UserSettingKey.FLICKR_API_KEY: "key",
        UserSettingKey.FLICKR_API_SECRET: "secret",
        UserSettingKey.FLICKR_UPLOAD_LABEL: label_override,
        UserSettingKey.FLICKR_UPLOAD_REQUIRE_TITLE_AND_KEYWORDS: require_metadata,
    }
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.get_user_setting",
        lambda key: values[key],
    )


def test_launch_flickr_upload_passes_visible_scope_without_blocking_precheck(
    qapp,
    monkeypatch,
) -> None:  # noqa: ARG001
    parent = _FakeParent(
        visible_items=[_FakeItem("/a.jpg", {"title": "", "keywords": "one"})],
        all_items=[_FakeItem("/a.jpg", {"title": "", "keywords": "one"})],
        db_manager=_FakeDbManager(),
    )
    _patch_settings(monkeypatch, require_metadata=True)

    launch_calls: list[dict] = []

    def _capture_launch(
        _parent,
        *,
        api_key,
        api_secret,
        upload_scope_items_by_name,
        label_override_text,
        should_require_metadata,
    ):
        assert api_key == "key"
        assert api_secret == "secret"
        launch_calls.append(
            {
                "upload_scope_items_by_name": upload_scope_items_by_name,
                "label_override_text": label_override_text,
                "should_require_metadata": should_require_metadata,
            }
        )

    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs._launch_flickr_upload_flow",
        _capture_launch,
    )

    dialogs.launch_flickr_upload(parent)

    assert len(launch_calls) == 1
    assert launch_calls[0]["label_override_text"] == ""
    assert launch_calls[0]["should_require_metadata"] is True
    assert list(launch_calls[0]["upload_scope_items_by_name"]) == [
        dialogs.UPLOAD_SCOPE_VISIBLE
    ]
    assert launch_calls[0]["upload_scope_items_by_name"][dialogs.UPLOAD_SCOPE_VISIBLE][
        0
    ]["file_path"] == "/a.jpg"


def test_launch_flickr_upload_builds_label_scope_from_all_photos_in_sort_order(
    qapp,
    monkeypatch,
) -> None:  # noqa: ARG001
    hidden_from_db = _FakeItem("/c.jpg", None)
    visible_nonmatch = _FakeItem("/a.jpg", {"label": "Rejected"})
    hidden_match = _FakeItem("/b.jpg", {"label": "Approved"})
    parent = _FakeParent(
        visible_items=[visible_nonmatch],
        all_items=[hidden_from_db, visible_nonmatch, hidden_match],
        db_manager=_FakeDbManager(
            {
                "/c.jpg": {"label": "Approved"},
            }
        ),
        sorted_paths=["/b.jpg", "/c.jpg", "/a.jpg"],
    )
    _patch_settings(monkeypatch, require_metadata=False, label_override="Approved")

    launch_calls: list[dict] = []

    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs._launch_flickr_upload_flow",
        lambda _parent, **kwargs: launch_calls.append(kwargs),
    )

    dialogs.launch_flickr_upload(parent)

    assert len(launch_calls) == 1
    visible_scope = launch_calls[0]["upload_scope_items_by_name"][
        dialogs.UPLOAD_SCOPE_VISIBLE
    ]
    label_scope = launch_calls[0]["upload_scope_items_by_name"][
        dialogs.UPLOAD_SCOPE_LABEL
    ]
    assert [entry["file_path"] for entry in visible_scope] == ["/a.jpg"]
    assert [entry["file_path"] for entry in label_scope] == ["/b.jpg", "/c.jpg"]
    assert parent.photo_model.sort_calls == [["/c.jpg", "/b.jpg"]]
    assert hidden_from_db.db_metadata == {"label": "Approved"}


def test_launch_flickr_upload_warns_when_both_scopes_are_empty(
    qapp,
    monkeypatch,
) -> None:  # noqa: ARG001
    parent = _FakeParent(
        visible_items=[],
        all_items=[],
        db_manager=_FakeDbManager(),
    )
    _patch_settings(monkeypatch, require_metadata=False, label_override="Approved")

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
    assert warnings == ["No photos to upload."]


def test_launch_flickr_upload_missing_credentials_opens_settings(
    qapp,
    monkeypatch,
) -> None:  # noqa: ARG001
    parent = _FakeParent(
        visible_items=[_FakeItem("/a.jpg", {"title": "A", "keywords": "one"})],
        all_items=[_FakeItem("/a.jpg", {"title": "A", "keywords": "one"})],
        db_manager=_FakeDbManager(),
    )
    values = {
        UserSettingKey.FLICKR_API_KEY: "",
        UserSettingKey.FLICKR_API_SECRET: "",
        UserSettingKey.FLICKR_UPLOAD_LABEL: "",
        UserSettingKey.FLICKR_UPLOAD_REQUIRE_TITLE_AND_KEYWORDS: False,
    }
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.get_user_setting",
        lambda key: values[key],
    )

    prompt_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.prompt_open_settings_for_missing_setting",
        lambda _parent, *, title, text, icon=QMessageBox.Icon.Warning: (
            prompt_calls.append((title, text)) or True
        ),
    )

    launch_calls: list[object] = []
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs._launch_flickr_upload_flow",
        lambda *_args, **_kwargs: launch_calls.append("called"),
    )

    dialogs.launch_flickr_upload(parent)

    assert launch_calls == []
    assert prompt_calls == [
        (
            "Upload to Flickr",
            "Flickr API key and Flickr API secret are empty.\n"
            "Set them in Settings > External/Tools > Flickr.",
        )
    ]
    assert parent.open_settings_calls == [UserSettingKey.FLICKR_API_KEY]
