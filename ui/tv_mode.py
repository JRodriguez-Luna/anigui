"""TV mode (2.1): an episode plays on your AirPlay TV; this Mac is the remote.

How it fits: the playback Session normally drives mpv through its control socket. Here it drives
an AirPlayIpc instead, which looks like that socket but talks to an AVPlayer (core.airplay) that
plays the relay's stream (core.tvrelay) on the TV. So progress, auto-next, Skip intro, the
episode list, the sleep timer and your media keys all keep working, with the TV as the player.

The handoff: clicking the AirPlay button gets the episode ready on an AVPlayer, paused and
silent, and opens macOS's own picker. The moment the TV takes it over, the built-in player
steps aside and the session moves to the TV, from the same second.
"""

from __future__ import annotations

import sys
import threading
import time

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QPushButton, QWidget

from core.airplay import AirPlayer
from core.tvrelay import Relay, airplay_receivers, tv_name

from . import theme

HANDOFF_TIMEOUT_S = 40      # picker opened, no TV chosen: give up quietly
POLL_MS = 400


class AirPlayIpc(QObject):
    """What a Session expects of mpv's control socket, backed by the TV."""

    connected = Signal()
    disconnected = Signal()
    gaveUp = Signal()
    propertyChanged = Signal(str, object)
    event = Signal(str, dict)
    externalChanged = Signal(bool)

    def __init__(self, relay: Relay, player: AirPlayer, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.relay, self.player = relay, player
        self.is_connected = False
        self.info = None
        self._start_at: float | None = None
        self._last: dict = {}
        self._ended_for: str | None = None
        self._timer = QTimer(self, interval=POLL_MS)
        self._timer.timeout.connect(self.poll)

    # -- the socket's face ----------------------------------------------------------------------

    def start(self, timeout_ms: int = 0) -> None:
        self.is_connected = True
        self._timer.start()
        self.connected.emit()

    def stop(self) -> None:
        was = self.is_connected
        self.is_connected = False
        self._timer.stop()
        for step in (self.player.close, self.player.detach_picker, self.relay.stop):
            try:
                step()
            except Exception:  # noqa: BLE001 (stopping must always finish)
                pass
        if was:
            self.disconnected.emit()

    def observe(self, name: str) -> None:
        pass

    def set_stream(self, info) -> None:
        """The Session says which stream the next loadfile means (the relay needs all of it)."""
        self.info = info

    def command(self, *args) -> int | None:
        if not args:
            return None
        name, rest = args[0], args[1:]
        p = self.player
        if name == "loadfile":
            if self.info is None:
                return None
            url = self.relay.start(self.info)
            p.replace(url, self._start_at)
            self._start_at = None
            self._ended_for = None
            p.play()
            QTimer.singleShot(0, lambda: self.event.emit("file-loaded", {}))
        elif name == "set_property" and len(rest) == 2:
            prop, value = rest
            if prop == "pause":
                p.pause() if value else p.play()
                self._emit("pause", bool(value))
            elif prop == "options/start":
                self._start_at = float(value) if value not in (None, "none", "") else None
            elif prop == "volume":
                p.set_volume(float(value) / 100)
            elif prop == "mute":
                p.set_volume(0.0 if value else float(self._last.get("volume", 100)) / 100)
                self._emit("mute", bool(value))
        elif name == "cycle" and rest and rest[0] == "pause":
            paused = self._last.get("pause", False)
            p.play() if paused else p.pause()
            self._emit("pause", not paused)
        elif name == "seek" and rest:
            amount = float(rest[0])
            how = rest[1] if len(rest) > 1 else "relative"
            st = p.status()
            now = st["time"] or 0.0
            if how == "absolute":
                target = amount
            elif how == "absolute-percent":
                target = (st["duration"] or 0.0) * amount / 100
            else:
                target = now + amount
            p.seek(max(0.0, target))
            self._emit("time-pos", max(0.0, target))
        elif name == "quit":
            self.stop()
        # audio-add / sub-add / screenshot-to-file / glsl-shaders: the TV does its own
        return None

    # -- what the TV is doing ---------------------------------------------------------------------

    def _emit(self, prop: str, value) -> None:
        if self._last.get(prop) != value:
            self._last[prop] = value
            self.propertyChanged.emit(prop, value)

    def poll(self) -> None:
        st = self.player.status()
        if st["state"] == "none":
            return
        if st["duration"]:
            self._emit("duration", float(st["duration"]))
        if st["time"] is not None:
            self._emit("time-pos", float(st["time"]))
        self._emit("pause", st["state"] == "paused")
        ext = bool(st["external"])
        if self._last.get("external") != ext:
            self._last["external"] = ext
            self.externalChanged.emit(ext)
        if st["error"] and self._ended_for != self.player.url:
            self._ended_for = self.player.url
            self.event.emit("end-file", {"reason": "error", "error": st["error"]})
            return
        dur, pos = st["duration"], st["time"]
        if dur and pos is not None and pos >= dur - 0.75 and st["state"] == "paused" \
                and self._ended_for != self.player.url:
            self._ended_for = self.player.url
            self.event.emit("end-file", {"reason": "eof"})


class TvHandoff(QObject):
    """Gets the episode ready on an AVPlayer and opens macOS's picker; says when a TV took it."""

    taken = Signal(object)        # the AirPlayIpc, now on the TV
    gaveUp = Signal(str)          # why (empty: you didn't pick one)

    def __init__(self, ctx, info, start: float | None, picker_host: QWidget, parent=None,
                 player: AirPlayer | None = None, relay: Relay | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.relay = relay if relay is not None else Relay()
        self.player = player if player is not None else AirPlayer()
        self.ipc = AirPlayIpc(self.relay, self.player, self)
        self.ipc.set_stream(info)
        self.start_at = start
        self.picker_host = picker_host
        self.started = time.monotonic()
        self.done = False
        self._poll = QTimer(self, interval=POLL_MS)
        self._poll.timeout.connect(self._check)

    def begin(self) -> bool:
        if not self.player.ok:
            self.gaveUp.emit("AirPlay isn't available on this Mac.")
            return False
        try:
            url = self.relay.start(self.ipc.info)
        except (OSError, ValueError) as exc:
            self.gaveUp.emit(str(exc))
            return False
        self.player.load(url, self.start_at, play=False)
        self.player.set_volume(0.0)
        nsview = int(self.picker_host.winId()) if sys.platform == "darwin" else 0
        self.player.attach_picker(nsview, 0, 0, 1, 1)
        how = self.player.press_picker()
        print(f"tv: picker opened ({how})", flush=True)
        self._poll.start()
        return True

    def _check(self) -> None:
        if self.done:
            return
        if self.player.external:
            self.done = True
            self._poll.stop()
            self.player.set_volume(1.0)
            self.player.seek(self.start_at or 0.0)
            self.player.play()
            self.taken.emit(self.ipc)
            return
        if time.monotonic() - self.started > HANDOFF_TIMEOUT_S:
            self.cancel("")

    def cancel(self, why: str = "") -> None:
        if self.done:
            return
        self.done = True
        self._poll.stop()
        self.ipc.stop()
        self.gaveUp.emit(why)


class RemoteView(QWidget):
    """In the player, where the video would be: what's on the TV, and the way back."""

    bringBack = Signal()

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.tv = "your TV"
        self.title = ""
        self.subtitle = ""
        self.up_next = ""
        self.receivers: list[str] | None = None
        self.back = QPushButton("Bring back to this Mac", self, cursor=Qt.CursorShape.PointingHandCursor)
        self.back.setObjectName("Glass")
        self.back.clicked.connect(self.bringBack)
        threading.Thread(target=self._scan, daemon=True).start()
        self._settle = QTimer(self, interval=500)
        self._settle.timeout.connect(self._named)
        self._settle.start()

    def _scan(self) -> None:
        self.receivers = airplay_receivers(3.0)

    def _named(self) -> None:
        if self.receivers is None:
            return
        self._settle.stop()
        name = tv_name(self.receivers)
        if name:
            self.tv = name
            self.update()

    def set_episode(self, title: str, episode: str, dub: bool) -> None:
        self.title = f"Episode {episode}"
        self.subtitle = f"{title} · {'Dub' if dub else 'Sub'}"
        self.update()

    def set_up_next(self, label: str) -> None:
        self.up_next = label
        self.update()

    def resizeEvent(self, _e) -> None:
        self.back.adjustSize()
        self.back.move(self.width() - self.back.width() - 24, 66 if self.height() >= 220 else 14)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.fillRect(r, QColor("#0A0A0F"))
        glow = QPainterPath()
        glow.addEllipse(QRectF(r.width() * 0.1, -r.height() * 0.6, r.width() * 0.8, r.height() * 1.2))
        tint = QColor(theme.ACCENT)
        tint.setAlpha(26)
        p.fillPath(glow, tint)
        small = r.height() < 220
        x = 32.0 if not small else 16.0
        y = 72.0 if not small else 14.0           # below the controls' title line
        dot = QColor(theme.GOOD)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dot)
        p.drawEllipse(QRectF(x, y + 4, 9, 9))
        p.setPen(dot)
        p.setFont(theme.font(13, QFont.Weight.DemiBold))
        p.drawText(QRectF(x + 16, y - 2, r.width() - x - 200, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"Playing on {self.tv}" + (" 🎄" if theme.HOLIDAY else ""))
        if small:
            return
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(30, QFont.Weight.ExtraBold))
        p.drawText(QRectF(x, y + 34, r.width() - 2 * x, 44), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.title)
        p.setPen(QColor(theme.MUTED))
        p.setFont(theme.font(14))
        p.drawText(QRectF(x, y + 78, r.width() - 2 * x, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.subtitle)
        hint = "Pause, skip or pick the next episode here; your keyboard's ⏯ ⏭ keys work too."
        p.setFont(theme.font(12))
        p.setPen(QColor(theme.FAINT))
        p.drawText(QRectF(x, r.height() - 118, r.width() - 2 * x, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   hint)
        if self.up_next:
            p.setPen(QColor(theme.MUTED))
            p.setFont(theme.font(12, QFont.Weight.DemiBold))
            p.drawText(QRectF(x, y + 112, r.width() - 2 * x, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"Up next: {self.up_next} · plays on the TV automatically")
