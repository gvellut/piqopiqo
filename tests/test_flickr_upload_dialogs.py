"""Tests for Flickr upload dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication
import pytest

from piqopiqo.flickr_upload.albums import FlickrAlbumPlan
from piqopiqo.flickr_upload.dialogs import FlickrPreflightDialog


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
