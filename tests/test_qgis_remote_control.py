import json
from pathlib import Path

from PySide6.QtNetwork import QLocalSocket
import pytest

from piqopiqo import qgis_remote_control as qgis
from piqopiqo.model import QgisLayerMapping


def test_resolve_layer_from_workspace_relative_folder():
    workspace = Path("/photos")
    nested = workspace / "2026/Paris/DSCF1234.JPG"
    root = workspace / "DSCF1234.JPG"
    assert qgis.resolve_photo_layer(nested, workspace, ()) == "2026/Paris"
    assert qgis.resolve_photo_layer(root, workspace, ()) == "."
    assert (
        qgis.resolve_photo_layer(
            nested,
            workspace,
            (QgisLayerMapping("Paris", 1), QgisLayerMapping("2026/Paris", 0)),
        )
        == 0
    )
    assert (
        qgis.resolve_photo_layer(root, workspace, (QgisLayerMapping(".", "0"),)) == "0"
    )
    with pytest.raises(qgis.QgisRemoteControlError, match="outside"):
        qgis.resolve_photo_layer(workspace / "../other/DSCF1234.JPG", workspace, ())


class _Socket:
    LocalSocketState = QLocalSocket.LocalSocketState

    def __init__(self, rejected_method):
        self.rejected_method = rejected_method
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
        return json.dumps(reply).encode() + b"\n"

    def abort(self):
        self.closed = True


@pytest.mark.parametrize("rejected_method", [None, "select", "zoomToSelection"])
def test_select_photo_sends_zoom_only_after_success(monkeypatch, rejected_method):
    socket = _Socket(rejected_method)

    class SocketFactory:
        LocalSocketState = QLocalSocket.LocalSocketState

        def __new__(cls):
            return socket

    monkeypatch.setattr(qgis, "QLocalSocket", SocketFactory)
    filename = "L'été\\Paris\tPhoto\n.JPG"
    if rejected_method:
        with pytest.raises(
            qgis.QgisRemoteControlError,
            match=rf"{rejected_method} failed. Rejected for testing",
        ):
            qgis.select_photo("test-qgis", 0, filename, 5000)
    else:
        qgis.select_photo("test-qgis", 0, filename, 5000)

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
    if rejected_method != "select":
        expected.append({"id": 2, "method": "zoomToSelection", "params": {"layer": 0}})
    assert socket.requests == expected
    assert socket.addresses == ["test-qgis"]
    assert socket.closed
