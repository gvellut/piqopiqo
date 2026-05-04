"""Tests for Flickr upload launch-flow scope selection."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
import pytest

from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.model import LabelTransitionRule, StatusLabel
from piqopiqo.ssf.settings_state import (
    StateKey,
    UserSettingKey,
    get_state_value,
    init_qsettings_store,
    set_state_value,
)
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
    def __init__(
        self,
        by_path: dict[str, dict | None],
        saved: list[tuple[str, dict]],
    ):
        self._by_path = by_path
        self._saved = saved

    def get_metadata(self, file_path: str):
        return self._by_path.get(file_path)

    def save_metadata(self, file_path: str, data: dict) -> None:
        self._by_path[file_path] = data.copy()
        self._saved.append((file_path, data.copy()))


class _FakeDbManager:
    def __init__(self, by_path: dict[str, dict | None] | None = None):
        self._by_path = by_path or {}
        self.saved: list[tuple[str, dict]] = []

    def get_db_for_image(self, _file_path: str):
        return _FakeDb(self._by_path, self.saved)

    def get_db_for_folder(self, _folder: str):
        return _FakeFolderDb()


class _FakeFolderDb:
    def get_folder_value(self, _key: str):
        return None

    def set_folder_value(self, _key: str, _value: str | None) -> None:
        pass


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
        self._active_flickr_upload_manager = None

    def open_settings_for_key(self, key: UserSettingKey) -> None:
        self.open_settings_calls.append(key)


def _patch_settings(
    monkeypatch,
    *,
    require_metadata: bool,
    label_override: str = "",
    use_lifecycle: bool | None = None,
) -> None:
    if use_lifecycle is None:
        use_lifecycle = bool(label_override)
    values = {
        UserSettingKey.FLICKR_API_KEY: "key",
        UserSettingKey.FLICKR_API_SECRET: "secret",
        UserSettingKey.FLICKR_UPLOAD_USE_LIFECYCLE: use_lifecycle,
        UserSettingKey.FLICKR_UPLOAD_LABEL: label_override,
        UserSettingKey.FLICKR_UPLOAD_REQUIRE_TITLE_AND_KEYWORDS: require_metadata,
        UserSettingKey.FLICKR_UPLOAD_LABEL_TRANSITIONS: [],
        UserSettingKey.STATUS_LABELS: [],
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
        use_lifecycle,
        visible_upload_items,
        label_upload_items,
        label_override_text,
        should_require_metadata,
    ):
        assert api_key == "key"
        assert api_secret == "secret"
        assert use_lifecycle is False
        launch_calls.append(
            {
                "use_lifecycle": use_lifecycle,
                "visible_upload_items": visible_upload_items,
                "label_upload_items": label_upload_items,
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
    assert [
        entry["file_path"] for entry in launch_calls[0]["visible_upload_items"]
    ] == ["/a.jpg"]
    assert launch_calls[0]["label_upload_items"] == []


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
    visible_scope = launch_calls[0]["visible_upload_items"]
    label_scope = launch_calls[0]["label_upload_items"]
    assert [entry["file_path"] for entry in visible_scope] == ["/a.jpg"]
    assert [entry["file_path"] for entry in label_scope] == ["/b.jpg", "/c.jpg"]
    assert parent.photo_model.sort_calls == [["/c.jpg", "/b.jpg"]]
    assert hidden_from_db.db_metadata == {"label": "Approved"}


def test_launch_flickr_upload_ignores_lifecycle_label_when_setting_is_off(
    qapp,
    monkeypatch,
) -> None:  # noqa: ARG001
    visible = _FakeItem("/a.jpg", {"label": "Rejected"})
    hidden_match = _FakeItem("/b.jpg", {"label": "Approved"})
    parent = _FakeParent(
        visible_items=[visible],
        all_items=[visible, hidden_match],
        db_manager=_FakeDbManager(),
    )
    _patch_settings(
        monkeypatch,
        require_metadata=False,
        label_override="Approved",
        use_lifecycle=False,
    )

    launch_calls: list[dict] = []
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs._launch_flickr_upload_flow",
        lambda _parent, **kwargs: launch_calls.append(kwargs),
    )

    dialogs.launch_flickr_upload(parent)

    assert len(launch_calls) == 1
    assert launch_calls[0]["use_lifecycle"] is False
    assert launch_calls[0]["label_override_text"] == ""
    assert launch_calls[0]["label_upload_items"] == []
    assert parent.photo_model.sort_calls == []


def test_flickr_upload_flow_uses_all_loaded_photos_for_transition_scope(
    qapp,
    monkeypatch,
) -> None:  # noqa: ARG001
    approved = _FakeItem("/approved.jpg", {DBFields.LABEL: "Approved"})
    rejected = _FakeItem("/rejected.jpg", {DBFields.LABEL: "Rejected"})
    review = _FakeItem("/review.jpg", {DBFields.LABEL: "Review"})
    parent = _FakeParent(
        visible_items=[approved],
        all_items=[approved, rejected, review],
        db_manager=_FakeDbManager(),
    )
    rules = [
        LabelTransitionRule("Approved", "Uploaded"),
        LabelTransitionRule("Rejected", "Done"),
        LabelTransitionRule("Review", "Done"),
    ]
    status_labels = [
        StatusLabel("Approved", "#ff0000", 0),
        StatusLabel("Uploaded", "#00ff00", 1),
        StatusLabel("Rejected", "#0000ff", 2),
        StatusLabel("Review", "#ffff00", 3),
        StatusLabel("Done", "#00ffff", 4),
    ]
    values = {
        UserSettingKey.FLICKR_UPLOAD_LABEL_TRANSITIONS: rules,
        UserSettingKey.STATUS_LABELS: status_labels,
        UserSettingKey.EXIFTOOL_PATH: "/opt/homebrew/bin/exiftool",
    }
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.get_user_setting",
        lambda key: values[key],
    )
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.get_flickr_token_file_path",
        lambda: "/tmp/flickr-token.sqlite",
    )
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.token_file_exists",
        lambda _path: True,
    )

    class _Signal:
        def connect(self, _callback) -> None:
            return

    class _Preflight:
        selected_album_text = ""
        selected_use_label_scope = True
        selected_action = "upload"

        def __init__(self, **kwargs):
            self._label_upload_items = list(kwargs["label_upload_items"])

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_upload_scope_items(self) -> list[dict]:
            return list(self._label_upload_items)

    created_upload_dialogs: list[object] = []

    class _UploadDialog:
        invalid_token = False
        album_validation_error = ""
        resolved_album_plan = None

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.manager_started = _Signal()
            self.manager_finished = _Signal()
            created_upload_dialogs.append(self)

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.FlickrPreflightDialog",
        _Preflight,
    )
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.FlickrUploadProgressDialog",
        _UploadDialog,
    )

    dialogs._launch_flickr_upload_flow(
        parent,
        api_key="key",
        api_secret="secret",
        use_lifecycle=True,
        visible_upload_items=dialogs._build_upload_scope_items([approved]),
        label_upload_items=dialogs._build_upload_scope_items([approved]),
        label_override_text="Approved",
        should_require_metadata=False,
    )

    assert len(created_upload_dialogs) == 1
    upload_kwargs = created_upload_dialogs[0].kwargs
    assert [entry["file_path"] for entry in upload_kwargs["upload_items"]] == [
        "/approved.jpg"
    ]
    assert [
        entry["file_path"] for entry in upload_kwargs["transition_scope_items"]
    ] == [
        "/approved.jpg",
        "/rejected.jpg",
        "/review.jpg",
    ]
    assert upload_kwargs["transition_rules"] == rules


def test_flickr_upload_flow_hides_transitions_when_lifecycle_state_unchecked(
    qapp,
    monkeypatch,
) -> None:  # noqa: ARG001
    init_qsettings_store(dyn=True)
    set_state_value(StateKey.FLICKR_UPLOAD_USE_LIFECYCLE_SCOPE, True)
    approved = _FakeItem("/approved.jpg", {DBFields.LABEL: "Approved"})
    rejected = _FakeItem("/rejected.jpg", {DBFields.LABEL: "Rejected"})
    parent = _FakeParent(
        visible_items=[rejected],
        all_items=[approved, rejected],
        db_manager=_FakeDbManager(),
    )
    rules = [LabelTransitionRule("Approved", "Uploaded")]
    status_labels = [
        StatusLabel("Approved", "#ff0000", 0),
        StatusLabel("Uploaded", "#00ff00", 1),
    ]
    values = {
        UserSettingKey.FLICKR_UPLOAD_LABEL_TRANSITIONS: rules,
        UserSettingKey.STATUS_LABELS: status_labels,
        UserSettingKey.EXIFTOOL_PATH: "/opt/homebrew/bin/exiftool",
    }
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.get_user_setting",
        lambda key: values[key],
    )
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.get_flickr_token_file_path",
        lambda: "/tmp/flickr-token.sqlite",
    )
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.token_file_exists",
        lambda _path: True,
    )

    class _Signal:
        def connect(self, _callback) -> None:
            return

    class _ScopeCheckbox:
        def isEnabled(self) -> bool:
            return True

    class _Preflight:
        selected_album_text = ""
        selected_use_label_scope = False
        selected_action = "upload"
        scope_checkbox = _ScopeCheckbox()

        def __init__(self, **kwargs):
            self._visible_upload_items = list(kwargs["visible_upload_items"])

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_upload_scope_items(self) -> list[dict]:
            return list(self._visible_upload_items)

    created_upload_dialogs: list[object] = []

    class _UploadDialog:
        invalid_token = False
        album_validation_error = ""
        resolved_album_plan = None

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.manager_started = _Signal()
            self.manager_finished = _Signal()
            created_upload_dialogs.append(self)

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.FlickrPreflightDialog",
        _Preflight,
    )
    monkeypatch.setattr(
        "piqopiqo.tools.flickr_upload.dialogs.FlickrUploadProgressDialog",
        _UploadDialog,
    )

    dialogs._launch_flickr_upload_flow(
        parent,
        api_key="key",
        api_secret="secret",
        use_lifecycle=True,
        visible_upload_items=dialogs._build_upload_scope_items([rejected]),
        label_upload_items=dialogs._build_upload_scope_items([approved]),
        label_override_text="Approved",
        should_require_metadata=False,
    )

    upload_kwargs = created_upload_dialogs[0].kwargs
    assert [entry["file_path"] for entry in upload_kwargs["upload_items"]] == [
        "/rejected.jpg"
    ]
    assert upload_kwargs["transition_rules"] == []
    assert get_state_value(StateKey.FLICKR_UPLOAD_USE_LIFECYCLE_SCOPE) is False


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
        UserSettingKey.FLICKR_UPLOAD_USE_LIFECYCLE: False,
        UserSettingKey.FLICKR_UPLOAD_LABEL: "",
        UserSettingKey.FLICKR_UPLOAD_REQUIRE_TITLE_AND_KEYWORDS: False,
        UserSettingKey.FLICKR_UPLOAD_LABEL_TRANSITIONS: [],
        UserSettingKey.STATUS_LABELS: [],
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


def test_apply_flickr_label_transitions_updates_scope_and_syncs(qapp):  # noqa: ARG001
    scoped_approved = _FakeItem(
        "/a.jpg",
        {
            DBFields.TITLE: "A",
            DBFields.LABEL: "Approved",
        },
    )
    scoped_uploaded = _FakeItem(
        "/b.jpg",
        {
            DBFields.TITLE: "B",
            DBFields.LABEL: "Uploaded",
        },
    )
    out_of_scope = _FakeItem(
        "/c.jpg",
        {
            DBFields.TITLE: "C",
            DBFields.LABEL: "Approved",
        },
    )
    scoped_no_metadata = _FakeItem("/d.jpg", None)
    parent = _FakeParent(
        visible_items=[
            scoped_approved,
            scoped_uploaded,
            out_of_scope,
            scoped_no_metadata,
        ],
        all_items=[
            scoped_approved,
            scoped_uploaded,
            out_of_scope,
            scoped_no_metadata,
        ],
        db_manager=_FakeDbManager(),
    )
    parent.synced: list[tuple[set[str], str, bool]] = []
    parent.refreshed: list[str] = []
    parent.edit_panel = None
    parent._fullscreen_overlay = None

    def _sync_model_after_metadata_update(
        changed_fields,
        source,
        allow_fullscreen_filter=False,
    ):
        parent.synced.append((set(changed_fields), source, allow_fullscreen_filter))

    parent.sync_model_after_metadata_update = _sync_model_after_metadata_update
    parent._refresh_grid_item_if_visible = parent.refreshed.append

    result = dialogs._apply_flickr_label_transitions(
        parent,
        [
            {
                "file_path": "/a.jpg",
                "db_metadata": scoped_approved.db_metadata.copy(),
            },
            {
                "file_path": "/b.jpg",
                "db_metadata": scoped_uploaded.db_metadata.copy(),
            },
            {
                "file_path": "/d.jpg",
                "db_metadata": None,
            },
        ],
        [
            LabelTransitionRule("Approved", "Uploaded"),
            LabelTransitionRule("Uploaded", "Rejected"),
            LabelTransitionRule("", "Rejected"),
        ],
    )

    assert result.changed_count == 3
    assert result.per_rule_counts == [1, 1, 1]
    assert scoped_approved.db_metadata[DBFields.LABEL] == "Uploaded"
    assert scoped_uploaded.db_metadata[DBFields.LABEL] == "Rejected"
    assert scoped_no_metadata.db_metadata[DBFields.LABEL] == "Rejected"
    assert out_of_scope.db_metadata[DBFields.LABEL] == "Approved"
    assert [
        (path, data[DBFields.LABEL])
        for path, data in parent.db_manager.saved
    ] == [
        ("/a.jpg", "Uploaded"),
        ("/b.jpg", "Rejected"),
        ("/d.jpg", "Rejected"),
    ]
    assert parent.refreshed == ["/a.jpg", "/b.jpg", "/d.jpg"]
    assert parent.synced == [
        ({DBFields.LABEL}, "flickr_label_transitions", True)
    ]


def test_apply_flickr_label_transitions_changes_non_uploaded_loaded_images(
    qapp,
) -> None:  # noqa: ARG001
    uploaded = _FakeItem("/uploaded.jpg", {DBFields.LABEL: "Approved"})
    not_uploaded_rejected = _FakeItem("/not_uploaded_rejected.jpg", None)
    not_uploaded_review = _FakeItem(
        "/not_uploaded_review.jpg",
        {DBFields.LABEL: "Review"},
    )
    parent = _FakeParent(
        visible_items=[uploaded],
        all_items=[uploaded, not_uploaded_rejected, not_uploaded_review],
        db_manager=_FakeDbManager(
            {
                "/not_uploaded_rejected.jpg": {DBFields.LABEL: "Rejected"},
            }
        ),
    )
    parent.synced: list[tuple[set[str], str, bool]] = []
    parent.refreshed: list[str] = []
    parent.edit_panel = None
    parent._fullscreen_overlay = None

    def _sync_model_after_metadata_update(
        changed_fields,
        source,
        allow_fullscreen_filter=False,
    ):
        parent.synced.append((set(changed_fields), source, allow_fullscreen_filter))

    parent.sync_model_after_metadata_update = _sync_model_after_metadata_update
    parent._refresh_grid_item_if_visible = parent.refreshed.append

    result = dialogs._apply_flickr_label_transitions(
        parent,
        dialogs._build_transition_scope_items(parent),
        [
            LabelTransitionRule("Approved", "Uploaded"),
            LabelTransitionRule("Rejected", "Done"),
            LabelTransitionRule("Review", "Done"),
        ],
    )

    assert result.changed_count == 3
    assert result.per_rule_counts == [1, 1, 1]
    assert uploaded.db_metadata[DBFields.LABEL] == "Uploaded"
    assert not_uploaded_rejected.db_metadata[DBFields.LABEL] == "Done"
    assert not_uploaded_review.db_metadata[DBFields.LABEL] == "Done"
