"""Now Playing (2.0): the built-in player in Control Center, and your keyboard's ⏯ ⏭ keys
(and AirPods) control it. Setting: "Media keys and Now Playing" (on). Only for the built-in
player: IINA and mpv do this themselves."""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from core.nowplaying import NowPlaying

REFRESH_MS = 1000
RESEND_S = 15          # macOS moves the time along itself; this keeps it honest


class NowPlayingBridge(QObject):
    command = Signal(str, object)     # from macOS (main thread) -> handled after it returns

    def __init__(self, ctx, playback, host, parent=None, core: NowPlaying | None = None) -> None:
        super().__init__(parent)
        self.ctx, self.playback, self.host = ctx, playback, host
        self.core = core if core is not None else NowPlaying()
        self._last: tuple | None = None
        self.command.connect(self.handle, Qt.ConnectionType.QueuedConnection)
        self.timer = QTimer(self, interval=REFRESH_MS)
        self.timer.timeout.connect(self.refresh)
        if self.core.ok:
            self.timer.start()

    def _session(self):
        s = self.playback.session
        return s if s is not None and s.alive and s.kind == "anigui" else None

    def refresh(self) -> None:
        s = self._session()
        if s is None or not self.ctx.pref("media_keys"):
            if self.core.started:
                self.core.stop()          # the keys go back to Music (or whatever played before)
                self._last = None
            return
        if s.loading:
            return
        if not self.core.started:
            self.core.start(lambda name, value: self.command.emit(name, value))
        n = s.now
        pos = float(n.position or 0.0)
        key = (n.anime_id, n.episode, n.paused, n.duration)
        now = time.monotonic()
        if self._last is not None:
            last_key, last_pos, last_at = self._last
            expected = last_pos + (0.0 if n.paused else now - last_at)
            if last_key == key and abs(pos - expected) < 3 and now - last_at < RESEND_S:
                return                # macOS is already showing the right thing
        show = self.ctx.store.get_show(n.anime_id)
        poster = None
        if show is not None and show.poster:
            path = self.ctx.images.covers.cached_path(show.poster)
            poster = str(path) if path else None
        self.core.show(f"Episode {n.episode}", n.title, pos, n.duration, not n.paused, poster)
        self._last = (key, pos, now)

    def handle(self, name: str, value) -> None:
        s = self._session()
        if s is None:
            return
        h = self.host
        if name == "play":
            h._cmd("set_property", "pause", False)
        elif name == "pause":
            h._cmd("set_property", "pause", True)
        elif name == "toggle":
            h._cmd("cycle", "pause")
        elif name == "next":
            h._action("next")
        elif name == "previous":
            h._cmd("seek", "0", "absolute")
        elif name == "seek" and value is not None:
            h._cmd("seek", f"{float(value):.1f}", "absolute")
        self._last = None             # tell macOS right away
        QTimer.singleShot(300, self.refresh)
