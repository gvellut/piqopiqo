"""Reusable modal Flickr token-validation and browser-login flow."""

from __future__ import annotations

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget

from piqopiqo.tools.flickr_tools.upload.workers import (
    FlickrLoginWorker,
    FlickrTokenValidationWorker,
)
from piqopiqo.tools.flickr_utils import token_file_exists
from piqopiqo.tools.tool_flow import (
    ToolButton,
    ToolFlowDialog,
    ToolScreen,
    ToolTaskHandle,
    ToolWorkflow,
)


class _FlickrAuthProgressDialog(ToolFlowDialog):
    def __init__(self, *, title: str, status: str, parent=None) -> None:
        self.payload: object | None = None
        self.error_message = ""
        self.was_cancelled = False
        workflow = ToolWorkflow(
            initial_screen="progress",
            screens={
                "progress": ToolScreen(
                    id="progress",
                    title=title,
                    build=lambda dialog: QWidget(dialog),
                    buttons=(ToolButton("cancel", "Cancel"),),
                    min_width=470,
                    show_progress=True,
                    show_progress_count=False,
                    close_policy="cancel",
                )
            },
            transitions={
                ("progress", "cancel"): lambda dialog, event: dialog._cancel(),
                ("progress", "finished"): (
                    lambda dialog, event: dialog._finished(*event.args)
                ),
                ("progress", "cancelled"): (lambda dialog, event: dialog._cancelled()),
                ("progress", "error"): (
                    lambda dialog, event: dialog._error(*event.args)
                ),
            },
        )
        super().__init__(workflow, parent=parent)
        self.set_status(status)
        self.set_progress(0, 0)

    def start_worker(self, worker) -> None:
        self.start_task(
            "flickr_auth",
            ToolTaskHandle.from_qrunnable(
                worker=worker,
                pool=QThreadPool.globalInstance(),
                signal_map={
                    worker.signals.finished: "finished",
                    worker.signals.cancelled: "cancelled",
                    worker.signals.error: "error",
                },
            ),
        )

    def _cancel(self) -> None:
        self.stop_task("flickr_auth", cancel=True)
        self.was_cancelled = True
        self.reject()

    def _finished(self, payload: object) -> None:
        self.stop_task("flickr_auth", cancel=False)
        self.payload = payload
        self.accept()

    def _cancelled(self) -> None:
        self.stop_task("flickr_auth", cancel=False)
        self.was_cancelled = True
        self.reject()

    def _error(self, message: str) -> None:
        self.stop_task("flickr_auth", cancel=False)
        self.error_message = str(message)
        self.accept()


def ensure_flickr_authenticated(
    parent,
    *,
    title: str,
    api_key: str,
    api_secret: str,
) -> bool:
    """Validate the cached token or complete browser OAuth before a Flickr tool."""
    if token_file_exists():
        validation_worker = FlickrTokenValidationWorker(
            api_key=api_key,
            api_secret=api_secret,
        )
        validation_dialog = _FlickrAuthProgressDialog(
            title=title,
            status="Checking Flickr login...",
            parent=parent,
        )
        validation_dialog.start_worker(validation_worker)
        if validation_dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if validation_dialog.error_message:
            QMessageBox.warning(parent, title, validation_dialog.error_message)
            return False
        if bool(validation_dialog.payload):
            return True

    login_worker = FlickrLoginWorker(api_key=api_key, api_secret=api_secret)
    login_dialog = _FlickrAuthProgressDialog(
        title=title,
        status="Log in to Flickr in your browser...",
        parent=parent,
    )
    login_dialog.start_worker(login_worker)
    if login_dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    if login_dialog.error_message:
        QMessageBox.warning(parent, title, login_dialog.error_message)
        return False
    return bool(getattr(login_dialog.payload, "success", False))
