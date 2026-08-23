"""Shared workflow primitives for modal tool dialogs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import logging
from typing import Any

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.dialogs.unsaved_changes_dialog import UnsavedChangesDialog

logger = logging.getLogger(__name__)
_QWIDGETSIZE_MAX = 16777215
_SIZE_CONSTRAINT_PROPERTY = "_tool_flow_size_constraints"


def _clamp_dialog_width(dialog: QDialog, width: int) -> int:
    minimum_width = max(0, dialog.minimumWidth())
    maximum_width = dialog.maximumWidth()
    bounded = max(int(width), minimum_width)
    if 0 < maximum_width < _QWIDGETSIZE_MAX:
        bounded = min(bounded, maximum_width)
    return bounded


def _release_applied_size_constraints(dialog: QDialog) -> None:
    constraints = dialog.property(_SIZE_CONSTRAINT_PROPERTY)
    dialog.setProperty(_SIZE_CONSTRAINT_PROPERTY, None)
    if not isinstance(constraints, dict):
        return
    if constraints.get("width"):
        dialog.setMinimumWidth(int(constraints["min_width"]))
        dialog.setMaximumWidth(int(constraints["max_width"]))
    if constraints.get("height"):
        dialog.setMinimumHeight(int(constraints["min_height"]))
        dialog.setMaximumHeight(int(constraints["max_height"]))


def _invalidate_layout_tree(widget: QWidget) -> None:
    widget.updateGeometry()
    layout = widget.layout()
    if layout is None:
        return
    layout.invalidate()
    for index in range(layout.count()):
        item = layout.itemAt(index)
        child_layout = item.layout()
        if child_layout is not None:
            child_layout.invalidate()
        child_widget = item.widget()
        if child_widget is not None:
            _invalidate_layout_tree(child_widget)


def _activate_layout_tree(widget: QWidget) -> None:
    layout = widget.layout()
    if layout is None:
        return
    for index in range(layout.count()):
        item = layout.itemAt(index)
        child_widget = item.widget()
        if child_widget is not None:
            _activate_layout_tree(child_widget)
        child_layout = item.layout()
        if child_layout is not None:
            child_layout.activate()
    layout.activate()


def _polish_widget_tree(widget: QWidget) -> None:
    widget.ensurePolished()
    for child in widget.findChildren(QWidget):
        child.ensurePolished()


def _layout_has_visible_content(layout) -> bool:
    for index in range(layout.count()):
        item = layout.itemAt(index)
        child_widget = item.widget()
        if child_widget is not None and not child_widget.isHidden():
            return True
        child_layout = item.layout()
        if child_layout is not None and _layout_has_visible_content(child_layout):
            return True
        spacer = item.spacerItem()
        if spacer is not None:
            hint = spacer.sizeHint()
            if hint.width() > 0 or hint.height() > 0:
                return True
    return False


def _widget_has_visible_content(widget: QWidget) -> bool:
    layout = widget.layout()
    if layout is None:
        return True
    return _layout_has_visible_content(layout)


def _normalize_body_widget(widget: QWidget) -> None:
    layout = widget.layout()
    if layout is not None:
        layout.setContentsMargins(0, 0, 0, 0)


def _height_for_width(dialog: QDialog, *, width: int, fallback_height: int) -> int:
    minimum_height = int(dialog.minimumSizeHint().height())
    layout = dialog.layout()
    if layout is not None and layout.hasHeightForWidth():
        height_for_width = layout.totalHeightForWidth(width)
        if height_for_width > 0:
            return max(int(height_for_width), minimum_height)
    if fallback_height > 0:
        return max(int(fallback_height), minimum_height)
    return minimum_height


def _clamp_dialog_height(dialog: QDialog, height: int) -> int:
    minimum_height = max(0, dialog.minimumHeight())
    maximum_height = dialog.maximumHeight()
    bounded = max(int(height), minimum_height)
    if 0 < maximum_height < _QWIDGETSIZE_MAX:
        bounded = min(bounded, maximum_height)
    return bounded


def _apply_dialog_size_to_content(
    dialog: QDialog,
    *,
    sizing: str,
    preserve_width: bool,
) -> None:
    if sizing == "free":
        return

    _release_applied_size_constraints(dialog)
    base_min_width = dialog.minimumWidth()
    base_max_width = dialog.maximumWidth()
    base_min_height = dialog.minimumHeight()
    base_max_height = dialog.maximumHeight()

    _polish_widget_tree(dialog)
    _invalidate_layout_tree(dialog)
    _activate_layout_tree(dialog)

    size_hint = dialog.sizeHint()
    base_width = (
        dialog.width() if preserve_width and dialog.isVisible() else size_hint.width()
    )
    target_width = _clamp_dialog_width(
        dialog,
        max(int(base_width), int(dialog.minimumSizeHint().width())),
    )
    target_height = _height_for_width(
        dialog,
        width=target_width,
        fallback_height=size_hint.height(),
    )
    target_height = _clamp_dialog_height(dialog, target_height)
    constraints: dict[str, int | bool] = {
        "height": True,
        "min_height": base_min_height,
        "max_height": base_max_height,
    }

    if sizing == "fixed":
        constraints.update({
            "width": True,
            "min_width": base_min_width,
            "max_width": base_max_width,
        })
        dialog.resize(target_width, target_height)
        dialog.setMinimumWidth(target_width)
        dialog.setMaximumWidth(target_width)
        dialog.setMinimumHeight(target_height)
        dialog.setMaximumHeight(target_height)
        dialog.setProperty(_SIZE_CONSTRAINT_PROPERTY, constraints)
        return

    dialog.resize(target_width, target_height)
    dialog.setMinimumHeight(target_height)
    dialog.setMaximumHeight(target_height)
    dialog.setProperty(_SIZE_CONSTRAINT_PROPERTY, constraints)


def sync_dialog_size_to_content(
    dialog: QDialog,
    *,
    sizing: str = "content",
    preserve_width: bool = False,
) -> None:
    """Resize a dialog from its current visible content."""
    _apply_dialog_size_to_content(
        dialog,
        sizing=sizing,
        preserve_width=preserve_width,
    )


@dataclass(frozen=True)
class ToolButton:
    """A button declared by a workflow screen."""

    event: str
    text: str
    enabled: bool = True
    visible: bool = True
    default: bool = False
    left_aligned: bool = False


@dataclass(frozen=True)
class ToolScreen:
    """Declarative definition for one dialog screen."""

    id: str
    title: str = ""
    build: Callable[[ToolFlowDialog], QWidget | None] | None = None
    buttons: tuple[ToolButton, ...] = ()
    min_width: int | None = None
    sizing: str = "content"  # content, fixed, free
    preserve_width: bool = False
    show_progress: bool = False
    show_progress_count: bool = True
    close_policy: str = "reject"  # reject, ignore, cancel


@dataclass(frozen=True)
class ToolEvent:
    """Event emitted by the workflow or by an async task."""

    name: str
    args: tuple[Any, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)


TransitionHandler = Callable[["ToolFlowDialog", ToolEvent], None]


@dataclass(frozen=True)
class ToolWorkflow:
    """Workflow screen graph and event handlers."""

    initial_screen: str
    screens: Mapping[str, ToolScreen]
    transitions: Mapping[tuple[str, str], TransitionHandler] = field(
        default_factory=dict
    )


class ToolTaskHandle:
    """Adapter for async work controlled by a tool workflow."""

    def __init__(
        self,
        *,
        start_fn: Callable[[], None],
        cancel_fn: Callable[[], None] | None = None,
        signal_map: Mapping[Any, str | Callable[..., ToolEvent | None]] | None = None,
    ) -> None:
        self._start_fn = start_fn
        self._cancel_fn = cancel_fn
        self._signal_map = dict(signal_map or {})
        self._connections: list[tuple[Any, Callable[..., None]]] = []
        self._emit: Callable[[str, Any], None] | None = None
        self._started = False
        self._cancelled = False

    @classmethod
    def from_qrunnable(
        cls,
        *,
        worker,
        pool: QThreadPool | None = None,
        signal_map: Mapping[Any, str | Callable[..., ToolEvent | None]] | None = None,
        cancel_fn: Callable[[], None] | None = None,
    ) -> ToolTaskHandle:
        thread_pool = pool or QThreadPool.globalInstance()
        cancel = cancel_fn
        if cancel is None and hasattr(worker, "request_cancel"):
            cancel = worker.request_cancel
        return cls(
            start_fn=lambda: thread_pool.start(worker),
            cancel_fn=cancel,
            signal_map=signal_map,
        )

    @classmethod
    def from_signals(
        cls,
        *,
        start_fn: Callable[[], None],
        cancel_fn: Callable[[], None] | None = None,
        signal_map: Mapping[Any, str | Callable[..., ToolEvent | None]] | None = None,
    ) -> ToolTaskHandle:
        return cls(start_fn=start_fn, cancel_fn=cancel_fn, signal_map=signal_map)

    def start(self, emit: Callable[[str, Any], None]) -> None:
        if self._started:
            return
        self._started = True
        self._emit = emit
        self._connect_signals()
        self._start_fn()

    def cancel(self) -> None:
        self._cancelled = True
        if self._cancel_fn is not None:
            self._cancel_fn()

    def disconnect(self) -> None:
        while self._connections:
            signal, slot = self._connections.pop()
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _connect_signals(self) -> None:
        for signal, route in self._signal_map.items():
            slot = self._make_slot(route)
            signal.connect(slot)
            self._connections.append((signal, slot))

    def _make_slot(
        self,
        route: str | Callable[..., ToolEvent | None],
    ) -> Callable[..., None]:
        def slot(*args) -> None:
            if self._emit is None:
                return
            if isinstance(route, str):
                event = ToolEvent(route, tuple(args))
            else:
                event = route(*args)
                if event is None:
                    return
            self._emit(event.name, event)

        return slot


class ToolFlowDialog(UnsavedChangesDialog):
    """Modal dialog runtime for tool workflows."""

    def __init__(
        self,
        workflow: ToolWorkflow,
        *,
        parent=None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self.workflow = workflow
        self.context: dict[str, Any] = context if context is not None else {}
        self.current_screen_id = ""
        self._current_screen: ToolScreen | None = None
        self._content_host: QWidget | None = None
        self._content_widget: QWidget | None = None
        self._buttons: dict[str, QPushButton] = {}
        self._tasks: dict[str, ToolTaskHandle] = {}
        self._unsaved_changes_screen_id: str | None = None

        self.setModal(True)
        self._setup_base_ui()
        self.transition_to(workflow.initial_screen)

    def _setup_base_ui(self) -> None:
        self._root_layout = QVBoxLayout(self)

        self._content_host = QWidget(self)
        self._content_host.hide()
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.addWidget(self._content_host)

        self.progress_row = QWidget(self)
        progress_row_layout = QHBoxLayout(self.progress_row)
        progress_row_layout.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel(self.progress_row)
        self.status_label.setWordWrap(True)
        progress_row_layout.addWidget(self.status_label, 1)
        self.progress_count_label = QLabel(self.progress_row)
        self.progress_count_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        mono = QFont("menlo")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.progress_count_label.setFont(mono)
        progress_row_layout.addWidget(self.progress_count_label)
        self.progress_row.hide()
        self._root_layout.addWidget(self.progress_row)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        self._root_layout.addWidget(self.progress_bar)

        self._button_row = QHBoxLayout()
        self._button_row.addStretch(1)
        self._root_layout.addLayout(self._button_row)

    def transition_to(self, screen_id: str) -> None:
        screen = self.workflow.screens[screen_id]
        self.current_screen_id = screen_id
        self._current_screen = screen
        if screen.title:
            self.setWindowTitle(screen.title)
        if screen.min_width:
            self.setMinimumWidth(screen.min_width)
        self._replace_content(screen)
        self._configure_buttons(screen)
        self.configure_progress(
            visible=screen.show_progress,
            show_count=screen.show_progress_count,
        )
        self.sync_size_to_content()

    def emit_event(self, name: str, *args: Any, **payload: Any) -> None:
        self._dispatch_event(ToolEvent(name, tuple(args), dict(payload)))

    def _set_unsaved_changes_state(self, getter: Callable[[], object]) -> None:
        self._unsaved_changes_screen_id = self.current_screen_id
        super()._set_unsaved_changes_state(getter)

    def _has_unsaved_changes(self) -> bool:
        if self.current_screen_id != self._unsaved_changes_screen_id:
            return False
        return super()._has_unsaved_changes()

    def start_task(self, name: str, task: ToolTaskHandle) -> None:
        self.stop_task(name, cancel=False)
        self._tasks[name] = task
        task.start(lambda _event_name, event: self._dispatch_event(event))

    def stop_task(self, name: str, *, cancel: bool = True) -> None:
        task = self._tasks.pop(name, None)
        if task is None:
            return
        if cancel:
            task.cancel()
        task.disconnect()

    def stop_all_tasks(self, *, cancel: bool = True) -> None:
        for name in list(self._tasks):
            self.stop_task(name, cancel=cancel)

    def configure_progress(self, *, visible: bool, show_count: bool = True) -> None:
        self.progress_row.setVisible(visible)
        self.progress_bar.setVisible(visible)
        self.progress_count_label.setVisible(visible and show_count)
        if not visible:
            self.status_label.clear()
            self.progress_count_label.clear()
            self.progress_bar.reset()
        self.sync_size_to_content()

    def set_status(self, text: str) -> None:
        self.status_label.setText(str(text))
        if self._current_screen is not None and self._current_screen.show_progress:
            self.progress_row.show()
        else:
            self.progress_row.hide()
        self.sync_size_to_content()

    def set_progress(self, completed: int, total: int) -> None:
        total_value = max(0, int(total))
        completed_value = max(0, int(completed))
        if total_value <= 0:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("")
            self.progress_count_label.clear()
            self.progress_count_label.hide()
        else:
            completed_value = min(completed_value, total_value)
            self.progress_bar.setRange(0, total_value)
            self.progress_bar.setValue(completed_value)
            text = f"{completed_value}/{total_value}"
            self.progress_bar.setFormat(text)
            if self._current_screen is None or self._current_screen.show_progress_count:
                self.progress_count_label.setText(text)
                self.progress_count_label.show()
        if self._current_screen is not None and self._current_screen.show_progress:
            self.progress_bar.show()
            self.progress_row.show()
        else:
            self.progress_bar.hide()
            self.progress_row.hide()
        self.sync_size_to_content()

    def button(self, event: str) -> QPushButton | None:
        return self._buttons.get(event)

    def sync_size_to_content(self) -> None:
        screen = self._current_screen
        self._sync_content_host_visibility()
        sync_dialog_size_to_content(
            self,
            sizing=screen.sizing if screen is not None else "content",
            preserve_width=screen.preserve_width if screen is not None else False,
        )

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.sync_size_to_content()

    def _escape_would_close(self) -> bool:
        screen = self._current_screen
        return screen is None or screen.close_policy != "ignore"

    def reject(self) -> None:
        screen = self._current_screen
        policy = screen.close_policy if screen is not None else "reject"
        if policy == "ignore":
            return
        if policy == "cancel":
            self.stop_all_tasks(cancel=True)
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        screen = self._current_screen
        policy = screen.close_policy if screen is not None else "reject"
        if policy == "ignore":
            event.ignore()
            return
        if policy == "cancel":
            self.stop_all_tasks(cancel=True)
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self.stop_all_tasks(cancel=False)
        super().done(result)

    def _dispatch_event(self, event: ToolEvent) -> None:
        handler = self.workflow.transitions.get((self.current_screen_id, event.name))
        if handler is None:
            handler = self.workflow.transitions.get(("*", event.name))
        if handler is None:
            logger.debug(
                "Unhandled tool event %s on screen %s",
                event.name,
                self.current_screen_id,
            )
            return
        handler(self, event)

    def _replace_content(self, screen: ToolScreen) -> None:
        if self._content_widget is not None:
            self._content_layout.removeWidget(self._content_widget)
            self._content_widget.deleteLater()
            self._content_widget = None
        widget = screen.build(self) if screen.build is not None else None
        if widget is None:
            if self._content_host is not None:
                self._content_host.hide()
            return
        _normalize_body_widget(widget)
        self._content_widget = widget
        self._content_layout.addWidget(widget)
        widget.show()
        self._sync_content_host_visibility()

    def _sync_content_host_visibility(self) -> None:
        if self._content_host is None:
            return
        visible = self._content_widget is not None and _widget_has_visible_content(
            self._content_widget
        )
        self._content_host.setVisible(visible)

    def _configure_buttons(self, screen: ToolScreen) -> None:
        while self._button_row.count() > 1:
            item = self._button_row.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._buttons.clear()

        for spec in screen.buttons:
            btn = QPushButton(spec.text, self)
            btn.setEnabled(spec.enabled)
            btn.setVisible(spec.visible)
            btn.setDefault(spec.default)
            btn.clicked.connect(
                lambda _checked=False, event=spec.event: self.emit_event(event)
            )
            if spec.left_aligned:
                self._button_row.insertWidget(0, btn)
            else:
                self._button_row.addWidget(btn)
            self._buttons[spec.event] = btn
