"""Tests for shared tool workflow primitives."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
import pytest

from piqopiqo.tools.tool_flow import (
    ToolButton,
    ToolEvent,
    ToolFlowDialog,
    ToolScreen,
    ToolTaskHandle,
    ToolWorkflow,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _widget_with_text(text: str) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.addWidget(QLabel(text))
    return widget


def _widget_with_wrapped_text(text: str) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    label = QLabel(text)
    label.setWordWrap(True)
    layout.addWidget(label)
    return widget


def test_dispatches_button_event_and_transitions(qapp):  # noqa: ARG001
    events: list[str] = []

    def on_next(dialog: ToolFlowDialog, _event: ToolEvent) -> None:
        events.append(dialog.current_screen_id)
        dialog.transition_to("done")

    workflow = ToolWorkflow(
        initial_screen="start",
        screens={
            "start": ToolScreen(
                id="start",
                title="Tool",
                build=lambda _dialog: _widget_with_text("Start"),
                buttons=(ToolButton("next", "Next"),),
            ),
            "done": ToolScreen(
                id="done",
                title="Tool",
                build=lambda _dialog: _widget_with_text("Done"),
                buttons=(ToolButton("ok", "OK"),),
            ),
        },
        transitions={("start", "next"): on_next},
    )

    dialog = ToolFlowDialog(workflow)
    dialog.button("next").click()

    assert events == ["start"]
    assert dialog.current_screen_id == "done"
    assert dialog.button("ok") is not None


def test_progress_count_and_indeterminate_state(qapp):  # noqa: ARG001
    workflow = ToolWorkflow(
        initial_screen="progress",
        screens={
            "progress": ToolScreen(
                id="progress",
                build=lambda _dialog: _widget_with_text("Progress"),
                show_progress=True,
            )
        },
    )
    dialog = ToolFlowDialog(workflow)

    dialog.set_progress(2, 5)
    assert dialog.progress_bar.value() == 2
    assert dialog.progress_bar.format() == "2/5"
    assert dialog.progress_count_label.text() == "2/5"

    dialog.set_progress(0, 0)
    assert dialog.progress_bar.minimum() == 0
    assert dialog.progress_bar.maximum() == 0
    assert dialog.progress_count_label.isHidden() is True


def test_content_sizing_can_preserve_current_width(qapp):
    workflow = ToolWorkflow(
        initial_screen="main",
        screens={
            "main": ToolScreen(
                id="main",
                build=lambda _dialog: _widget_with_wrapped_text("Long text " * 50),
                min_width=320,
                preserve_width=True,
            )
        },
    )

    dialog = ToolFlowDialog(workflow)
    dialog.show()
    qapp.processEvents()

    dialog.resize(720, dialog.height())
    qapp.processEvents()
    dialog.sync_size_to_content()

    assert dialog.width() == 720
    assert dialog.minimumHeight() == dialog.maximumHeight() == dialog.height()


class _Signals(QObject):
    progress = Signal(int, int)
    finished = Signal()


class _Worker(QRunnable):
    def __init__(self) -> None:
        super().__init__()
        self.signals = _Signals()
        self.cancelled = False
        self.ran = False

    def request_cancel(self) -> None:
        self.cancelled = True

    def run(self) -> None:
        self.ran = True
        self.signals.progress.emit(1, 2)
        self.signals.finished.emit()


class _InlinePool:
    def __init__(self) -> None:
        self.started: list[QRunnable] = []

    def start(self, worker: QRunnable) -> None:
        self.started.append(worker)
        worker.run()


def test_qrunnable_task_maps_signals_and_disconnects(qapp):  # noqa: ARG001
    received: list[tuple[str, tuple]] = []
    worker = _Worker()
    pool = _InlinePool()
    task = ToolTaskHandle.from_qrunnable(
        worker=worker,
        pool=pool,
        signal_map={
            worker.signals.progress: "progress",
            worker.signals.finished: "finished",
        },
    )

    task.start(lambda _name, event: received.append((event.name, event.args)))
    task.disconnect()
    worker.signals.finished.emit()

    assert worker.ran is True
    assert received == [("progress", (1, 2)), ("finished", ())]


def test_signal_task_start_cancel_and_signal_mapping(qapp):  # noqa: ARG001
    signals = _Signals()
    calls: list[str] = []
    received: list[tuple[str, tuple]] = []

    task = ToolTaskHandle.from_signals(
        start_fn=lambda: calls.append("start"),
        cancel_fn=lambda: calls.append("cancel"),
        signal_map={signals.progress: "progress"},
    )

    task.start(lambda _name, event: received.append((event.name, event.args)))
    signals.progress.emit(3, 4)
    task.cancel()
    task.disconnect()
    signals.progress.emit(4, 4)

    assert calls == ["start", "cancel"]
    assert received == [("progress", (3, 4))]
