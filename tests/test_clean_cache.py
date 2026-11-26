"""Cache discovery, deletion boundaries, and modal cleanup workflows."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QWidget
import pytest

from piqopiqo.cache_paths import (
    FOLDER_METADATA_SOURCE_PATH,
    get_folder_cache_id,
    set_cache_base_dir,
)
from piqopiqo.dialogs.modal import managed_modal_dialog
from piqopiqo.main_window import MainWindow
from piqopiqo.ssf.settings_state import init_qsettings_store
from piqopiqo.tools import clean_cache as module
from piqopiqo.tools.clean_cache import (
    CacheCleanupDialog,
    CacheCleanupResult,
    CacheFolder,
    CacheSelectionDialog,
    clean_cache,
    launch_clean_cache,
    scan_cache,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    init_qsettings_store(dyn=True)
    yield app
    app.closeAllWindows()
    app.processEvents()


def _make_cache(cache_base: Path, source: Path, *, legacy_table: str = "") -> Path:
    cache_dir = cache_base / get_folder_cache_id(str(source))
    db_dir = cache_dir / "db"
    db_dir.mkdir(parents=True)
    connection = sqlite3.connect(db_dir / "metadata.db")
    if legacy_table:
        connection.execute(f"CREATE TABLE {legacy_table} (file_path TEXT)")
        connection.execute(
            f"INSERT INTO {legacy_table} VALUES (?)", (str(source / "a.jpg"),)
        )
    else:
        connection.execute(
            "CREATE TABLE folder_metadata (data TEXT PRIMARY KEY, value TEXT)"
        )
        connection.execute(
            "INSERT INTO folder_metadata VALUES (?, ?)",
            (FOLDER_METADATA_SOURCE_PATH, str(source)),
        )
    connection.commit()
    connection.close()
    for quality in ("embedded", "hq"):
        thumb = cache_dir / "thumb" / quality / "a.jpg"
        thumb.parent.mkdir(parents=True)
        thumb.write_bytes(b"thumbnail")
    return cache_dir


@pytest.mark.parametrize("legacy_table", ["", "photo_metadata", "photo_exif_fields"])
def test_discovery_recovers_source_without_modifying_database(tmp_path, legacy_table):
    # Exercise SQLite URI escaping as well as old schemas.
    cache_base = tmp_path / "cache # ?"
    source = tmp_path / "photos" / "source"
    cache_dir = _make_cache(cache_base, source, legacy_table=legacy_table)
    db_path = cache_dir / "db" / "metadata.db"
    before = db_path.read_bytes()
    result = scan_cache(cache_base, "")
    assert result.error == ""
    assert result.unidentified_count == 0
    assert len(result.folders) == 1
    assert result.folders[0].source_folder == str(source)
    assert result.folders[0].missing
    assert db_path.read_bytes() == before


def test_stored_source_takes_precedence_over_photo_rows(tmp_path):
    source = tmp_path / "photos"
    cache_base = tmp_path / "cache"
    cache_dir = _make_cache(cache_base, source)
    connection = sqlite3.connect(cache_dir / "db" / "metadata.db")
    connection.execute("CREATE TABLE photo_metadata (file_path TEXT)")
    connection.execute(
        "INSERT INTO photo_metadata VALUES (?)", (str(tmp_path / "old" / "a.jpg"),)
    )
    connection.commit()
    connection.close()
    assert scan_cache(cache_base, "").folders[0].source_folder == str(source)


def test_discovery_groups_missing_then_existing_then_ignored_alphabetically(tmp_path):
    cache_base = tmp_path / "cache"
    favorite = tmp_path / "favorite"
    favorite.mkdir()
    sources = [
        tmp_path / "a-existing",
        tmp_path / "z-missing",
        favorite / "z-existing",
        favorite / "a-missing",
        favorite / "a-existing",
        tmp_path / "favorite-sibling" / "existing",
    ]
    existing = [sources[0], sources[2], sources[4], sources[5]]
    for source in existing:
        source.mkdir(parents=True)
    for source in sources:
        _make_cache(cache_base, source)
    result = scan_cache(cache_base, str(favorite))
    missing = sorted([str(sources[1]), str(sources[3])])
    normal = sorted([str(sources[0]), str(sources[5])])
    ignored = sorted([str(sources[2]), str(sources[4])])
    assert [
        folder.source_folder for folder in result.folders
    ] == missing + normal + ignored
    assert [folder.missing for folder in result.folders] == [
        True,
        True,
        False,
        False,
        False,
        False,
    ]
    assert [folder.ignored for folder in result.folders] == [
        False,
        False,
        False,
        False,
        True,
        True,
    ]
    assert not any(folder.ignored for folder in scan_cache(cache_base, "").folders)


def test_unidentifiable_caches_and_service_data_are_kept(tmp_path):
    cache_base = tmp_path / "cache"
    for name in ("a" * 32, "b" * 32, "c" * 32):
        (cache_base / name / "db").mkdir(parents=True)
    (cache_base / ("a" * 32) / "db" / "metadata.db").write_text("invalid sqlite")
    connection = sqlite3.connect(cache_base / ("b" * 32) / "db" / "metadata.db")
    connection.execute("CREATE TABLE folder_metadata (data TEXT, value TEXT)")
    connection.commit()
    connection.close()
    flickr = cache_base / "flickr"
    flickr.mkdir()
    (flickr / "oauth-tokens.sqlite").write_bytes(b"credentials")
    result = scan_cache(cache_base, "")
    assert result.folders == []
    assert result.unidentified_count == 3
    assert result.error == ""


def test_cleanup_removes_all_selected_cache_data_and_counts_files(tmp_path):
    cache_base = tmp_path / "cache"
    selected_source = tmp_path / "photos" / "selected"
    selected_source.mkdir(parents=True)
    original = selected_source / "a.jpg"
    original.write_bytes(b"original image")
    other_source = tmp_path / "photos" / "other"
    selected_cache = _make_cache(cache_base, selected_source)
    other_cache = _make_cache(cache_base, other_source)
    (selected_cache / "other-data").write_bytes(b"other cache data")
    flickr = cache_base / "flickr"
    flickr.mkdir()
    token = flickr / "oauth-tokens.sqlite"
    token.write_bytes(b"credentials")
    selected = [
        folder
        for folder in scan_cache(cache_base, "").folders
        if folder.source_folder == str(selected_source)
    ]
    updates = []
    result = clean_cache(cache_base, selected, lambda *args: updates.append(args))
    assert result.cleaned_folders == 1
    assert result.deleted_files == 4
    assert result.remaining_folders == 1
    assert result.errors == []
    assert not selected_cache.exists()
    assert other_cache.is_dir()
    assert token.read_bytes() == b"credentials"
    assert original.read_bytes() == b"original image"
    assert updates == [(0, 1, str(selected_source)), (1, 1, str(selected_source))]


def test_cleanup_never_follows_links_to_originals(tmp_path):
    cache_base = tmp_path / "cache"
    source = tmp_path / "photos"
    source.mkdir()
    original = source / "a.jpg"
    original.write_bytes(b"original image")
    cache_dir = _make_cache(cache_base, source)
    (cache_dir / "linked-folder").symlink_to(source, target_is_directory=True)
    (cache_dir / "linked-image.jpg").symlink_to(original)
    linked_cache = cache_base / ("a" * 32)
    linked_cache.symlink_to(source, target_is_directory=True)
    scan = scan_cache(cache_base, "")
    assert len(scan.folders) == 1
    result = clean_cache(cache_base, scan.folders, lambda *_args: None)
    assert result.deleted_files == 5  # DB, two thumbnails, and two links.
    assert not cache_dir.exists()
    assert linked_cache.is_symlink()
    assert original.read_bytes() == b"original image"


@pytest.mark.parametrize(
    "unsafe_kind", ["outside", "replacement-link", "contains-source"]
)
def test_cleanup_rejects_unsafe_targets(tmp_path, unsafe_kind):
    cache_base = tmp_path / "cache"
    cache_base.mkdir()
    source = tmp_path / "photos"
    source.mkdir()
    original = source / "a.jpg"
    original.write_bytes(b"original image")
    if unsafe_kind == "outside":
        target = source
    elif unsafe_kind == "replacement-link":
        target = cache_base / ("a" * 32)
        target.symlink_to(source, target_is_directory=True)
    else:
        target = cache_base / ("a" * 32)
        target.mkdir()
        source = target / "photos"
        source.mkdir()
        original = source / "a.jpg"
        original.write_bytes(b"original image")
    result = clean_cache(
        cache_base, [CacheFolder(str(source), (target,))], lambda *_args: None
    )
    assert result.cleaned_folders == 0
    assert result.deleted_files == 0
    assert len(result.errors) == 1
    assert original.read_bytes() == b"original image"


def test_partial_cleanup_reports_actual_deletions_and_continues(tmp_path, monkeypatch):
    cache_base = tmp_path / "cache"
    first = _make_cache(cache_base, tmp_path / "a")
    second = _make_cache(cache_base, tmp_path / "b")
    remove = module.shutil.rmtree

    def partly_locked(directory, *, onexc):
        if directory == first:
            (directory / "thumb" / "hq" / "a.jpg").unlink()
            onexc(None, directory, PermissionError("locked"))
        else:
            remove(directory, onexc=onexc)

    monkeypatch.setattr(module.shutil, "rmtree", partly_locked)
    result = clean_cache(
        cache_base, scan_cache(cache_base, "").folders, lambda *_args: None
    )
    assert result.cleaned_folders == 2
    assert result.deleted_files == 4
    assert result.remaining_folders == 1
    assert "locked" in result.errors[0]
    assert first.exists()
    assert not second.exists()


def _selection(cache_base, favorite, qapp):
    dialog = CacheSelectionDialog(cache_base, str(favorite) if favorite else "")
    dialog._scan_started = True
    dialog._on_scanned(scan_cache(cache_base, str(favorite) if favorite else ""))
    dialog.show()
    qapp.processEvents()
    return dialog


def test_selection_groups_styles_tooltips_and_check_controls(qapp, tmp_path):
    cache_base = tmp_path / "cache"
    favorite = tmp_path / "favorite"
    missing = favorite / "missing"
    outside = tmp_path / "a-existing"
    outside.mkdir()
    inside = favorite / "b-existing"
    inside.mkdir(parents=True)
    for source in (outside, inside, missing):
        _make_cache(cache_base, source)
    with managed_modal_dialog(_selection(cache_base, favorite, qapp)) as dialog:
        rows = dialog._rows
        assert [item.text() for item, _ in rows] == [str(missing), str(outside)]
        assert rows[0][0].font().bold()
        assert not rows[1][0].font().bold()
        assert all(item.foreground().color() != QColor("red") for item, _ in rows)
        assert all(item.checkState() == Qt.CheckState.Checked for item, _ in rows)
        assert dialog.folder_list.textElideMode() == Qt.TextElideMode.ElideLeft
        assert (
            dialog.folder_list.horizontalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        dialog.include_ignored_button.click()
        assert [item.text() for item, _ in rows] == [
            str(missing),
            str(outside),
            "b-existing",
        ]
        assert rows[-1][0].toolTip() == str(inside)
        assert rows[-1][0].foreground().color() == QColor("red")
        assert rows[-1][0].checkState() == Qt.CheckState.Unchecked
        assert not rows[-1][0].font().bold()
        dialog.uncheck_all_button.click()
        assert not dialog.button("ok").isEnabled()
        dialog.check_all_button.click()
        assert all(item.checkState() == Qt.CheckState.Checked for item, _ in rows)
        assert dialog.button("ok").isEnabled()
        assert dialog.button("cancel").x() < dialog.button("ok").x()
        dialog.reject()


def test_cancel_confirmation_returns_to_selection_and_ok_accepts(qapp, tmp_path):
    cache_base = tmp_path / "cache"
    cache_dir = _make_cache(cache_base, tmp_path / "photos")
    with managed_modal_dialog(_selection(cache_base, "", qapp)) as dialog:
        observed = []

        def answer(accept):
            modal = QApplication.activeModalWidget()
            observed.append(modal.parentWidget() == dialog)
            observed.append(
                "The cache for 1 folders will be deleted. Continue?"
                in [label.text() for label in modal.findChildren(QLabel)]
            )
            buttons = {
                button.text(): button for button in modal.findChildren(QPushButton)
            }
            observed.append(buttons["Cancel"].x() < buttons["OK"].x())
            buttons["OK" if accept else "Cancel"].click()

        QTimer.singleShot(0, lambda: answer(False))
        dialog._on_ok()
        assert dialog.isVisible()
        assert dialog.selected_folders == []
        assert dialog._rows[0][0].checkState() == Qt.CheckState.Checked
        assert cache_dir.exists()
        QTimer.singleShot(0, lambda: answer(True))
        dialog._on_ok()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert len(dialog.selected_folders) == 1
        assert cache_dir.exists()  # Selection and confirmation never delete files.
        assert observed == [True] * 6


def test_progress_height_is_stable_and_path_elides_at_start(qapp, tmp_path):
    folder = CacheFolder(str(tmp_path / "photos"), (tmp_path / "cache" / ("a" * 32),))
    with managed_modal_dialog(
        CacheCleanupDialog(tmp_path / "cache", [folder])
    ) as dialog:
        dialog._started = True
        dialog.show()
        qapp.processEvents()
        initial = dialog.size()
        for path in ("/short", "/long-parent" * 100 + "/last-folder", "/short-again"):
            dialog._on_progress(0, 1, path)
            qapp.processEvents()
            assert dialog.size() == initial
            if path.endswith("/last-folder"):
                assert dialog.path_label.text().startswith("…")
                assert dialog.path_label.text().endswith("/last-folder")
                assert dialog.path_label.toolTip() == path
        dialog._on_progress(1, 1, "/last-folder")
        assert dialog.progress_bar.text() == "1/1"
        assert dialog.progress_count_label.text() == "1/1"
        dialog.reject()
        assert dialog.isVisible()  # Running deletion cannot be dismissed.
        dialog._on_finished(CacheCleanupResult(1, 3, 2))
        qapp.processEvents()
        assert dialog.progress_bar.isHidden()
        assert dialog.progress_row.isHidden()
        assert (
            dialog.summary_text.toPlainText()
            == "Image folders cleaned: 1\nFiles deleted: 3\n"
            "Image cache folders remaining: 2"
        )
        dialog.accept()


@pytest.mark.parametrize("current_workspace_selected", [False, True])
def test_full_modal_workflow_uses_background_workers(
    qapp, tmp_path, monkeypatch, current_workspace_selected
):
    cache_base = tmp_path / "cache"
    set_cache_base_dir(cache_base)
    source = tmp_path / "photos"
    cache_dir = _make_cache(cache_base, source)
    window = QWidget()
    window.photo_model = SimpleNamespace(
        source_folders=[str(source)] if current_workspace_selected else []
    )
    window._prepare_workspace_for_cache_cleanup = Mock()
    monkeypatch.setattr(module, "get_user_setting", lambda _key: "")
    summaries = []
    errors = []
    timer = QTimer()
    deadline = time.monotonic() + 5

    def tick():
        dialog = QApplication.activeModalWidget()
        if time.monotonic() > deadline:
            errors.append("Timed out waiting for cleanup")
            if dialog is not None:
                dialog.done(QDialog.DialogCode.Rejected)
            return
        if (
            isinstance(dialog, CacheSelectionDialog)
            and dialog.current_screen_id == "select"
        ):
            # A distinct timer answers the nested confirmation event loop.
            QTimer.singleShot(0, lambda: QApplication.activeModalWidget().accept())
            dialog.button("ok").click()
        elif (
            isinstance(dialog, CacheCleanupDialog)
            and dialog.current_screen_id == "result"
        ):
            summaries.append(dialog.result_data)
            dialog.button("ok").click()

    timer.timeout.connect(tick)
    timer.start(10)
    try:
        launch_clean_cache(window)
    finally:
        timer.stop()
        QThreadPool.globalInstance().waitForDone()
        window.close()
    assert errors == []
    assert len(summaries) == 1
    assert summaries[0].cleaned_folders == 1
    assert summaries[0].deleted_files == 3
    assert summaries[0].remaining_folders == 0
    assert not cache_dir.exists()
    assert window._prepare_workspace_for_cache_cleanup.call_count == int(
        current_workspace_selected
    )


def test_workspace_cleanup_stops_writers_before_unloading(qapp, monkeypatch):  # noqa: ARG001
    calls = []
    pool = QThreadPool()
    window = SimpleNamespace(
        _background_db_save_pool=pool,
        edit_panel=SimpleNamespace(
            shutdown_background_saves=lambda *_args, **_kwargs: (
                calls.append("drain edits") or True
            )
        ),
        _stop_folder_watcher=lambda: calls.append("stop watcher"),
        media_manager=SimpleNamespace(
            stop=lambda **_kwargs: calls.append("stop media")
        ),
        _unload_workspace=lambda: calls.append("unload"),
    )
    monkeypatch.setattr(
        "piqopiqo.main_window.drain_qthread_pool",
        lambda *_args: calls.append("drain labels") or True,
    )
    MainWindow._prepare_workspace_for_cache_cleanup(window)
    assert calls == [
        "drain labels",
        "drain edits",
        "stop watcher",
        "stop media",
        "unload",
    ]
