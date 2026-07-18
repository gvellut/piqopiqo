"""Database-only Find & Replace workflow for selected or visible photos."""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

from attrs import define, field
from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.keyword_utils import (
    format_keywords,
    normalize_keyword_list,
    parse_keywords,
    validate_keywords_balanced,
)
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDBUnavailableError
from piqopiqo.qt_workers import PythonOwnedRunnable
from piqopiqo.tools.edit_tools.service import (
    FindReplaceSpec,
    apply_replacement,
    validate_find_replace_spec,
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
    from piqopiqo.model import ImageItem


@define
class LocalFindReplaceResult:
    total: int = 0
    processed: int = 0
    eligible: int = 0
    title_changed: int = 0
    tags_removed: int = 0
    tags_added: int = 0
    photos_changed: int = 0
    unchanged: int = 0
    cancelled: bool = False
    updates: dict[str, dict] = field(factory=dict)
    errors: list[str] = field(factory=list)
    db_fault: object | None = None
    changed_fields: set[str] = field(factory=set)


class _LocalFindReplaceSignals(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)


class LocalFindReplaceWorker(PythonOwnedRunnable):
    """Apply replacements to existing SQLite metadata without reading image files."""

    def __init__(self, *, db_manager, entries: list[dict], spec: FindReplaceSpec):
        super().__init__()
        self._db_manager = db_manager
        self._entries = list(entries)
        self._spec = spec.normalized()
        self._cancel_requested = threading.Event()
        self.signals = _LocalFindReplaceSignals()

    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def run(self) -> None:
        result = LocalFindReplaceResult(total=len(self._entries))
        for entry in self._entries:
            if self._cancel_requested.is_set():
                result.cancelled = True
                break

            file_path = str(entry["file_path"])
            metadata = dict(entry["metadata"])
            self.signals.progress.emit(
                result.processed,
                result.total,
                os.path.basename(file_path),
            )

            try:
                current_tags = parse_keywords(
                    str(metadata.get(DBFields.KEYWORDS) or "")
                )
                outcome = apply_replacement(
                    metadata.get(DBFields.TITLE),
                    current_tags,
                    self._spec,
                )
                result.processed += 1
                if not outcome.eligible:
                    result.unchanged += 1
                    continue

                result.eligible += 1
                if not outcome.changed:
                    result.unchanged += 1
                    continue

                updated = metadata.copy()
                changes: dict[str, str | None] = {}
                if outcome.title_changed:
                    changes[DBFields.TITLE] = outcome.title or None
                    updated[DBFields.TITLE] = changes[DBFields.TITLE]
                if outcome.removed_tags or outcome.added_tags:
                    normalized_tags = normalize_keyword_list(list(outcome.tags))
                    changes[DBFields.KEYWORDS] = (
                        format_keywords(normalized_tags) or None
                    )
                    updated[DBFields.KEYWORDS] = changes[DBFields.KEYWORDS]

                db = self._db_manager.get_db_for_image(file_path)
                if not db.update_title_and_keywords(file_path, changes):
                    raise RuntimeError("The metadata row is no longer available.")
                result.updates[file_path] = updated
                result.photos_changed += 1
                result.changed_fields.update(changes)
                result.title_changed += int(outcome.title_changed)
                result.tags_removed += outcome.removed_tags
                result.tags_added += outcome.added_tags
            except MetadataDBUnavailableError as ex:
                result.db_fault = ex.fault
                result.errors.append(f"{file_path}: {ex}")
                break
            except Exception as ex:  # pragma: no cover - infrastructure failure
                result.errors.append(f"{file_path}: {ex}")

        self.signals.progress.emit(result.processed, result.total, "")
        self.signals.finished.emit(result)


class LocalFindReplaceDialog(ToolFlowDialog):
    """Input, progress, and result workflow for database-only replacement."""

    def __init__(
        self,
        *,
        window: MainWindow,
        target_items: list[ImageItem],
        selected_count: int,
        visible_count: int,
        loaded_count: int,
        used_visible_fallback: bool,
        parent=None,
    ) -> None:
        self._window = window
        self._target_items = list(target_items)
        self._items_by_path = {item.path: item for item in target_items}
        self._selected_count = int(selected_count)
        self._visible_count = int(visible_count)
        self._loaded_count = int(loaded_count)
        self._used_visible_fallback = bool(used_visible_fallback)
        self._worker: LocalFindReplaceWorker | None = None
        self._result: LocalFindReplaceResult | None = None

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
                    title="Find & Replace",
                    build=lambda dialog: dialog._build_input(),
                    buttons=(
                        ToolButton("cancel", "Cancel"),
                        ToolButton("apply", "Apply Changes", default=True),
                    ),
                    min_width=620,
                ),
                "progress": ToolScreen(
                    id="progress",
                    title="Find & Replace",
                    build=lambda dialog: QWidget(dialog),
                    buttons=(ToolButton("cancel_work", "Cancel"),),
                    min_width=520,
                    show_progress=True,
                    close_policy="cancel",
                ),
                "result": ToolScreen(
                    id="result",
                    title="Find & Replace",
                    build=lambda dialog: dialog._build_result(),
                    buttons=(ToolButton("close", "Close", default=True),),
                    min_width=520,
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

    def _build_input(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)

        scope = QLabel(
            f"Selected: {self._selected_count}    "
            f"Visible: {self._visible_count}    "
            f"Loaded: {self._loaded_count}    "
            f"Will process: {len(self._target_items)}",
            widget,
        )
        layout.addWidget(scope)

        if self._used_visible_fallback:
            warning = QLabel(
                "No photos are selected. Changes will be applied to every "
                "currently visible photo.",
                widget,
            )
            warning.setWordWrap(True)
            warning.setStyleSheet(
                "QLabel { color: #8a4b00; background: #fff3cd; "
                "border: 1px solid #e0b45c; padding: 6px; }"
            )
            layout.addWidget(warning)

        explanation = QLabel(
            "The title condition is a regular expression. When it is set, all "
            "title and tag changes are limited to matching photos. Image files "
            "and EXIF metadata are not read or changed.",
            widget,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        group = QGroupBox("Conditions and changes", widget)
        form = QFormLayout(group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.title_pattern_edit = QLineEdit(group)
        self.title_pattern_edit.setPlaceholderText("Optional regular expression")
        form.addRow("Title condition", self.title_pattern_edit)

        self.replace_title_check = QCheckBox("Replace matching title text", group)
        form.addRow("", self.replace_title_check)

        self.title_replacement_edit = QLineEdit(group)
        self.title_replacement_edit.setEnabled(False)
        self.title_replacement_edit.setPlaceholderText(
            "Replacement text; empty removes the match"
        )
        form.addRow("Replace with", self.title_replacement_edit)

        self.remove_tags_edit = QLineEdit(group)
        self.remove_tags_edit.setPlaceholderText(
            "Comma-separated; quote tags containing commas"
        )
        form.addRow("Tags to remove", self.remove_tags_edit)

        self.add_tags_edit = QLineEdit(group)
        self.add_tags_edit.setPlaceholderText(
            "Comma-separated; quote tags containing commas"
        )
        form.addRow("Tags to add", self.add_tags_edit)

        self.add_only_if_removed_check = QCheckBox(
            "Add only when at least one listed tag was removed",
            group,
        )
        form.addRow("", self.add_only_if_removed_check)
        layout.addWidget(group)

        self.replace_title_check.toggled.connect(self.title_replacement_edit.setEnabled)
        return widget

    def _read_spec(self) -> FindReplaceSpec | None:
        assert self.title_pattern_edit is not None
        assert self.replace_title_check is not None
        assert self.title_replacement_edit is not None
        assert self.remove_tags_edit is not None
        assert self.add_tags_edit is not None
        assert self.add_only_if_removed_check is not None

        for label, edit in (
            ("Tags to remove", self.remove_tags_edit),
            ("Tags to add", self.add_tags_edit),
        ):
            if not validate_keywords_balanced(edit.text()):
                QMessageBox.warning(
                    self,
                    "Find & Replace",
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
            QMessageBox.warning(self, "Find & Replace", error)
            return None
        return spec

    def _start(self) -> None:
        spec = self._read_spec()
        if spec is None:
            return

        entries = []
        for item in self._target_items:
            if not isinstance(item.db_metadata, dict):
                continue
            entries.append({
                "file_path": item.path,
                "metadata": item.db_metadata.copy(),
            })

        self._worker = LocalFindReplaceWorker(
            db_manager=self._window.db_manager,
            entries=entries,
            spec=spec,
        )
        self.transition_to("progress")
        self.set_status("Updating the PiqoPiqo metadata database...")
        self.set_progress(0, len(entries))
        self.start_task(
            "local_find_replace",
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
        cancel_button = self.button("cancel_work")
        if cancel_button is not None:
            cancel_button.setEnabled(False)
        self.set_status("Canceling after the current database operation...")

    def _on_progress(self, completed: int, total: int, name: str) -> None:
        self.set_progress(completed, total)
        if name:
            self.set_status(f"Updating {name}...")

    def _on_finished(self, result: LocalFindReplaceResult) -> None:
        self.stop_task("local_find_replace", cancel=False)
        self._result = result
        for file_path, metadata in result.updates.items():
            item = self._items_by_path.get(file_path)
            if item is not None:
                item.db_metadata = metadata.copy()

        if result.changed_fields:
            self._window.sync_model_after_metadata_update(
                set(result.changed_fields),
                source="local_find_replace",
            )

        if result.db_fault is not None:
            handler = getattr(self._window, "_handle_interrupted_db_action", None)
            if callable(handler):
                handler(action_name="Find & Replace")
        self.transition_to("result")

    def _build_result(self) -> QWidget:
        result = self._result or LocalFindReplaceResult()
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        status = "Canceled" if result.cancelled else "Finished"
        summary = QLabel(
            f"{status}. Processed {result.processed} of {result.total} photos.\n"
            f"Eligible: {result.eligible}    Changed photos: "
            f"{result.photos_changed}    Unchanged: {result.unchanged}\n"
            f"Titles changed: {result.title_changed}    Tags removed: "
            f"{result.tags_removed}    Tags added: {result.tags_added}\n\n"
            "Only the PiqoPiqo SQLite metadata database was changed. Image "
            "files and EXIF metadata were untouched.",
            widget,
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        if result.errors:
            details = QTextEdit(widget)
            details.setReadOnly(True)
            details.setPlainText("\n".join(result.errors))
            details.setMaximumHeight(140)
            layout.addWidget(details)
        return widget


def launch_local_find_replace(window: MainWindow) -> None:
    """Launch selection-first local Find & Replace from the Edit menu."""
    selected_items = list(window.photo_model.get_selected_photos())
    visible_items = list(window.images_data)
    loaded_items = list(window.photo_model.all_photos)
    used_visible_fallback = not selected_items
    target_items = selected_items if selected_items else visible_items

    if not target_items:
        QMessageBox.information(
            window,
            "Find & Replace",
            "No selected or visible photos are available.",
        )
        return

    if not window.db_manager.ensure_items_metadata_ready(target_items):
        QMessageBox.information(
            window,
            "Find & Replace",
            "Metadata is still being read for one or more target photos. "
            "Try again when reading is complete.",
        )
        return

    dialog = LocalFindReplaceDialog(
        window=window,
        target_items=target_items,
        selected_count=len(selected_items),
        visible_count=len(visible_items),
        loaded_count=len(loaded_items),
        used_visible_fallback=used_visible_fallback,
        parent=window,
    )
    dialog.exec()
