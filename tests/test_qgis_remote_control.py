import json
import logging
from pathlib import Path

from PySide6.QtNetwork import QLocalSocket
import pytest

from piqopiqo import qgis_remote_control as qgis
from piqopiqo.model import QgisLayerMapping, QgisRemoteControlSettings


def test_resolve_layer_from_workspace_relative_folder():
    workspace = Path("/photos")
    nested = workspace / "2026/Paris/DSCF1234.JPG"
    root = workspace / "DSCF1234.JPG"
    assert qgis.resolve_photo_layer(nested, workspace, ()) == (
        "2026/Paris",
        "2026/Paris",
    )
    assert qgis.resolve_photo_layer(root, workspace, ()) == (".", ".")
    assert qgis.resolve_photo_layer(
        nested,
        workspace,
        (QgisLayerMapping("Paris", 1), QgisLayerMapping("2026/Paris", 0)),
    ) == ("2026/Paris", 0)
    assert qgis.resolve_photo_layer(root, workspace, (QgisLayerMapping(".", "0"),)) == (
        ".",
        "0",
    )
    with pytest.raises(qgis.QgisRemoteControlError, match="outside"):
        qgis.resolve_photo_layer(workspace / "../other/DSCF1234.JPG", workspace, ())


class _Socket:
    LocalSocketState = QLocalSocket.LocalSocketState

    def __init__(self, rejected_method, selected_count):
        self.rejected_method = rejected_method
        self.selected_count = selected_count
        self.addresses = []
        self.requests = []
        self.closed = False

    def connectToServer(self, address):  # noqa: N802
        self.addresses.append(address)

    def state(self):
        return self.LocalSocketState.ConnectedState

    def write(self, frame):
        assert frame.endswith(b"\n")
        self.requests.append(json.loads(frame))
        return len(frame)

    def bytesToWrite(self):  # noqa: N802
        return 0

    def canReadLine(self):  # noqa: N802
        return True

    def readLine(self):  # noqa: N802
        request = self.requests[-1]
        reply = {"id": request["id"], "ok": request["method"] != self.rejected_method}
        if not reply["ok"]:
            reply["error"] = "Rejected for testing"
        elif request["method"] == "select" and self.selected_count is not None:
            reply["selectedCount"] = self.selected_count
        return json.dumps(reply).encode() + b"\n"

    def abort(self):
        self.closed = True


@pytest.mark.parametrize(
    ("rejected_method", "selected_count"),
    [
        (None, None),
        (None, 12),
        (None, 0),
        ("select", 12),
        ("move", 12),
        ("move", 0),
    ],
)
def test_select_photo_moves_to_coordinates_after_selection(
    monkeypatch, caplog, rejected_method, selected_count
):
    socket = _Socket(rejected_method, selected_count)
    caplog.set_level(logging.DEBUG, logger=qgis.__name__)

    class SocketFactory:
        LocalSocketState = QLocalSocket.LocalSocketState

        def __new__(cls):
            return socket

    monkeypatch.setattr(qgis, "QLocalSocket", SocketFactory)
    filename = "L'été\\Paris\tPhoto\n.JPG"
    coordinates = (0.0, -8.0)
    moves = rejected_method != "select"
    if rejected_method:
        with pytest.raises(qgis.QgisRemoteControlError) as caught:
            qgis.select_photo(
                "test-qgis",
                0,
                filename,
                5000,
                coordinates=coordinates,
                zoom=17,
            )
        assert str(caught.value) == f"{rejected_method} failed. Rejected for testing"
        assert caught.value.status is qgis.QgisMapStatus.OPERATION
    else:
        status = qgis.select_photo(
            "test-qgis", 0, filename, 5000, coordinates=coordinates, zoom=17
        )
        assert status is (
            qgis.QgisMapStatus.ZOOMED_TO_POSITION if selected_count == 0 else None
        )

    expected = [
        {
            "id": 1,
            "method": "select",
            "params": {
                "layer": 0,
                "expression": r""" "Name" = 'L''été\\Paris\tPhoto\n.JPG' """.strip(),
            },
        }
    ]
    move_params = {"lat": 0.0, "lon": -8.0, "z": 17, "marker": True}
    if moves:
        expected.append({"id": 2, "method": "move", "params": move_params})
    assert socket.requests == expected
    assert socket.addresses == ["test-qgis"]
    assert socket.closed
    debug_messages = []
    if rejected_method != "select" and selected_count is not None:
        debug_messages.append(
            f"QGIS select on layer 0 returned selectedCount={selected_count}"
        )
    if moves:
        debug_messages.append(f"QGIS move for layer 0 with params {move_params}")
    assert [
        r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG
    ] == debug_messages
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == (
        ["QGIS Map on layer 0: Image not found. Zoomed to position"]
        if selected_count == 0 and rejected_method is None
        else []
    )


@pytest.mark.parametrize(
    ("error_type", "expected_failure"),
    [
        (None, None),
        (qgis.QgisConnectionError, qgis.QgisMapStatus.CONNECTION),
        (qgis.QgisRemoteControlError, qgis.QgisMapStatus.OPERATION),
        (RuntimeError, qgis.QgisMapStatus.OPERATION),
    ],
)
def test_qgis_map_logs_one_line_per_record(
    monkeypatch, caplog, error_type, expected_failure
):
    filename = "Photo\n123.JPG"
    folder = "2026/Paris\nTrip"
    layer = "Mapped\r\nlayer"

    def select_photo(_socket_name, chosen_layer, chosen_filename, _timeout, **_kwargs):
        assert (chosen_layer, chosen_filename) == (layer, filename)
        if error_type:
            raise error_type("First detail\r\nSecond detail")

    monkeypatch.setattr(qgis, "select_photo", select_photo)
    worker = qgis.QgisPhotoWorker(
        f"/photos/{folder}/{filename}",
        "/photos",
        QgisRemoteControlSettings(mappings=(QgisLayerMapping(folder, layer),)),
        5000,
        coordinates=(48.0, 2.0),
        zoom=17,
    )
    results = []
    worker.signals.finished.connect(results.append)
    with caplog.at_level(logging.DEBUG, logger=qgis.__name__):
        worker.run()

    assert results == [expected_failure]
    records = [record for record in caplog.records if record.name == qgis.__name__]
    debug, *errors = records
    assert debug.levelno == logging.DEBUG
    assert debug.getMessage() == (
        f"QGIS Map requested for {filename!r} from folder {folder!r} on layer {layer!r}"
    )
    assert all(record.exc_info is None for record in records)
    assert all(len(record.getMessage().splitlines()) == 1 for record in records)
    assert all(record.levelno == logging.ERROR for record in errors)
    assert all(
        record.getMessage().startswith(
            f"QGIS Remote Control failed on layer {layer!r}: "
        )
        for record in errors
    )
    if error_type:
        first, second = errors[-2:]
        assert first.getMessage().endswith("First detail")
        assert second.getMessage().endswith("Second detail")
        if error_type is RuntimeError:
            assert "Traceback" in errors[0].getMessage()
        else:
            assert len(errors) == 2
    else:
        assert not errors
