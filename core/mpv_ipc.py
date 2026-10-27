"""mpv's JSON IPC over a Unix socket, driven by the Qt event loop (no threads).

mpv (and IINA, which embeds mpv) is started with --input-ipc-server=<path>. We
connect, observe properties such as time-pos and duration, and receive events
such as end-file. See https://mpv.io/manual/stable/#json-ipc
"""

from __future__ import annotations

import itertools
import json
import sys
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalSocket

RETRY_MS = 250


class MpvIpc(QObject):
    connected = Signal()
    disconnected = Signal()
    gaveUp = Signal()                   # never connected before the deadline
    propertyChanged = Signal(str, object)
    event = Signal(str, dict)           # event name, full message

    def __init__(self, path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.sock = QLocalSocket(self)
        self.sock.connected.connect(self._on_connected)
        self.sock.disconnected.connect(self._on_disconnected)
        self.sock.errorOccurred.connect(self._on_error)
        self.sock.readyRead.connect(self._on_ready_read)
        self._buf = b""
        self._ids = itertools.count(1)
        self._observe_ids = itertools.count(1)
        self._deadline = 0.0
        self._was_connected = False
        self._retry = QTimer(self, singleShot=True, interval=RETRY_MS)
        self._retry.timeout.connect(self._try)

    @property
    def is_connected(self) -> bool:
        return self.sock.state() == QLocalSocket.LocalSocketState.ConnectedState

    def start(self, timeout_ms: int = 10_000) -> None:
        """Keep trying to connect until the player creates its socket or we time out."""
        self._deadline = time.monotonic() + timeout_ms / 1000
        self._try()

    def stop(self) -> None:
        self._retry.stop()
        self._deadline = 0.0
        self.sock.abort()

    def command(self, *args) -> int | None:
        if not self.is_connected:
            return None
        rid = next(self._ids)
        payload = json.dumps({"command": list(args), "request_id": rid}) + "\n"
        self.sock.write(payload.encode())
        self.sock.flush()
        return rid

    def observe(self, name: str) -> None:
        self.command("observe_property", next(self._observe_ids), name)

    # -- socket plumbing ----------------------------------------------------------

    def _try(self) -> None:
        if self.is_connected or self.sock.state() == QLocalSocket.LocalSocketState.ConnectingState:
            return
        if time.monotonic() > self._deadline:
            self.gaveUp.emit()
            return
        self.sock.connectToServer(self.path)

    def _on_connected(self) -> None:
        self._retry.stop()
        self._was_connected = True
        self.connected.emit()

    def _on_error(self, _err) -> None:
        if self._was_connected:
            return  # handled by disconnected
        self.sock.abort()
        if self._deadline:
            self._retry.start()

    def _on_disconnected(self) -> None:
        if self._was_connected:
            self._was_connected = False
            self.disconnected.emit()

    def _on_ready_read(self) -> None:
        self._buf += bytes(self.sock.readAll())
        *lines, self._buf = self._buf.split(b"\n")
        for line in lines:
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = msg.get("event")
            if name == "property-change":
                self.propertyChanged.emit(msg.get("name", ""), msg.get("data"))
            elif name:
                self.event.emit(name, msg)
            elif msg.get("error") not in (None, "success"):
                print(f"[mpv ipc] request {msg.get('request_id')}: {msg.get('error')}", file=sys.stderr)
