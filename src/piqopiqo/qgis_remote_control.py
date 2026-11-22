"""Select a photo feature and move to its GPS position using the QGIS local socket."""

from __future__ import annotations

from enum import Enum
import json
import logging
import os
from pathlib import Path
import traceback

from attrs import define
from PySide6.QtCore import QDeadlineTimer, QObject, Signal
from PySide6.QtNetwork import QLocalSocket

from piqopiqo.model import QgisLayerMapping, QgisRemoteControlSettings
from piqopiqo.qt_workers import PythonOwnedRunnable

logger = logging.getLogger(__name__)


class QgisMapStatus(Enum):
    CONNECTION = "Cannot connect to QGIS Remote Control"
    OPERATION = "Error in QGIS Remote Control"
    ZOOMED_TO_POSITION = "Image not found. Zoomed to position"
    LAYER_NOT_FOUND = "Layer not found. Zoomed to position."


@define(frozen=True)
class QgisMapResult:
    status: QgisMapStatus
    error_code: str | None = None
    remote_message: str | None = None


class QgisRemoteControlError(Exception):
    status = QgisMapStatus.OPERATION

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        remote_message: str | None = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.remote_message = remote_message


class QgisConnectionError(QgisRemoteControlError):
    status = QgisMapStatus.CONNECTION


def resolve_photo_layer(
    photo: Path, workspace: Path, mappings: tuple[QgisLayerMapping, ...]
) -> tuple[str, str | int]:
    """Return the workspace-relative photo folder and its QGIS layer."""
    try:
        parent = Path(os.path.abspath(photo.parent))
        folder = parent.relative_to(Path(os.path.abspath(workspace))).as_posix()
    except ValueError as error:
        raise QgisRemoteControlError(
            "The photo is outside the opened folder."
        ) from error
    layer = next(
        (mapping.layer for mapping in mappings if mapping.folder == folder), folder
    )
    return folder, layer


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
        remote_message = reply.get("error")
        if not isinstance(remote_message, str):
            remote_message = None
        error_code = reply.get("errorCode")
        if not isinstance(error_code, str):
            error_code = None
        detail = remote_message or "QGIS rejected the request."
        raise QgisRemoteControlError(
            f"{method} failed. {detail}",
            error_code=error_code,
            remote_message=remote_message,
        )
    return reply


def select_photo(
    socket_name: str,
    layer: str | int,
    filename: str,
    timeout_ms: int,
    *,
    coordinates: tuple[float, float],
    zoom: int,
) -> QgisMapResult | None:
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

        result = None
        try:
            reply = _send_request(
                socket,
                deadline,
                1,
                "select",
                {"layer": layer, "expression": photo_expression(filename)},
            )
        except QgisRemoteControlError as error:
            if error.error_code != "LAYER_NOT_FOUND":
                raise
            _log_map_error(layer, str(error), error.error_code, level=logging.WARNING)
            result = QgisMapResult(
                QgisMapStatus.LAYER_NOT_FOUND, error.error_code, error.remote_message
            )
        else:
            selected_count = reply.get("selectedCount")
            if type(selected_count) is not int or selected_count < 0:
                selected_count = None
            if selected_count is not None:
                logger.debug(
                    "QGIS select on layer %r returned selectedCount=%d",
                    layer,
                    selected_count,
                )
            if selected_count == 0:
                result = QgisMapResult(QgisMapStatus.ZOOMED_TO_POSITION)

        lat, lon = coordinates
        params = {"lat": lat, "lon": lon, "z": zoom, "marker": True}
        logger.debug("QGIS move for layer %r with params %s", layer, params)
        _send_request(socket, deadline, 2, "move", params)
        _send_request(socket, deadline, 3, "raiseWindow", {})
        if result is not None:
            logger.warning("QGIS Map on layer %r: %s", layer, result.status.value)
        return result
    finally:
        socket.abort()


class _QgisPhotoWorkerSignals(QObject):
    finished = Signal(object)  # QgisMapResult or None


def _log_map_error(
    layer: str | int | None,
    detail: str,
    error_code: str | None = None,
    *,
    level: int = logging.ERROR,
) -> None:
    context = "QGIS Remote Control failed"
    if layer is not None:
        context += f" on layer {layer!r}"
    if error_code is not None:
        context += f" (errorCode={error_code!r})"
    lines = [line for line in detail.splitlines() if line.strip()]
    for line in lines or ["No error details provided."]:
        logger.log(level, "%s: %s", context, line)


class QgisPhotoWorker(PythonOwnedRunnable):
    def __init__(
        self,
        photo_path: str,
        workspace: str,
        settings: QgisRemoteControlSettings,
        timeout_ms: int,
        *,
        coordinates: tuple[float, float],
        zoom: int,
    ):
        super().__init__()
        self._photo = Path(photo_path)
        self._workspace = Path(workspace)
        self._settings = settings
        self._timeout_ms = timeout_ms
        self._coordinates = coordinates
        self._zoom = zoom
        self.signals = _QgisPhotoWorkerSignals()

    def run(self) -> None:
        filename = self._photo.name
        layer = None
        try:
            folder, layer = resolve_photo_layer(
                self._photo, self._workspace, self._settings.mappings
            )
            logger.debug(
                "QGIS Map requested for %r from folder %r on layer %r",
                filename,
                folder,
                layer,
            )
            result = select_photo(
                self._settings.socket_name,
                layer,
                filename,
                self._timeout_ms,
                coordinates=self._coordinates,
                zoom=self._zoom,
            )
        except QgisRemoteControlError as error:
            _log_map_error(layer, str(error), error.error_code)
            result = QgisMapResult(error.status, error.error_code, error.remote_message)
        except Exception as error:
            _log_map_error(layer, "".join(traceback.format_exception(error)))
            result = QgisMapResult(QgisMapStatus.OPERATION)
        self.signals.finished.emit(result)
