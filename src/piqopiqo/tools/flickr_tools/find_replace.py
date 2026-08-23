"""Find and replace Flickr photo titles and tags."""

from __future__ import annotations

from functools import partial
import threading
from typing import TYPE_CHECKING

from attrs import define, field
from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.components.ellided_label import EllidedLabel
from piqopiqo.dialogs.settings_redirect import (
    prompt_open_settings_for_missing_setting,
)
from piqopiqo.keyword_utils import (
    normalize_keyword_list,
    parse_keywords,
    validate_keywords_balanced,
)
from piqopiqo.qt_workers import PythonOwnedRunnable
from piqopiqo.ssf.settings_state import (
    RuntimeSettingKey,
    UserSettingKey,
    get_runtime_setting,
    get_user_setting,
)
from piqopiqo.tools.edit_tools.service import (
    FindReplaceSpec,
    apply_replacement,
    validate_find_replace_spec,
)
from piqopiqo.tools.flickr_tools.auth_flow import ensure_flickr_authenticated
from piqopiqo.tools.flickr_tools.upload.constants import API_RETRIES
from piqopiqo.tools.flickr_utils import (
    FlickrOperationCancelled,
    all_pages,
    create_flickr_client,
    extract_album_id,
    extract_photo_id,
    format_flickr_tags,
    retry,
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


SORT_OPTIONS = (
    "date-posted-desc",
    "date-posted-asc",
    "date-taken-desc",
    "date-taken-asc",
)
NO_TITLE_TEXT = "<No title>"


@define(frozen=True)
class FlickrFindReplaceOptions:
    source: str
    album_id: str
    start_photo_id: str
    end_photo_id: str
    limit: int | None
    sort: str
    replacement: FindReplaceSpec


@define
class FlickrFindReplaceResult:
    retrieved: int = 0
    in_scope: int = 0
    processed: int = 0
    eligible: int = 0
    title_changed: int = 0
    tags_removed: int = 0
    tags_added: int = 0
    photos_changed: int = 0
    unchanged: int = 0
    cancelled: bool = False
    error_message: str = ""
    errors: list[str] = field(factory=list)
    failed_photo_ids: set[str] = field(factory=set)


def _photo_title(photo: dict) -> str:
    title = photo.get("title")
    if isinstance(title, dict):
        return str(title.get("_content") or "")
    return str(title or "")


def slice_photo_range(
    photos: list[dict],
    *,
    start_photo_id: str = "",
    end_photo_id: str = "",
    limit: int | None = None,
) -> list[dict]:
    """Return an exact inclusive range and reject absent/reversed boundaries."""
    ids = [str(photo.get("id") or "") for photo in photos]
    start_index = 0
    end_index = len(photos) - 1
    if start_photo_id:
        if start_photo_id not in ids:
            raise ValueError(f"Start photo {start_photo_id} was not found in scope.")
        start_index = ids.index(start_photo_id)
    if end_photo_id:
        if end_photo_id not in ids:
            raise ValueError(f"End photo {end_photo_id} was not found in scope.")
        end_index = ids.index(end_photo_id)
    if start_index > end_index:
        raise ValueError("Start photo occurs after end photo in the chosen order.")
    selected = photos[start_index : end_index + 1]
    if limit is not None:
        selected = selected[: max(0, int(limit))]
    return selected


class _FlickrFindReplaceSignals(QObject):
    progress = Signal(int, int, str, str)
    finished = Signal(object)


class FlickrFindReplaceWorker(PythonOwnedRunnable):
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        options: FlickrFindReplaceOptions,
        quick_timeout_s: float,
    ) -> None:
        super().__init__()
        self._api_key = api_key
        self._api_secret = api_secret
        self._options = options
        self._quick_timeout_s = float(quick_timeout_s)
        self._cancel_requested = threading.Event()
        self.signals = _FlickrFindReplaceSignals()

    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def _fetch_photos(self, flickr) -> tuple[list[dict], int]:
        options = self._options
        if options.source == "album":
            raw = all_pages(
                "photoset",
                "photo",
                flickr.photosets.getPhotos,
                photoset_id=options.album_id,
                extras="date_taken",
                per_page=500,
                timeout=self._quick_timeout_s,
                num_retries=API_RETRIES,
                cancel_event=self._cancel_requested,
            )
        else:
            start_info = retry(
                API_RETRIES,
                lambda: flickr.photos.getInfo(
                    photo_id=options.start_photo_id,
                    timeout=self._quick_timeout_s,
                ),
            )
            end_info = retry(
                API_RETRIES,
                lambda: flickr.photos.getInfo(
                    photo_id=options.end_photo_id,
                    timeout=self._quick_timeout_s,
                ),
            )
            start_posted = int(start_info["photo"]["dates"]["posted"])
            end_posted = int(end_info["photo"]["dates"]["posted"])
            raw = all_pages(
                "photos",
                "photo",
                flickr.photos.search,
                user_id="me",
                min_upload_date=min(start_posted, end_posted),
                max_upload_date=max(start_posted, end_posted),
                sort=options.sort,
                extras="date_taken",
                per_page=500,
                timeout=self._quick_timeout_s,
                num_retries=API_RETRIES,
                cancel_event=self._cancel_requested,
            )

        photos = [photo for photo in raw if isinstance(photo, dict)]
        selected = slice_photo_range(
            photos,
            start_photo_id=options.start_photo_id,
            end_photo_id=options.end_photo_id,
            limit=options.limit,
        )
        return selected, len(photos)

    def _record_error(
        self,
        result: FlickrFindReplaceResult,
        photo_id: str,
        operation: str,
        ex: Exception,
    ) -> None:
        result.failed_photo_ids.add(photo_id)
        result.errors.append(f"{photo_id} — {operation}: {ex}")

    def run(self) -> None:
        result = FlickrFindReplaceResult()
        try:
            flickr = create_flickr_client(
                self._api_key,
                self._api_secret,
                timeout_s=self._quick_timeout_s,
            )
            photos, retrieved = self._fetch_photos(flickr)
            result.retrieved = retrieved
            result.in_scope = len(photos)

            spec = self._options.replacement.normalized()
            for photo in photos:
                if self._cancel_requested.is_set():
                    raise FlickrOperationCancelled()
                photo_id = str(photo.get("id") or "").strip()
                title = _photo_title(photo)
                self.signals.progress.emit(
                    result.processed,
                    result.in_scope,
                    photo_id,
                    title,
                )
                result.processed += 1

                title_outcome = apply_replacement(title, [], spec)
                if not title_outcome.eligible:
                    result.unchanged += 1
                    continue
                result.eligible += 1
                photo_changed = False

                if title_outcome.title_changed:
                    try:
                        retry(
                            API_RETRIES,
                            partial(
                                flickr.photos.setMeta,
                                photo_id=photo_id,
                                title=title_outcome.title,
                                timeout=self._quick_timeout_s,
                            ),
                        )
                        result.title_changed += 1
                        photo_changed = True
                    except Exception as ex:
                        self._record_error(result, photo_id, "replace title", ex)

                if spec.remove_tags or spec.add_tags:
                    try:
                        info = retry(
                            API_RETRIES,
                            partial(
                                flickr.photos.getInfo,
                                photo_id=photo_id,
                                timeout=self._quick_timeout_s,
                            ),
                        )
                        tag_nodes = info.get("photo", {}).get("tags", {}).get("tag", [])
                        if not isinstance(tag_nodes, list):
                            tag_nodes = [tag_nodes] if tag_nodes else []
                    except Exception as ex:
                        self._record_error(result, photo_id, "read tags", ex)
                        tag_nodes = None

                    if tag_nodes is not None:
                        remove_set = set(spec.remove_tags)
                        successful_removed_raw: list[str] = []
                        remaining_raw: list[str] = []
                        for node in tag_nodes:
                            if not isinstance(node, dict):
                                continue
                            raw = str(node.get("raw") or "")
                            if raw not in remove_set:
                                remaining_raw.append(raw)
                                continue
                            tag_id = str(node.get("id") or "")
                            try:
                                retry(
                                    API_RETRIES,
                                    partial(
                                        flickr.photos.removeTag,
                                        tag_id=tag_id,
                                        timeout=self._quick_timeout_s,
                                    ),
                                )
                                successful_removed_raw.append(raw)
                                result.tags_removed += 1
                                photo_changed = True
                            except Exception as ex:
                                remaining_raw.append(raw)
                                self._record_error(
                                    result,
                                    photo_id,
                                    f"remove tag {raw!r}",
                                    ex,
                                )

                        should_add = bool(spec.add_tags) and (
                            not spec.add_only_if_removed or bool(successful_removed_raw)
                        )
                        if should_add:
                            remaining_keys = {tag.casefold() for tag in remaining_raw}
                            add_values = [
                                tag
                                for tag in spec.add_tags
                                if tag.casefold() not in remaining_keys
                            ]
                            add_values = normalize_keyword_list(add_values)
                            api_tags = format_flickr_tags(add_values)
                            if api_tags:
                                try:
                                    retry(
                                        API_RETRIES,
                                        partial(
                                            flickr.photos.addTags,
                                            photo_id=photo_id,
                                            tags=api_tags,
                                            timeout=self._quick_timeout_s,
                                        ),
                                    )
                                    result.tags_added += len(add_values)
                                    photo_changed = True
                                except Exception as ex:
                                    self._record_error(
                                        result,
                                        photo_id,
                                        "add tags",
                                        ex,
                                    )

                if photo_changed:
                    result.photos_changed += 1
                else:
                    result.unchanged += 1
        except FlickrOperationCancelled:
            result.cancelled = True
        except Exception as ex:
            result.error_message = str(ex)
        self.signals.finished.emit(result)


class FlickrFindReplaceDialog(ToolFlowDialog):
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
        self._worker: FlickrFindReplaceWorker | None = None
        self._result: FlickrFindReplaceResult | None = None

        self.source_combo: QComboBox | None = None
        self.album_edit: QLineEdit | None = None
        self.start_edit: QLineEdit | None = None
        self.end_edit: QLineEdit | None = None
        self.limit_edit: QLineEdit | None = None
        self.sort_combo: QComboBox | None = None
        self.title_pattern_edit: QLineEdit | None = None
        self.replace_title_check: QCheckBox | None = None
        self.title_replacement_edit: QLineEdit | None = None
        self.remove_tags_edit: QLineEdit | None = None
        self.add_tags_edit: QLineEdit | None = None
        self.add_only_if_removed_check: QCheckBox | None = None

        workflow = ToolWorkflow(
            initial_screen="input",
            screens={
                "input": ToolScreen(
                    id="input",
                    title="Flickr Find & Replace",
                    build=lambda dialog: dialog._build_input(),
                    buttons=(
                        ToolButton("cancel", "Cancel"),
                        ToolButton("apply", "Apply Changes", default=True),
                    ),
                    min_width=680,
                ),
                "progress": ToolScreen(
                    id="progress",
                    title="Flickr Find & Replace",
                    build=lambda dialog: QWidget(dialog),
                    buttons=(ToolButton("cancel_work", "Cancel"),),
                    min_width=560,
                    show_progress=True,
                    close_policy="cancel",
                ),
                "result": ToolScreen(
                    id="result",
                    title="Flickr Find & Replace",
                    build=lambda dialog: dialog._build_result(),
                    buttons=(ToolButton("close", "Close", default=True),),
                    min_width=560,
                ),
            },
            transitions={
                ("input", "cancel"): lambda dialog, event: dialog.reject(),
                ("input", "apply"): lambda dialog, event: dialog._start(),
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
        self._configure_progress_status()
        self._set_unsaved_changes_state(self._input_state)

    def _configure_progress_status(self) -> None:
        progress_layout = self.progress_row.layout()
        assert progress_layout is not None
        progress_layout.removeWidget(self.status_label)
        progress_layout.removeWidget(self.progress_count_label)

        status_widget = QWidget(self.progress_row)
        status_layout = QVBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(0)

        self.status_label.setParent(status_widget)
        self.status_label.setWordWrap(False)
        self.status_label.show()
        status_layout.addWidget(self.status_label)

        self.progress_title_label = EllidedLabel("", status_widget)
        self.progress_title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.progress_title_label.setMinimumWidth(0)
        self.progress_title_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.progress_title_label.setFixedHeight(
            self.progress_title_label.fontMetrics().lineSpacing()
        )
        status_layout.addWidget(self.progress_title_label)

        progress_layout.addWidget(status_widget, 1)
        progress_layout.addWidget(self.progress_count_label)

    def _input_state(self) -> tuple[object, ...]:
        assert self.source_combo is not None
        assert self.album_edit is not None
        assert self.start_edit is not None
        assert self.end_edit is not None
        assert self.limit_edit is not None
        assert self.sort_combo is not None
        assert self.title_pattern_edit is not None
        assert self.replace_title_check is not None
        assert self.title_replacement_edit is not None
        assert self.remove_tags_edit is not None
        assert self.add_tags_edit is not None
        assert self.add_only_if_removed_check is not None
        return (
            self.source_combo.currentIndex(),
            self.album_edit.text(),
            self.start_edit.text(),
            self.end_edit.text(),
            self.limit_edit.text(),
            self.sort_combo.currentIndex(),
            self.title_pattern_edit.text(),
            self.replace_title_check.isChecked(),
            self.title_replacement_edit.text(),
            self.remove_tags_edit.text(),
            self.add_tags_edit.text(),
            self.add_only_if_removed_check.isChecked(),
        )

    def _build_input(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)

        scope_group = QGroupBox("Flickr scope", widget)
        scope_form = QFormLayout(scope_group)
        scope_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.source_combo = QComboBox(scope_group)
        self.source_combo.addItem("Album", "album")
        self.source_combo.addItem("Photostream", "photostream")
        scope_form.addRow("Source", self.source_combo)
        self.album_edit = QLineEdit(scope_group)
        self.album_edit.setPlaceholderText("Flickr album ID or URL")
        scope_form.addRow("Album", self.album_edit)
        self.start_edit = QLineEdit(scope_group)
        self.start_edit.setPlaceholderText("Optional for albums; required for stream")
        scope_form.addRow("Start photo", self.start_edit)
        self.end_edit = QLineEdit(scope_group)
        self.end_edit.setPlaceholderText("Optional for albums; required for stream")
        scope_form.addRow("End photo", self.end_edit)
        self.limit_edit = QLineEdit(scope_group)
        self.limit_edit.setPlaceholderText("Optional positive number")
        scope_form.addRow("Maximum photos", self.limit_edit)
        self.sort_combo = QComboBox(scope_group)
        self.sort_combo.addItems(SORT_OPTIONS)
        scope_form.addRow("Photostream order", self.sort_combo)
        layout.addWidget(scope_group)

        explanation = QLabel(
            "The optional title condition is a regular expression. When set, "
            "all requested title and tag changes are limited to matching photos.",
            widget,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        changes_group = QGroupBox("Conditions and changes", widget)
        changes_form = QFormLayout(changes_group)
        changes_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.title_pattern_edit = QLineEdit(changes_group)
        self.title_pattern_edit.setPlaceholderText("Optional regular expression")
        changes_form.addRow("Title condition", self.title_pattern_edit)
        self.replace_title_check = QCheckBox(
            "Replace matching title text", changes_group
        )
        changes_form.addRow("", self.replace_title_check)
        self.title_replacement_edit = QLineEdit(changes_group)
        self.title_replacement_edit.setEnabled(False)
        self.title_replacement_edit.setPlaceholderText(
            "Replacement text; empty removes the match"
        )
        changes_form.addRow("Replace with", self.title_replacement_edit)
        self.remove_tags_edit = QLineEdit(changes_group)
        self.remove_tags_edit.setPlaceholderText("Comma-separated tags")
        changes_form.addRow("Tags to remove", self.remove_tags_edit)
        self.add_tags_edit = QLineEdit(changes_group)
        self.add_tags_edit.setPlaceholderText("Comma-separated tags")
        changes_form.addRow("Tags to add", self.add_tags_edit)
        self.add_only_if_removed_check = QCheckBox(
            "Add only when at least one listed tag was removed",
            changes_group,
        )
        changes_form.addRow("", self.add_only_if_removed_check)
        layout.addWidget(changes_group)

        self.source_combo.currentIndexChanged.connect(self._sync_source_controls)
        self.replace_title_check.toggled.connect(self.title_replacement_edit.setEnabled)
        self._sync_source_controls()
        return widget

    def _sync_source_controls(self) -> None:
        assert self.source_combo is not None
        assert self.album_edit is not None
        assert self.sort_combo is not None
        is_album = self.source_combo.currentData() == "album"
        self.album_edit.setEnabled(is_album)
        self.sort_combo.setEnabled(not is_album)

    def _read_options(self) -> FlickrFindReplaceOptions | None:
        assert self.source_combo is not None
        assert self.album_edit is not None
        assert self.start_edit is not None
        assert self.end_edit is not None
        assert self.limit_edit is not None
        assert self.sort_combo is not None
        assert self.title_pattern_edit is not None
        assert self.replace_title_check is not None
        assert self.title_replacement_edit is not None
        assert self.remove_tags_edit is not None
        assert self.add_tags_edit is not None
        assert self.add_only_if_removed_check is not None

        source = str(self.source_combo.currentData())
        album_id = ""
        start_id = ""
        end_id = ""
        try:
            if source == "album":
                album_id = extract_album_id(self.album_edit.text())
            if self.start_edit.text().strip():
                start_id = extract_photo_id(self.start_edit.text())
            if self.end_edit.text().strip():
                end_id = extract_photo_id(self.end_edit.text())
        except ValueError as ex:
            QMessageBox.warning(self, "Flickr Find & Replace", str(ex))
            return None
        if source == "photostream" and (not start_id or not end_id):
            QMessageBox.warning(
                self,
                "Flickr Find & Replace",
                "Photostream mode requires both a start and an end photo.",
            )
            return None

        limit = None
        limit_text = self.limit_edit.text().strip()
        if limit_text:
            try:
                limit = int(limit_text)
            except ValueError:
                limit = 0
            if limit <= 0:
                QMessageBox.warning(
                    self,
                    "Flickr Find & Replace",
                    "Maximum photos must be a positive whole number.",
                )
                return None

        for label, edit in (
            ("Tags to remove", self.remove_tags_edit),
            ("Tags to add", self.add_tags_edit),
        ):
            if not validate_keywords_balanced(edit.text()):
                QMessageBox.warning(
                    self,
                    "Flickr Find & Replace",
                    f"{label} contains an unmatched quote.",
                )
                return None

        spec = FindReplaceSpec(
            title_pattern=self.title_pattern_edit.text(),
            replace_title=self.replace_title_check.isChecked(),
            title_replacement=self.title_replacement_edit.text(),
            remove_tags=tuple(parse_keywords(self.remove_tags_edit.text())),
            add_tags=tuple(parse_keywords(self.add_tags_edit.text())),
            add_only_if_removed=self.add_only_if_removed_check.isChecked(),
        ).normalized()
        error = validate_find_replace_spec(spec)
        if error:
            QMessageBox.warning(self, "Flickr Find & Replace", error)
            return None

        return FlickrFindReplaceOptions(
            source=source,
            album_id=album_id,
            start_photo_id=start_id,
            end_photo_id=end_id,
            limit=limit,
            sort=self.sort_combo.currentText(),
            replacement=spec,
        )

    def _start(self) -> None:
        options = self._read_options()
        if options is None:
            return
        if not ensure_flickr_authenticated(
            self,
            title="Flickr Find & Replace",
            api_key=self._api_key,
            api_secret=self._api_secret,
        ):
            return

        self._worker = FlickrFindReplaceWorker(
            api_key=self._api_key,
            api_secret=self._api_secret,
            options=options,
            quick_timeout_s=float(
                get_runtime_setting(RuntimeSettingKey.FLICKR_API_QUICK_TIMEOUT_S)
            ),
        )
        self.transition_to("progress")
        self.progress_title_label.setText("")
        self.set_status("Retrieving the Flickr photo scope...")
        self.set_progress(0, 0)
        self.start_task(
            "flickr_find_replace",
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
        self.progress_title_label.setText("")
        self.set_status("Canceling after the current Flickr operation...")

    def _on_progress(
        self,
        completed: int,
        total: int,
        photo_id: str,
        title: str,
    ) -> None:
        display_title = str(title).replace("\r\n", " ").replace("\r", " ")
        display_title = display_title.replace("\n", " ").strip() or NO_TITLE_TEXT
        self.progress_title_label.setText(display_title)
        self.set_status(f"Photo {photo_id}")
        self.set_progress(completed, total)

    def _on_finished(self, result: FlickrFindReplaceResult) -> None:
        self.stop_task("flickr_find_replace", cancel=False)
        self._result = result
        self.transition_to("result")

    def _build_result(self) -> QWidget:
        result = self._result or FlickrFindReplaceResult()
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        status = "Canceled." if result.cancelled else "Finished."
        lines = [
            status,
            f"Retrieved photos: {result.retrieved}",
            f"Photos in exact requested range: {result.in_scope}",
            f"Processed: {result.processed}",
            f"Eligible: {result.eligible}",
            f"Changed photos: {result.photos_changed}",
            f"Titles changed: {result.title_changed}",
            f"Tags removed: {result.tags_removed}",
            f"Tags added: {result.tags_added}",
            f"Unchanged: {result.unchanged}",
            f"Failed photos: {len(result.failed_photo_ids)}",
        ]
        if result.error_message:
            lines.append(f"Error: {result.error_message}")
        summary = QTextEdit(widget)
        summary.setObjectName("flickrFindReplaceSummaryText")
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
        if result.errors:
            details = QTextEdit(widget)
            details.setReadOnly(True)
            details.setPlainText("\n".join(result.errors))
            details.setMaximumHeight(170)
            layout.addWidget(details)
        return widget


def launch_flickr_find_replace(window: MainWindow) -> None:
    api_key = str(get_user_setting(UserSettingKey.FLICKR_API_KEY) or "").strip()
    api_secret = str(get_user_setting(UserSettingKey.FLICKR_API_SECRET) or "").strip()
    if not api_key or not api_secret:
        should_open = prompt_open_settings_for_missing_setting(
            window,
            title="Flickr Find & Replace",
            text=(
                "Flickr API key and Flickr API secret are empty.\n"
                "Set them in Settings > External/Tools > Flickr."
            ),
        )
        if should_open:
            window.open_settings_for_key(UserSettingKey.FLICKR_API_KEY)
        return

    dialog = FlickrFindReplaceDialog(
        window=window,
        api_key=api_key,
        api_secret=api_secret,
        parent=window,
    )
    dialog.exec()
