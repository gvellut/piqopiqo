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

logger = logging.getLogger(__name__)


def sync_dialog_size_to_content(
    dialog: QDialog,
    *,
    sizing: str = "content",
    preserve_width: bool = False,
) -> None:
    """Resize a dialog from its current visible content."""
    if sizing == "free":
        return

    dialog.setMinimumHeight(0)
    dialog.setMaximumHeight(16777215)
    layout = dialog.layout()
    if layout is not None:
        layout.activate()

    if sizing == "fixed":
        dialog.adjustSize()
        dialog.setFixedSize(dialog.sizeHint())
        return

    if preserve_width:
        current_width = max(dialog.width(), dialog.minimumWidth())
        target_height = dialog.sizeHint().height()
        if layout is not None and layout.hasHeightForWidth():
            height_for_width = layout.totalHeightForWidth(current_width)
            if height_for_width > 0:
                target_height = height_for_width
        if target_height > 0:
            dialog.resize(current_width, target_height)
            dialog.setFixedHeight(target_height)
        return

    dialog.adjustSize()
    target_height = dialog.sizeHint().height()
    if target_height > 0:
        dialog.setFixedHeight(target_height)


@dataclass(frozen=True)
class ToolButton:
    """A button declared by a workflow screen."""

    event: str
    text: str
    enabled: bool = True
    visible: bool = True
    default: bool = False


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


class ToolFlowDialog(QDialog):
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
        self._content_widget: QWidget | None = None
        self._buttons: dict[str, QPushButton] = {}
        self._tasks: dict[str, ToolTaskHandle] = {}

        self.setModal(True)
        self._setup_base_ui()
        self.transition_to(workflow.initial_screen)

    def _setup_base_ui(self) -> None:
        self._root_layout = QVBoxLayout(self)

        self._content_layout = QVBoxLayout()
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.addLayout(self._content_layout)

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
        if not self.progress_row.isVisible():
            self.progress_row.show()
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
        self.progress_bar.show()
        if not self.progress_row.isVisible():
            self.progress_row.show()
        self.sync_size_to_content()

    def button(self, event: str) -> QPushButton | None:
        return self._buttons.get(event)

    def sync_size_to_content(self) -> None:
        screen = self._current_screen
        sync_dialog_size_to_content(
            self,
            sizing=screen.sizing if screen is not None else "content",
            preserve_width=screen.preserve_width if screen is not None else False,
        )

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
        widget = screen.build(self) if screen.build is not None else QWidget(self)
        if widget is None:
            widget = QWidget(self)
        self._content_widget = widget
        self._content_layout.addWidget(widget)

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
            self._button_row.addWidget(btn)
            self._buttons[spec.event] = btn
