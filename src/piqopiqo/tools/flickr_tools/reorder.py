"""Flickr album reorder workflow."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import TYPE_CHECKING

from attrs import define, field
from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.dialogs.settings_redirect import (
    prompt_open_settings_for_missing_setting,
)
from piqopiqo.qt_workers import PythonOwnedRunnable
from piqopiqo.ssf.settings_state import (
    RuntimeSettingKey,
    StateKey,
    UserSettingKey,
    get_runtime_setting,
    get_state_value,
    get_support_dir_macos,
    get_user_setting,
    set_state_value,
)
from piqopiqo.tools.flickr_tools.auth_flow import ensure_flickr_authenticated
from piqopiqo.tools.flickr_tools.upload.constants import API_RETRIES
from piqopiqo.tools.flickr_utils import (
    FlickrOperationCancelled,
    all_pages,
    create_flickr_client,
    extract_album_id,
)
from piqopiqo.tools.tool_flow import (
    ToolButton,
    ToolFlowDialog,
    ToolScreen,
    ToolTaskHandle,
    ToolWorkflow,
)

if TYPE_CHECKING:
    from piqopiqo.main_window import MainWindow


BACKUP_FOLDER_NAME = "flickr-album-orders"
BACKUP_PREFIX = "flickr-album-order-"


@define(frozen=True)
class FlickrAlbumOrderEntry:
    album_id: str
    title: str


@define
class FlickrReorderResult:
    album_count: int = 0
    albums_examined: int = 0
    invalid_photo_dates: int = 0
    reordered: bool = False
    already_ordered: bool = False
    cancelled: bool = False
    backup_path: str = ""
    undated_albums: list[str] = field(factory=list)
    warnings: list[str] = field(factory=list)
    error_message: str = ""


def _album_title(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("_content") or "").strip()
    return str(value or "").strip()


def _taken_date(value: object):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def build_reordered_album_ids(
    albums: list[FlickrAlbumOrderEntry],
    modal_dates: dict[str, object],
    *,
    from_album_id: str = "",
) -> list[str]:
    """Build the complete album order, sorting only the requested prefix."""
    if not albums:
        return []
    selected_count = len(albums)
    if from_album_id:
        for index, album in enumerate(albums):
            if album.album_id == from_album_id:
                selected_count = index + 1
                break
        else:
            raise ValueError(f"Album {from_album_id} is not in your album list.")

    selected = albums[:selected_count]
    tail = albums[selected_count:]
    ordered = sorted(
        selected,
        key=lambda album: modal_dates[album.album_id],
        reverse=True,
    )
    return [album.album_id for album in (*ordered, *tail)]


def save_album_order_backup(
    album_ids: list[str],
    *,
    support_dir: str | Path,
    keep: int,
    now: datetime | None = None,
) -> tuple[Path, list[str]]:
    """Atomically save an ID-array backup and prune older tool backups."""
    backup_dir = Path(support_dir) / BACKUP_FOLDER_NAME
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    target = backup_dir / f"{BACKUP_PREFIX}{stamp}.json"
    suffix = 2
    while target.exists():
        target = backup_dir / f"{BACKUP_PREFIX}{stamp}-{suffix}.json"
        suffix += 1

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=backup_dir,
            prefix=".flickr-album-order-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            json.dump([str(album_id) for album_id in album_ids], stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            temp_path = stream.name
        os.replace(temp_path, target)
    except Exception:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass
        raise

    warnings: list[str] = []
    dated_backups: list[tuple[int, str, Path]] = []
    for path in backup_dir.glob(f"{BACKUP_PREFIX}*.json"):
        try:
            dated_backups.append((path.stat().st_mtime_ns, path.name, path))
        except OSError as ex:
            warnings.append(f"Could not inspect old backup {path.name}: {ex}")
    backups = [row[2] for row in sorted(dated_backups, reverse=True)]
    for old_path in backups[max(1, int(keep)) :]:
        try:
            old_path.unlink()
        except OSError as ex:
            warnings.append(f"Could not remove old backup {old_path.name}: {ex}")
    return target, warnings


class _FlickrReorderSignals(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)


class FlickrReorderWorker(PythonOwnedRunnable):
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        from_album_id: str,
        save_existing_order: bool,
        support_dir: str | Path,
        backup_limit: int,
        quick_timeout_s: float,
        very_long_timeout_s: float,
    ) -> None:
        super().__init__()
        self._api_key = api_key
        self._api_secret = api_secret
        self._from_album_id = from_album_id
        self._save_existing_order = bool(save_existing_order)
        self._support_dir = Path(support_dir)
        self._backup_limit = max(1, int(backup_limit))
        self._quick_timeout_s = float(quick_timeout_s)
        self._very_long_timeout_s = float(very_long_timeout_s)
        self._cancel_requested = threading.Event()
        self.signals = _FlickrReorderSignals()

    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def run(self) -> None:
        result = FlickrReorderResult()
        try:
            flickr = create_flickr_client(
                self._api_key,
                self._api_secret,
                timeout_s=self._quick_timeout_s,
            )
            raw_albums = all_pages(
                "photosets",
                "photoset",
                flickr.photosets.getList,
                num_retries=API_RETRIES,
                cancel_event=self._cancel_requested,
                per_page=500,
                timeout=self._quick_timeout_s,
            )
            albums = [
                FlickrAlbumOrderEntry(
                    album_id=str(album.get("id") or "").strip(),
                    title=_album_title(album.get("title")),
                )
                for album in raw_albums
                if isinstance(album, dict) and str(album.get("id") or "").strip()
            ]
            result.album_count = len(albums)
            if not albums:
                raise RuntimeError("No Flickr albums were returned.")

            selected_count = len(albums)
            if self._from_album_id:
                ids = [album.album_id for album in albums]
                if self._from_album_id not in ids:
                    raise ValueError(
                        f"Album {self._from_album_id} is not in your album list."
                    )
                selected_count = ids.index(self._from_album_id) + 1

            modal_dates: dict[str, object] = {}
            for index, album in enumerate(albums[:selected_count], start=1):
                if self._cancel_requested.is_set():
                    raise FlickrOperationCancelled()
                self.signals.progress.emit(
                    index - 1,
                    selected_count,
                    f"Reading {album.title or album.album_id}...",
                )
                photos = all_pages(
                    "photoset",
                    "photo",
                    flickr.photosets.getPhotos,
                    photoset_id=album.album_id,
                    extras="date_taken",
                    per_page=500,
                    timeout=self._quick_timeout_s,
                    num_retries=API_RETRIES,
                    cancel_event=self._cancel_requested,
                )
                counts: Counter = Counter()
                first_seen: list = []
                for photo in photos:
                    if not isinstance(photo, dict):
                        result.invalid_photo_dates += 1
                        continue
                    date = _taken_date(photo.get("datetaken"))
                    if date is None:
                        result.invalid_photo_dates += 1
                        continue
                    if date not in counts:
                        first_seen.append(date)
                    counts[date] += 1
                if not counts:
                    result.undated_albums.append(album.title or album.album_id)
                else:
                    highest = max(counts.values())
                    modal_dates[album.album_id] = next(
                        date for date in first_seen if counts[date] == highest
                    )
                result.albums_examined += 1

            if result.undated_albums:
                result.error_message = (
                    "No albums were reordered because these albums contain no "
                    "valid photo taken dates: " + ", ".join(result.undated_albums)
                )
                self.signals.finished.emit(result)
                return

            current_order = [album.album_id for album in albums]
            new_order = build_reordered_album_ids(
                albums,
                modal_dates,
                from_album_id=self._from_album_id,
            )
            if new_order == current_order:
                result.already_ordered = True
                self.signals.finished.emit(result)
                return
            if self._cancel_requested.is_set():
                raise FlickrOperationCancelled()

            if self._save_existing_order:
                backup_path, warnings = save_album_order_backup(
                    current_order,
                    support_dir=self._support_dir,
                    keep=self._backup_limit,
                )
                result.backup_path = str(backup_path)
                result.warnings.extend(warnings)
            if self._cancel_requested.is_set():
                raise FlickrOperationCancelled()

            self.signals.progress.emit(
                0,
                0,
                "Applying the new album order...",
            )
            flickr.photosets.orderSets(
                photoset_ids=",".join(new_order),
                timeout=self._very_long_timeout_s,
            )
            result.reordered = True
        except FlickrOperationCancelled:
            result.cancelled = True
        except Exception as ex:
            result.error_message = str(ex)
        self.signals.finished.emit(result)


class FlickrReorderDialog(ToolFlowDialog):
    def __init__(
        self,
        *,
        window: MainWindow,
        api_key: str,
        api_secret: str,
        parent=None,
    ) -> None:
        self._window = window
        self._api_key = api_key
        self._api_secret = api_secret
        self._worker: FlickrReorderWorker | None = None
        self._result: FlickrReorderResult | None = None
        self.from_album_edit: QLineEdit | None = None
        self.save_order_check: QCheckBox | None = None

        workflow = ToolWorkflow(
            initial_screen="input",
            screens={
                "input": ToolScreen(
                    id="input",
                    title="Reorder Flickr Albums",
                    build=lambda dialog: dialog._build_input(),
                    buttons=(
                        ToolButton("cancel", "Cancel"),
                        ToolButton("reorder", "Reorder Albums", default=True),
                    ),
                    min_width=600,
                ),
                "progress": ToolScreen(
                    id="progress",
                    title="Reorder Flickr Albums",
                    build=lambda dialog: QWidget(dialog),
                    buttons=(ToolButton("cancel_work", "Cancel"),),
                    min_width=520,
                    show_progress=True,
                    close_policy="cancel",
                ),
                "result": ToolScreen(
                    id="result",
                    title="Reorder Flickr Albums",
                    build=lambda dialog: dialog._build_result(),
                    buttons=(ToolButton("close", "Close", default=True),),
                    min_width=520,
                ),
            },
            transitions={
                ("input", "cancel"): lambda dialog, event: dialog.reject(),
                ("input", "reorder"): lambda dialog, event: dialog._start(),
                ("progress", "cancel_work"): (
                    lambda dialog, event: dialog._cancel_work()
                ),
                ("progress", "progress"): (
                    lambda dialog, event: dialog._on_progress(*event.args)
                ),
                ("progress", "finished"): (
                    lambda dialog, event: dialog._on_finished(*event.args)
                ),
                ("result", "close"): lambda dialog, event: dialog.accept(),
            },
        )
        super().__init__(workflow, parent=parent or window)
        self._set_unsaved_changes_state(
            lambda: (
                self.from_album_edit.text(),
                self.save_order_check.isChecked(),
            )
        )

    def _build_input(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        from_album_required = bool(
            get_runtime_setting(RuntimeSettingKey.FLICKR_REORDER_FROM_ALBUM_REQUIRED)
        )
        self.from_album_edit = QLineEdit(widget)
        placeholder = (
            "Flickr album ID or URL"
            if from_album_required
            else "Optional Flickr album ID or URL"
        )
        self.from_album_edit.setPlaceholderText(placeholder)
        form.addRow("Reorder from album", self.from_album_edit)
        self.save_order_check = QCheckBox("Save the existing order before changes")
        self.save_order_check.setChecked(
            bool(get_state_value(StateKey.FLICKR_REORDER_SAVE_EXISTING_ORDER))
        )
        form.addRow("", self.save_order_check)
        layout.addLayout(form)
        layout.addSpacing(int(get_runtime_setting(RuntimeSettingKey.PADDING)))
        return widget

    def _start(self) -> None:
        assert self.from_album_edit is not None
        assert self.save_order_check is not None
        from_text = self.from_album_edit.text().strip()
        from_album_required = bool(
            get_runtime_setting(RuntimeSettingKey.FLICKR_REORDER_FROM_ALBUM_REQUIRED)
        )
        if from_album_required and not from_text:
            QMessageBox.warning(
                self,
                "Reorder Flickr Albums",
                "Enter a Flickr album ID or URL.",
            )
            return

        from_album_id = ""
        if from_text:
            try:
                from_album_id = extract_album_id(from_text)
            except ValueError as ex:
                QMessageBox.warning(self, "Reorder Flickr Albums", str(ex))
                return

        save_order = self.save_order_check.isChecked()
        set_state_value(StateKey.FLICKR_REORDER_SAVE_EXISTING_ORDER, save_order)
        if not ensure_flickr_authenticated(
            self,
            title="Reorder Flickr Albums",
            api_key=self._api_key,
            api_secret=self._api_secret,
        ):
            return

        self._worker = FlickrReorderWorker(
            api_key=self._api_key,
            api_secret=self._api_secret,
            from_album_id=from_album_id,
            save_existing_order=save_order,
            support_dir=get_support_dir_macos(),
            backup_limit=int(
                get_runtime_setting(RuntimeSettingKey.FLICKR_REORDER_BACKUP_LIMIT)
            ),
            quick_timeout_s=float(
                get_runtime_setting(RuntimeSettingKey.FLICKR_API_QUICK_TIMEOUT_S)
            ),
            very_long_timeout_s=float(
                get_runtime_setting(RuntimeSettingKey.FLICKR_API_VERY_LONG_TIMEOUT_S)
            ),
        )
        self.transition_to("progress")
        self.set_status("Reading the current Flickr album order...")
        self.set_progress(0, 0)
        self.start_task(
            "flickr_reorder",
            ToolTaskHandle.from_qrunnable(
                worker=self._worker,
                pool=QThreadPool.globalInstance(),
                signal_map={
                    self._worker.signals.progress: "progress",
                    self._worker.signals.finished: "finished",
                },
            ),
        )

    def _cancel_work(self) -> None:
        if self._worker is None:
            return
        self._worker.request_cancel()
        button = self.button("cancel_work")
        if button is not None:
            button.setEnabled(False)
        self.set_status("Canceling before the next Flickr operation...")

    def _on_progress(self, completed: int, total: int, status: str) -> None:
        self.set_progress(completed, total)
        self.set_status(status)

    def _on_finished(self, result: FlickrReorderResult) -> None:
        self.stop_task("flickr_reorder", cancel=False)
        self._result = result
        self.transition_to("result")

    def _build_result(self) -> QWidget:
        result = self._result or FlickrReorderResult()
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        if result.cancelled:
            headline = "Canceled before applying a new album order."
        elif result.reordered:
            headline = "Flickr albums were reordered successfully."
        elif result.already_ordered:
            headline = "The Flickr albums were already in the calculated order."
        else:
            headline = "Flickr albums were not reordered."
        lines = [
            headline,
            f"Albums returned: {result.album_count}",
            f"Albums examined: {result.albums_examined}",
            f"Photo dates ignored as invalid: {result.invalid_photo_dates}",
        ]
        if result.backup_path:
            lines.append(f"Existing order saved to: {result.backup_path}")
        if result.error_message:
            lines.append(f"Error: {result.error_message}")
        summary = QTextEdit(widget)
        summary.setObjectName("flickrReorderSummaryText")
        summary.setReadOnly(True)
        summary.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        summary.setPlainText("\n".join(lines))
        palette = summary.palette()
        palette.setColor(
            QPalette.ColorRole.Base,
            palette.color(QPalette.ColorRole.AlternateBase),
        )
        summary.setPalette(palette)
        visible_lines = min(max(len(lines), 2), 8)
        text_height = summary.fontMetrics().lineSpacing() * visible_lines
        frame_height = summary.frameWidth() * 2
        summary.setFixedHeight(text_height + frame_height + 16)
        layout.addWidget(summary)
        details_lines = [*result.warnings]
        if result.undated_albums:
            details_lines.append(
                "Albums without a usable date: " + ", ".join(result.undated_albums)
            )
        if details_lines:
            details = QTextEdit(widget)
            details.setReadOnly(True)
            details.setPlainText("\n".join(details_lines))
            details.setMaximumHeight(130)
            layout.addWidget(details)
        return widget


def launch_flickr_reorder(window: MainWindow) -> None:
    api_key = str(get_user_setting(UserSettingKey.FLICKR_API_KEY) or "").strip()
    api_secret = str(get_user_setting(UserSettingKey.FLICKR_API_SECRET) or "").strip()
    if not api_key or not api_secret:
        should_open = prompt_open_settings_for_missing_setting(
            window,
            title="Reorder Flickr Albums",
            text=(
                "Flickr API key and Flickr API secret are empty.\n"
                "Set them in Settings > External/Tools > Flickr."
            ),
        )
        if should_open:
            window.open_settings_for_key(UserSettingKey.FLICKR_API_KEY)
        return

    dialog = FlickrReorderDialog(
        window=window,
        api_key=api_key,
        api_secret=api_secret,
        parent=window,
    )
    dialog.exec()
