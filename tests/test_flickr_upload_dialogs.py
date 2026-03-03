"""Tests for Flickr upload dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.tools.flickr_upload.albums import FlickrAlbumPlan
from piqopiqo.tools.flickr_upload.constants import FlickrStage
from piqopiqo.tools.flickr_upload.dialogs import (
    FlickrPreflightDialog,
    FlickrUploadProgressDialog,
)
from piqopiqo.tools.flickr_upload.manager import (
    FlickrUploadPhotoFailure,
    FlickrUploadResult,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_preflight_album_field_visible_only_when_upload_ready(qapp) -> None:  # noqa: ARG001
    upload_dialog = FlickrPreflightDialog(
        visible_count=3,
        token_file_path="/tmp/oauth-tokens.sqlite",
        token_exists=True,
    )
    assert upload_dialog.album_input is not None

    login_dialog = FlickrPreflightDialog(
        visible_count=3,
        token_file_path="/tmp/oauth-tokens.sqlite",
        token_exists=False,
    )
    assert login_dialog.album_input is None


def test_preflight_album_error_clears_on_text_change(qapp) -> None:  # noqa: ARG001
    dialog = FlickrPreflightDialog(
        visible_count=3,
        token_file_path="/tmp/oauth-tokens.sqlite",
        token_exists=True,
        album_error="Album not found",
    )
    assert dialog.album_error_label is not None
    assert dialog.album_error_label.text() == "Album not found"

    assert dialog.album_input is not None
    dialog.album_input.setText("My Album")
    assert dialog.album_error_label.text() == ""
    assert dialog.album_error_label.isHidden() is True


def test_preflight_folder_data_link_visibility(qapp) -> None:  # noqa: ARG001
    plan = FlickrAlbumPlan(
        raw_text="72177720331888267",
        album_id="72177720331888267",
        album_title="Trip",
        user_nsid="22539273@N00",
        album_url="https://flickr.com/photos/22539273@N00/albums/72177720331888267",
        is_create=False,
    )

    with_link = FlickrPreflightDialog(
        visible_count=2,
        token_file_path="/tmp/oauth-tokens.sqlite",
        token_exists=True,
        album_display_plan=plan,
        show_album_link=True,
    )
    assert with_link.album_link_label is not None
    assert with_link.album_link_label.isHidden() is False
    assert "flickr.com/photos/22539273@N00/albums/72177720331888267" in (
        with_link.album_link_label.text()
    )

    without_link = FlickrPreflightDialog(
        visible_count=2,
        token_file_path="/tmp/oauth-tokens.sqlite",
        token_exists=True,
        album_display_plan=plan,
        show_album_link=False,
    )
    assert without_link.album_link_label is not None
    assert without_link.album_link_label.isHidden() is True


def _mk_upload_dialog() -> FlickrUploadProgressDialog:
    return FlickrUploadProgressDialog(
        api_key="k",
        api_secret="s",
        exiftool_path="/opt/homebrew/bin/exiftool",
        upload_items=[
            {"file_path": "/a.jpg", "order": 0, "db_metadata": None},
            {"file_path": "/b.jpg", "order": 1, "db_metadata": None},
        ],
        album_text="Trip",
        cached_album_plan=None,
        set_folder_album_id_callback=lambda _album_id: None,
    )


def test_upload_progress_shows_single_running_step_line(qapp) -> None:  # noqa: ARG001
    dialog = _mk_upload_dialog()

    dialog._on_stage_changed(FlickrStage.STAGE_UPLOAD.label)
    assert FlickrStage.STAGE_UPLOAD.label in dialog.stage_label.text()
    dialog._on_progress(1, 2)
    assert dialog.progress_text_label.text() == "1/2"
    assert dialog.progress_text_label.isHidden() is False

    dialog._on_stage_changed(FlickrStage.STAGE_RESET_DATE.label)
    assert FlickrStage.STAGE_RESET_DATE.label in dialog.stage_label.text()

    dialog._on_status(FlickrStage.STAGE_UPLOAD.label)
    assert FlickrStage.STAGE_RESET_DATE.label in dialog.stage_label.text()
    assert dialog.album_action_label.isHidden() is True

    dialog._on_stage_changed(FlickrStage.STAGE_CHECK_UPLOAD_STATUS.label)
    assert dialog.progress_bar.minimum() == 0
    assert dialog.progress_bar.maximum() == 0
    assert dialog.progress_text_label.isHidden() is True

    dialog._on_status("Check 2/10")
    assert "Check upload status - Check 2/10" in dialog.stage_label.text()


def test_upload_progress_add_to_album_uses_merged_step_text(qapp) -> None:  # noqa: ARG001
    dialog = _mk_upload_dialog()
    dialog._on_stage_changed(FlickrStage.STAGE_ADD_TO_ALBUM.label)

    dialog._on_album_status("Creating album 'Trip'...")
    assert "Add to album - Creating album 'Trip'" in dialog.stage_label.text()
    assert dialog.album_action_label.isHidden() is True

    dialog._on_album_status("Adding to album 'Trip'...")
    assert "Add to album - Adding to album 'Trip'" in dialog.stage_label.text()
    assert dialog.album_action_label.isHidden() is True


def test_upload_progress_completion_hides_running_widgets_and_shows_summary(  # noqa: ARG001
    qapp,
) -> None:
    dialog = _mk_upload_dialog()
    dialog._on_stage_changed(FlickrStage.STAGE_UPLOAD.label)

    dialog._on_finished(
        FlickrUploadResult(
            total_photos=2,
            uploaded_count=2,
            reset_date_count=2,
            made_public_count=2,
        )
    )

    assert dialog.stage_label.isHidden() is True
    assert dialog.progress_bar.isHidden() is True
    assert dialog.progress_text_label.isHidden() is True
    assert dialog.status_label.isHidden() is False
    assert dialog.details.isHidden() is False
    assert dialog.ok_btn.isHidden() is False
    assert dialog.ok_btn.isEnabled() is True


def test_upload_progress_height_tracks_content_changes(qapp) -> None:
    dialog = _mk_upload_dialog()
    dialog.show()
    qapp.processEvents()

    initial_height = dialog.height()
    assert initial_height < 300
    assert dialog.minimumHeight() == dialog.maximumHeight() == initial_height

    failures = [
        FlickrUploadPhotoFailure(
            file_path="/a.jpg",
            stage=FlickrStage.STAGE_ADD_TO_ALBUM.label,
            message="Album operation failed",
        )
        for _ in range(6)
    ]
    dialog._on_finished(
        FlickrUploadResult(
            total_photos=2,
            uploaded_count=1,
            reset_date_count=1,
            made_public_count=1,
            failures=failures,
        )
    )
    qapp.processEvents()

    final_height = dialog.height()
    assert dialog.minimumHeight() == dialog.maximumHeight() == final_height
    assert final_height != initial_height
