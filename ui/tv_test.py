"""TV mode preview (2.1, test build): one window that sends the playing episode to an AirPlay TV
and reports what happens, so TV mode can be checked on a real TV before the full feature is
built. Pauses the built-in player while it runs; stops the relay and the AirPlay player when
closed."""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.airplay import AirPlayer
from core.tvrelay import Relay, airplay_receivers, lan_addresses

PICKER = (48, 36)


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return "–:––"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


class TvTestWindow(QDialog):
    def __init__(self, ctx, info, title: str, episode: str, start: float | None = None, parent=None,
                 player: AirPlayer | None = None, relay: Relay | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("WelcomeDialog")
        self.setWindowTitle("Send to TV (preview)")
        self.setFixedSize(560, 460)
        self.info, self.title_, self.episode, self.start_at = info, title, episode, start
        self.relay = relay if relay is not None else Relay()
        self.player = player if player is not None else AirPlayer()
        self.lines: list[str] = []
        self.started = time.time()
        self._external_since: float | None = None

        head = QLabel("Send to TV (preview)", objectName="WelcomeTitle")
        self.what = QLabel(f"{title} · Episode {episode}", objectName="Muted", wordWrap=True)
        self.step = QLabel("", objectName="SettingTitle", wordWrap=True)
        self.status = QLabel("", objectName="Muted", wordWrap=True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.picker_host = QWidget()
        self.picker_host.setFixedSize(PICKER[0] + 160, PICKER[1] + 8)
        self.pick_btn = QPushButton("Pick your TV…", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        self.pick_btn.clicked.connect(self._press_picker)
        self.picker_label = QLabel("← or click the AirPlay icon", objectName="Muted")
        picker_row = QHBoxLayout()
        picker_row.setContentsMargins(0, 0, 0, 0)
        picker_row.addWidget(self.pick_btn)
        picker_row.addWidget(self.picker_host)
        picker_row.addWidget(self.picker_label, 1)
        self.seen = QLabel("Looking for AirPlay TVs on your Wi-Fi…", objectName="Muted", wordWrap=True)
        self.receivers: list[str] | None = None
        self.details = QLabel("", objectName="Muted", wordWrap=True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box = QFrame(objectName="WelcomeRow")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.addWidget(self.details)
        self.copy = QPushButton("Copy report", cursor=Qt.CursorShape.PointingHandCursor)
        self.copy.clicked.connect(self._copy)
        self.pause = QPushButton("Pause", cursor=Qt.CursorShape.PointingHandCursor)
        self.pause.clicked.connect(self._toggle)
        self.done = QPushButton("Stop and close", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        self.done.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addWidget(self.copy)
        buttons.addWidget(self.pause)
        buttons.addStretch(1)
        buttons.addWidget(self.done)
        col = QVBoxLayout(self)
        col.setContentsMargins(28, 24, 28, 20)
        col.setSpacing(10)
        col.addWidget(head)
        col.addWidget(self.what)
        col.addSpacing(6)
        col.addWidget(self.step)
        col.addLayout(picker_row)
        col.addWidget(self.seen)
        col.addWidget(self.status)
        col.addWidget(box, 1)
        col.addLayout(buttons)

        self.timer = QTimer(self, interval=1000)
        self.timer.timeout.connect(self.refresh)
        QTimer.singleShot(0, self._begin)

    # -- running ---------------------------------------------------------------------------------

    def _note(self, text: str) -> None:
        self.lines.append(f"{time.strftime('%H:%M:%S')}  {text}")
        print(f"tv test: {text}", flush=True)

    def _begin(self) -> None:
        if not self.player.ok:
            self.step.setText("AirPlay isn't available here.")
            self.status.setText("This needs macOS (AVFoundation). Nothing was started.")
            self._note("AVFoundation not reachable")
            return
        try:
            url = self.relay.start(self.info, self.title_)
        except (OSError, ValueError) as exc:
            self.step.setText("Couldn't start the relay.")
            self.status.setText(str(exc))
            self._note(f"relay failed: {exc}")
            return
        self._note(f"relay at {url}")
        self._note(f"addresses on this Mac: {', '.join(lan_addresses()) or 'none'}")
        self._note(f"stream: {self.info.url[:80]}… subs={'yes' if self.info.subtitle_url else 'no'} "
                   f"audio={'separate' if self.info.audio_url else 'in video'}")
        loaded = self.player.load(url, self.start_at, play=True)
        self._note(f"AVPlayer loaded: {loaded}")
        self.player.attach_picker(int(self.picker_host.winId()), 4, 4, *PICKER)
        self.step.setText("1 · If macOS asks about incoming connections or the local network, click Allow.\n"
                          "2 · Click “Pick your TV…” and choose your TV in the menu.")
        threading.Thread(target=self._scan, daemon=True).start()
        self.timer.start()
        self.refresh()

    def _scan(self) -> None:
        self.receivers = airplay_receivers(3.0)
        self._note(f"AirPlay receivers on the network: {self.receivers or 'none'}")

    def _press_picker(self) -> None:
        how = self.player.press_picker()
        self._note(f"pick your TV: {how}")

    def refresh(self) -> None:
        if self.receivers is not None and self.seen.text().startswith("Looking"):
            self.seen.setText("AirPlay on your Wi-Fi: " + ", ".join(self.receivers) if self.receivers
                              else "No AirPlay receivers answered on your Wi-Fi (is the TV on and on the same "
                                   "network?)")
        if not self.relay.running:
            return
        s = self.player.status()
        st = self.relay.stats
        mac = self.relay.host
        tvs = [ip for ip in st.clients if ip != mac and not ip.startswith("127.")]
        if s["external"] and self._external_since is None:
            self._external_since = time.time()
            self._note("external playback: the TV took over")
        if not s["external"] and self._external_since is not None:
            self._external_since = None
            self._note("external playback ended")
        where = "on the TV" if s["external"] else "on this Mac (not sent yet)"
        line = f"Playing {where} · {s['state']} · {_clock(s['time'])} / {_clock(s['duration'])}"
        if s["waiting"]:
            line += f" · waiting: {s['waiting'].split('.')[-1]}"
        if s["error"]:
            line += f"\nPlayer error: {s['error']}"
        self.status.setText(line)
        fetched = f"{st.playlists} playlists, {st.pieces} pieces, {st.bytes / 2**20:.1f} MB"
        who = (f"The TV ({', '.join(tvs)}) is fetching from this Mac ✓" if tvs
               else "Nothing has fetched from the TV's side yet")
        extra = ""
        if st.errors:
            extra = "\nRelay errors:\n" + "\n".join(st.errors[-4:])
        self.details.setText(f"Relay: {self.relay.base}\nServed: {fetched}\n{who}{extra}")
        if s["external"] and tvs and st.pieces >= 3:
            self.step.setText("It's playing on your TV. Check: picture OK? Subtitles showing? Then Stop and close "
                              "and send me the report.")

    def _toggle(self) -> None:
        s = self.player.status()
        if s["state"] == "playing":
            self.player.pause()
            self.pause.setText("Play")
        else:
            self.player.play()
            self.pause.setText("Pause")

    def report(self) -> str:
        s = self.player.status()
        st = self.relay.stats
        lines = [f"AniGUI TV test · {self.title_} · episode {self.episode}",
                 f"relay {self.relay.base if self.relay.host else '-'} · clients {st.clients}",
                 f"served {st.playlists} playlists, {st.pieces} pieces, {st.bytes} bytes",
                 f"player {s}", f"errors {st.errors[-6:]}", f"ran {time.time() - self.started:.0f} s"]
        return "\n".join(lines + self.lines)

    def _copy(self) -> None:
        clip = QGuiApplication.clipboard() if QApplication.instance() else None
        if clip is not None:
            clip.setText(self.report())
            self.copy.setText("Copied ✓")
            QTimer.singleShot(1500, lambda: self.copy.setText("Copy report"))

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.player.close()
        self.player.detach_picker()
        self.relay.stop()
        self._note("stopped")
        print(self.report(), flush=True)
        super().closeEvent(event)
