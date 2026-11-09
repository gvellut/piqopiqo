"""Select a photo feature and zoom to it using the QGIS local socket."""

from __future__ import annotations

from enum import Enum
import json
import logging
import os
from pathlib import Path
import traceback

from PySide6.QtCore import QDeadlineTimer, QObject, Signal
from PySide6.QtNetwork import QLocalSocket

from piqopiqo.model import QgisLayerMapping, QgisRemoteControlSettings
from piqopiqo.qt_workers import PythonOwnedRunnable

logger = logging.getLogger(__name__)


class QgisRemoteControlError(Exception):
    pass


class QgisConnectionError(QgisRemoteControlError):
    pass


class QgisMapFailure(Enum):
    CONNECTION = "Cannot connect to QGIS Remote Control"
    OPERATION = "Error in QGIS Remote Control"


def resolve_photo_layer(
    photo: Path, workspace: Path, mappings: tuple[QgisLayerMapping, ...]
) -> str | int:
    try:
        parent = Path(os.path.abspath(photo.parent))
        folder = parent.relative_to(Path(os.path.abspath(workspace))).as_posix()
    except ValueError as error:
        raise QgisRemoteControlError(
            "The photo is outside the opened folder."
        ) from error
    return next(
        (mapping.layer for mapping in mappings if mapping.folder == folder), folder
    )


def photo_expression(filename: str) -> str:
    # Match the escaping used by QgsExpression.quotedString().
    escaped = (
        filename
        .replace("\\", "\\\\")
        .replace("'", "''")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f"\"Name\" = '{escaped}'"


def _remaining_time(deadline: QDeadlineTimer, operation: str) -> int:
    if deadline.hasExpired():
        raise QgisRemoteControlError(f"Timed out while {operation}.")
    return deadline.remainingTime()


def _send_request(
    socket: QLocalSocket,
    deadline: QDeadlineTimer,
    request_id: int,
    method: str,
    params: dict,
) -> dict:
    operation = f"running {method} in QGIS"
    _remaining_time(deadline, operation)
    frame = (
        json.dumps(
            {"id": request_id, "method": method, "params": params}, ensure_ascii=False
        ).encode("utf-8")
        + b"\n"
    )
    if socket.write(frame) != len(frame):
        raise QgisRemoteControlError(f"Could not send {method}. {socket.errorString()}")
    while socket.bytesToWrite():
        if not socket.waitForBytesWritten(_remaining_time(deadline, operation)):
            _remaining_time(deadline, operation)
            raise QgisRemoteControlError(
                f"Could not send {method}. {socket.errorString()}"
            )

    while not socket.canReadLine():
        if not socket.waitForReadyRead(_remaining_time(deadline, operation)) and not (
            socket.canReadLine()
        ):
            _remaining_time(deadline, operation)
            raise QgisRemoteControlError(
                f"No QGIS reply to {method}. {socket.errorString()}"
            )

    try:
        reply = json.loads(bytes(socket.readLine()).decode("utf-8"))
    except (ValueError, RecursionError) as error:
        raise QgisRemoteControlError(
            f"QGIS sent an invalid JSON reply to {method}."
        ) from error
    if (
        not isinstance(reply, dict)
        or type(reply.get("id")) is not int
        or reply["id"] != request_id
    ):
        raise QgisRemoteControlError(f"QGIS sent an unexpected reply to {method}.")
    if reply.get("ok") is not True:
        detail = reply.get("error") or "QGIS rejected the request."
        raise QgisRemoteControlError(f"{method} failed. {detail}")
    return reply


def select_photo(
    socket_name: str, layer: str | int, filename: str, timeout_ms: int
) -> None:
    deadline = QDeadlineTimer(max(1, timeout_ms))
    socket = QLocalSocket()
    try:
        socket.connectToServer(socket_name)
        if socket.state() != QLocalSocket.LocalSocketState.ConnectedState and not (
            socket.waitForConnected(deadline.remainingTime())
        ):
            raise QgisConnectionError(
                f"Could not connect to the QGIS socket {socket_name!r}. "
                f"{socket.errorString()}"
            )

        reply = _send_request(
            socket,
            deadline,
            1,
            "select",
            {"layer": layer, "expression": photo_expression(filename)},
        )
        selected_count = reply.get("selectedCount")
        if type(selected_count) is int and selected_count >= 0:
            logger.debug(
                "QGIS select for %r on layer %r returned selectedCount=%d",
                filename,
                layer,
                selected_count,
            )
        _send_request(socket, deadline, 2, "zoomToSelection", {"layer": layer})
    finally:
        socket.abort()


class _QgisPhotoWorkerSignals(QObject):
    finished = Signal(object)  # QgisMapFailure or None


def _log_map_error(filename: str, detail: str) -> None:
    lines = [line for line in detail.splitlines() if line.strip()]
    for line in lines or ["No error details provided."]:
        logger.error("QGIS Remote Control failed for %r: %s", filename, line)


class QgisPhotoWorker(PythonOwnedRunnable):
    def __init__(
        self,
        photo_path: str,
        workspace: str,
        settings: QgisRemoteControlSettings,
        timeout_ms: int,
    ):
        super().__init__()
        self._photo = Path(photo_path)
        self._workspace = Path(workspace)
        self._settings = settings
        self._timeout_ms = timeout_ms
        self.signals = _QgisPhotoWorkerSignals()

    def run(self) -> None:
        failure = None
        filename = self._photo.name
        try:
            layer = resolve_photo_layer(
                self._photo, self._workspace, self._settings.mappings
            )
            logger.debug("QGIS Map requested for %r on layer %r", filename, layer)
            select_photo(self._settings.socket_name, layer, filename, self._timeout_ms)
        except QgisRemoteControlError as error:
            _log_map_error(filename, str(error))
            failure = (
                QgisMapFailure.CONNECTION
                if isinstance(error, QgisConnectionError)
                else QgisMapFailure.OPERATION
            )
        except Exception as error:
            _log_map_error(filename, "".join(traceback.format_exception(error)))
            failure = QgisMapFailure.OPERATION
        self.signals.finished.emit(failure)
