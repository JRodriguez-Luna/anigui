"""Where episodes play (2.0.1): the AniGUI player or IINA, side by side, with how hard each one
makes this Mac work, measured on this Mac.

"Measure on this Mac" plays 20 seconds of the last episode you watched in each player, muted,
and reads how much processor time each used (what Activity Monitor shows). Nothing is sent
anywhere; the numbers are kept in AniGUI's settings.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import signal
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from core import cpu, sharper
from core.player import build_player_command, child_env, embedded_options, embedded_tracks, find_player

from . import theme
from .widgets import Combo

MEASURE_S = 20            # seconds of steady playback per player
START_TIMEOUT_S = 45      # loading the stream and starting to play
SETTLE_S = 2              # after it starts, before counting

FEATURES = {
    "anigui": [(True, "Theater, pop-out, full screen"), (True, "Moments, sleep timer, your queue"),
               (True, "Sharper picture (uses more)"), (True, "Media keys and Now Playing")],
    "iina": [(False, "Its own window and controls"), (False, "No moments, sleep timer or queue"),
             (False, "No Sharper picture"), (True, "Media keys (IINA's own)")],
}
OTHER = [("Don't use", ""), ("Auto (IINA, then mpv)", "auto"), ("mpv", "mpv")]


# -- what was measured ------------------------------------------------------------------------------

@dataclass
class Measured:
    anigui: float | None = None
    sharper: float | None = None
    iina: float | None = None
    when: str = ""                 # ISO date
    what: str = ""                 # "My Hero Academia, episode 7"
    height: int | None = None      # 1080

    @classmethod
    def load(cls, ctx) -> "Measured | None":
        raw = ctx.pref("player_measure")
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return cls(**{k: data.get(k) for k in cls.__dataclass_fields__})
        except (TypeError, ValueError):
            return None

    def save(self, ctx) -> None:
        ctx.set_pref("player_measure", json.dumps(self.__dict__))

    @property
    def ratio(self) -> float | None:
        """IINA's use as a share of the AniGUI player's (0.25 = a quarter)."""
        if self.anigui and self.iina is not None and self.anigui > 0:
            return self.iina / self.anigui
        return None


def share_words(ratio: float | None) -> str | None:
    """0.26 -> "about a quarter" (None when IINA isn't clearly lighter)."""
    if ratio is None or ratio > 0.8:
        return None
    for limit, words in ((0.15, "about a tenth"), (0.29, "about a quarter"), (0.4, "about a third"),
                         (0.6, "about half"), (0.8, "about two-thirds")):
        if ratio <= limit:
            return words
    return None


def last_episode(store):
    """(anime_id, title, episode, position) of the last episode you watched, or None."""
    items = store.continue_watching(1)
    if not items:
        return None
    it = items[0]
    return it.show.anime_id, it.show.title, it.last.episode, it.last.position


# -- the players while measuring ------------------------------------------------------------------

class BuiltInProbe:
    """The AniGUI player in a small window of its own, muted."""

    def __init__(self, info, title: str, start: float, sharp: bool) -> None:
        from .player_view import VideoView
        opts, url = embedded_options(info, title, None, start)
        opts["mute"] = "yes"
        if sharp:
            opts["glsl-shaders"] = sharper.shaders_value(True)
        self.window = QWidget(None, Qt.WindowType.Window)
        self.window.setWindowTitle("AniGUI · measuring (muted)")
        self.window.resize(960, 540)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.window.move(area.right() - 980, area.bottom() - 580)
        self.view = VideoView(opts, url, embedded_tracks(info), self.window)
        self.view.setGeometry(0, 0, 960, 540)
        self.window.show()

    def position(self) -> float | None:
        try:
            return self.view.mpv.get_double("time-pos")
        except Exception:  # noqa: BLE001
            return None

    def height(self) -> int | None:
        try:
            h = self.view.mpv.get("video-params/h")
            return int(h) if h else None
        except Exception:  # noqa: BLE001
            return None

    def cpu(self) -> float | None:
        return cpu.own_cpu_seconds()

    def close(self) -> None:
        try:
            self.view.close_engine()
        finally:
            self.window.close()
            self.window.deleteLater()


def _ipc_get(path: str, prop: str) -> float | None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(path)
            s.sendall(json.dumps({"command": ["get_property", prop], "request_id": 7}).encode() + b"\n")
            buf = b""
            while b"\n" not in buf or b'"request_id":7' not in buf.replace(b" ", b""):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        for line in buf.splitlines():
            msg = json.loads(line)
            if msg.get("request_id") == 7:
                value = msg.get("data")
                return float(value) if isinstance(value, (int, float)) else None
    except (OSError, ValueError):
        return None
    return None


class IinaProbe:
    """IINA playing the same episode, muted. It's only measured if AniGUI opened it."""

    def __init__(self, info, title: str, start: float) -> None:
        found = find_player("iina")
        if not found or found[0] != "iina":
            raise RuntimeError("IINA isn't installed.")
        if cpu.pids_named("IINA"):
            raise RuntimeError("IINA is already open. Quit IINA, then measure again.")
        self.sock = os.path.join(tempfile.gettempdir(), f"anigui-measure-{os.getpid()}.sock")
        cmd = build_player_command("iina", found[1], info, title, self.sock, start)
        cmd.insert(len(cmd) - 1, "--mpv-mute=yes")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True, env=child_env())
        self.pid: int | None = None

    def position(self) -> float | None:
        if self.pid is None:
            new = cpu.pids_named("IINA")
            self.pid = min(new) if new else None
        return _ipc_get(self.sock, "time-pos") if self.pid else None

    def height(self) -> int | None:
        h = _ipc_get(self.sock, "height")
        return int(h) if h else None

    def cpu(self) -> float | None:
        return cpu.cpu_seconds(self.pid) if self.pid else None

    def close(self) -> None:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                s.connect(self.sock)
                s.sendall(b'{"command": ["quit"]}\n')
        except OSError:
            pass
        for pid in filter(None, (self.pid, self.proc.pid)):
            try:
                os.kill(pid, signal.SIGTERM)        # IINA was opened for this only
            except OSError:
                pass


# -- measuring ------------------------------------------------------------------------------------

@dataclass
class _Run:
    kind: str                       # anigui | sharper | iina
    probe: object = None
    started: float = 0.0
    began: float | None = None      # when playback was seen moving
    cpu0: float | None = None
    pos0: float | None = None
    t0: float = 0.0
    first_pos: float | None = None
    extra: dict = field(default_factory=dict)


class Measurer(QObject):
    """Measures each player in turn. step(kind, text) while it works; finished(Measured) or
    failed(message) at the end."""

    step = Signal(str, str)
    finished = Signal(object)
    failed = Signal(str)

    POLL_MS = 500

    def __init__(self, ctx, resolver, busy=lambda: False, parent=None) -> None:
        super().__init__(parent)
        self.ctx, self.resolver, self.busy = ctx, resolver, busy
        self.result = Measured()
        self.runs: list[str] = []
        self.run: _Run | None = None
        self.info = None
        self.target = None
        self.running = False
        self._job = None
        self._timer = QTimer(self, interval=self.POLL_MS)
        self._timer.timeout.connect(self._tick)
        self.notes: list[str] = []

    # tests replace this
    def make_probe(self, kind: str):
        title = self.target[1]
        start = self.start_at
        if kind == "iina":
            return IinaProbe(self.info, title, start)
        return BuiltInProbe(self.info, title, start, sharp=(kind == "sharper"))

    def start(self) -> bool:
        if self.running:
            return False
        if self.busy():
            self.failed.emit("Stop the episode that's playing first, so it doesn't count.")
            return False
        self.target = last_episode(self.ctx.store)
        if self.target is None:
            self.failed.emit("Watch an episode first: it's measured with the last one you watched.")
            return False
        if self.resolver is None:
            self.failed.emit("Measuring isn't available here.")
            return False
        anime_id, title, episode, position = self.target
        self.start_at = float(max(60, min(position or 0, 600)))
        self.runs = ["anigui"] + (["sharper"] if sharper.available() else [])
        found = find_player("iina")
        if found and found[0] == "iina":
            self.runs.append("iina")
        self.result = Measured(when=dt.date.today().isoformat(), what=f"{title}, episode {episode}")
        self.notes = []
        self.running = True
        self.step.emit("", "Finding the episode…")
        self._job = self.resolver.prepare(anime_id, title, episode, on_ready=self._got_stream,
                                          on_fail=lambda msg: self._fail(f"Couldn't load the episode: {msg}"))
        return True

    def stop(self) -> None:
        if not self.running:
            return
        self._end_run()
        if self._job is not None and hasattr(self.resolver, "cancel"):
            self.resolver.cancel(self._job)
        self.running = False
        self._timer.stop()
        self.failed.emit("Stopped.")

    def _got_stream(self, info) -> None:
        if not self.running:
            return
        self.info = info
        self._next()

    def _next(self) -> None:
        if not self.runs:
            self.running = False
            self._timer.stop()
            self.result.save(self.ctx)
            self.finished.emit(self.result)
            return
        kind = self.runs.pop(0)
        self.run = _Run(kind, started=time.monotonic())
        self.step.emit(kind, "Starting…")
        try:
            self.run.probe = self.make_probe(kind)
        except Exception as exc:  # noqa: BLE001 (IINA missing or open: skip it, say why)
            self.notes.append(str(exc))
            self.step.emit(kind, str(exc))
            self.run = None
            QTimer.singleShot(0, self._next)
            return
        self._timer.start()

    def _tick(self) -> None:
        r = self.run
        if r is None:
            return
        now = time.monotonic()
        pos = r.probe.position()
        if r.began is None:
            if pos is not None:
                if r.first_pos is None:
                    r.first_pos = pos
                elif pos > r.first_pos + 0.5:
                    r.began = now
            if r.began is None and now - r.started > START_TIMEOUT_S:
                self._skip(r, "didn't start playing in time")
            return
        if r.cpu0 is None:
            if now - r.began >= SETTLE_S:
                r.cpu0, r.pos0, r.t0 = r.probe.cpu(), pos, now
            return
        left = MEASURE_S - (now - r.t0)
        if left > 0:
            self.step.emit(r.kind, f"Measuring… {int(left) + 1} s")
            return
        cpu1 = r.probe.cpu()
        if cpu1 is None or r.cpu0 is None or pos is None or r.pos0 is None or pos - r.pos0 < MEASURE_S * 0.6:
            self._skip(r, "the stream kept pausing to load")
            return
        value = round(cpu.percent(r.cpu0, cpu1, now - r.t0), 1)
        setattr(self.result, r.kind, value)
        if r.kind == "anigui":
            self.result.height = r.probe.height()
        self.step.emit(r.kind, f"{value:.0f}%")
        self._end_run()
        QTimer.singleShot(800, self._next)

    def _skip(self, r: _Run, why: str) -> None:
        name = {"anigui": "The AniGUI player", "sharper": "Sharper picture", "iina": "IINA"}[r.kind]
        self.notes.append(f"{name}: {why}.")
        self.step.emit(r.kind, "Couldn't measure")
        self._end_run()
        QTimer.singleShot(0, self._next)

    def _end_run(self) -> None:
        self._timer.stop()
        if self.run is not None and self.run.probe is not None:
            try:
                self.run.probe.close()
            except Exception:  # noqa: BLE001
                pass
        self.run = None

    def _fail(self, message: str) -> None:
        self.running = False
        self._end_run()
        self.failed.emit(message)


# -- the cards ------------------------------------------------------------------------------------

class Meter(QWidget):
    """How hard the Mac works: a bar out of 100% of one core. None: not measured (striped)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(8)
        self.value: float | None = None
        self.cool = False
        self.busy = False
        self._phase = 0.0
        self._timer = QTimer(self, interval=40)
        self._timer.timeout.connect(self._spin)

    def set_value(self, value: float | None, cool: bool = False) -> None:
        self.value, self.cool = value, cool
        self.set_busy(False)
        self.update()

    def set_busy(self, on: bool) -> None:
        self.busy = on
        self._timer.start() if on else self._timer.stop()
        self.update()

    def _spin(self) -> None:
        self._phase = (self._phase + 0.025) % 1.4
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        track = QPainterPath()
        track.addRoundedRect(r, 4, 4)
        p.fillPath(track, QColor(theme.SURFACE_3))
        p.setClipPath(track)
        if self.busy:
            w = r.width() * 0.35
            x = r.left() + (self._phase - 0.35) * r.width()
            g = QLinearGradient(x, 0, x + w, 0)
            g.setColorAt(0, QColor(0, 0, 0, 0))
            g.setColorAt(0.5, QColor(theme.MUTED))
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(QRectF(x, r.top(), w, r.height()), g)
        elif self.value is None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#30303F"))
            x = r.left()
            while x < r.right():
                p.drawRect(QRectF(x + 6, r.top(), 6, r.height()))
                x += 12
        else:
            w = max(r.height(), r.width() * min(1.0, self.value / 100))
            bar = QRectF(r.left(), r.top(), w, r.height())
            if self.cool:
                p.fillRect(bar, QColor(theme.GOOD))
            else:
                g = QLinearGradient(bar.left(), 0, bar.right(), 0)
                g.setColorAt(0, QColor("#F5B942"))
                g.setColorAt(1, QColor(theme.ACCENT))
                p.fillRect(bar, g)


class PlayerCard(QFrame):
    picked = Signal(str)

    def __init__(self, kind: str, name: str, pitch: str, tag: str, parent=None) -> None:
        super().__init__(parent, objectName="PlayerCard")
        self.kind = kind
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.radio = QLabel(objectName="PlayerRadio")
        self.radio.setFixedSize(16, 16)
        self.name = QLabel(name, objectName="PlayerName")
        self.tag = QLabel(tag, objectName="PlayerTag")
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.radio)
        top.addWidget(self.name)
        top.addStretch(1)
        top.addWidget(self.tag)
        self.pitch = QLabel(pitch, objectName="Muted", wordWrap=True)
        self.pitch.setOpenExternalLinks(True)
        self.use_label = QLabel("Uses while playing", objectName="Muted")
        self.value = QLabel("—", objectName="PlayerValue")
        uses = QHBoxLayout()
        uses.addWidget(self.use_label)
        uses.addStretch(1)
        uses.addWidget(self.value)
        self.meter = Meter()
        self.extra = QLabel("", objectName="Muted")
        self.extra.setVisible(False)
        feats = QGridLayout()
        feats.setHorizontalSpacing(8)
        feats.setVerticalSpacing(2)
        for i, (yes, text) in enumerate(FEATURES[kind]):
            mark = QLabel("✓" if yes else "–", objectName="FeatYes" if yes else "FeatNo")
            feats.addWidget(mark, i, 0)
            feats.addWidget(QLabel(text, objectName="FeatText" if yes else "FeatOff", wordWrap=True), i, 1)
        feats.setColumnStretch(1, 1)
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(6)
        col.addLayout(top)
        col.addWidget(self.pitch)
        col.addSpacing(2)
        col.addLayout(uses)
        col.addWidget(self.meter)
        col.addWidget(self.extra)
        col.addSpacing(4)
        col.addLayout(feats)
        self.set_selected(False)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.radio.setProperty("selected", on)
        for w in (self, self.radio):
            w.style().unpolish(w)
            w.style().polish(w)

    def set_tag(self, text: str, light: bool = False) -> None:
        self.tag.setText(text)
        self.tag.setVisible(bool(text))
        self.tag.setProperty("light", light)
        self.tag.style().unpolish(self.tag)
        self.tag.style().polish(self.tag)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.kind)
        super().mousePressEvent(e)


class PlayerChooser(QWidget):
    """Settings → Playback: the AniGUI player or IINA (and other players)."""

    def __init__(self, ctx, controls: dict, resolver=None, busy=lambda: False, parent=None) -> None:
        super().__init__(parent, objectName="PlayerChooser")
        self.ctx = ctx
        title = QLabel("Where episodes play", objectName="SettingTitle")
        desc = QLabel("Both track your progress, play the next episode and skip intros. They differ in how much "
                      "of your Mac they use, and what you can do while watching.", objectName="Muted",
                      wordWrap=True)
        self.cards = {
            "anigui": PlayerCard("anigui", "AniGUI player", "Plays right here in the window.", "MORE FEATURES"),
            "iina": PlayerCard("iina", "IINA", "Opens in its own window.", "LIGHTER"),
        }
        self.iina_installed = bool((f := find_player("iina")) and f[0] == "iina")
        if not self.iina_installed:
            self.cards["iina"].pitch.setText('Not installed. It\'s free: <a href="https://iina.io" '
                                             'style="color:#9B9BAF">iina.io</a>')
        cards = QHBoxLayout()
        cards.setSpacing(10)
        for card in self.cards.values():
            card.picked.connect(self.pick)
            cards.addWidget(card, 1)

        # measuring
        self.measurer = Measurer(ctx, resolver, busy, self)
        self.measurer.step.connect(self._on_step)
        self.measurer.finished.connect(self._on_finished)
        self.measurer.failed.connect(self._on_failed)
        self.measure_box = QFrame(objectName="MeasureBox")
        mrow = QHBoxLayout(self.measure_box)
        mrow.setContentsMargins(12, 10, 12, 10)
        mrow.setSpacing(12)
        self.measure_btn = QPushButton("Measure on this Mac", objectName="Primary",
                                       cursor=Qt.CursorShape.PointingHandCursor)
        self.measure_btn.clicked.connect(self.measure)
        self.measure_text = QLabel("", objectName="Muted", wordWrap=True)
        self.stop_btn = QPushButton("Stop", cursor=Qt.CursorShape.PointingHandCursor)
        self.stop_btn.clicked.connect(self.measurer.stop)
        self.stop_btn.hide()
        mrow.addWidget(self.measure_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        mrow.addWidget(self.measure_text, 1)
        mrow.addWidget(self.stop_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.footnote = QLabel("", objectName="Muted", wordWrap=True)
        self.footnote.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.footnote.linkActivated.connect(lambda _l: self.measure())

        # other players
        self.other = Combo(cursor=Qt.CursorShape.PointingHandCursor)
        self.other.setFixedWidth(210)
        for label, value in OTHER:
            self.other.addItem(label, value)
        self.other.currentIndexChanged.connect(self._other_changed)
        controls["player"] = self.other
        other_row = QHBoxLayout()
        other_text = QVBoxLayout()
        other_text.setSpacing(2)
        other_text.addWidget(QLabel("Other players", objectName="SettingTitle"))
        other_text.addWidget(QLabel("Prefer mpv? Pick it here instead.", objectName="Muted"))
        other_row.addLayout(other_text, 1)
        other_row.addWidget(self.other, 0, Qt.AlignmentFlag.AlignVCenter)

        col = QVBoxLayout(self)
        col.setContentsMargins(16, 14, 16, 14)
        col.setSpacing(8)
        col.addWidget(title)
        col.addWidget(desc)
        col.addSpacing(4)
        col.addLayout(cards)
        col.addWidget(self.measure_box)
        col.addWidget(self.footnote)
        line = QFrame(objectName="SettingsDivider", frameShape=QFrame.Shape.HLine)
        col.addSpacing(4)
        col.addWidget(line)
        col.addSpacing(4)
        col.addLayout(other_row)
        self.show_choice()
        self.show_measured(Measured.load(ctx))
        ctx.events.changed.connect(self._pref_changed)

    # -- the choice -------------------------------------------------------------------------------

    def pick(self, kind: str) -> None:
        self.ctx.set_pref("player", kind)
        self.show_choice()

    def _other_changed(self, _i: int) -> None:
        value = self.other.currentData()
        if value:
            self.ctx.set_pref("player", value)
        elif self.ctx.pref("player") not in ("anigui", "iina"):
            self.ctx.set_pref("player", "anigui")     # "Don't use": back to the AniGUI player
        self.show_choice()

    def show_choice(self) -> None:
        chosen = self.ctx.pref("player")
        for kind, card in self.cards.items():
            card.set_selected(kind == chosen)
        value = chosen if chosen in ("auto", "mpv") else ""
        i = self.other.findData(value)
        if i != self.other.currentIndex():
            self.other.blockSignals(True)
            self.other.setCurrentIndex(i)
            self.other.blockSignals(False)

    def _pref_changed(self, key: str, _value) -> None:
        if key == "player":
            self.show_choice()

    # -- measuring --------------------------------------------------------------------------------

    def measure(self) -> None:
        if self.measurer.start():
            self.measure_btn.hide()
            self.stop_btn.show()
            self.measure_box.show()
            self.footnote.hide()
            for card in self.cards.values():
                card.value.setText("…")
                card.meter.set_value(None)
                card.extra.hide()

    def _on_step(self, kind: str, text: str) -> None:
        names = {"anigui": "the AniGUI player", "sharper": "the AniGUI player with Sharper picture",
                 "iina": "IINA"}
        if not kind:
            self.measure_text.setText(text)
            return
        card = self.cards["anigui" if kind == "sharper" else kind]
        where = ("It opened behind this window, muted. It closes by itself when done." if kind == "iina"
                 else "Playing muted in a small window. It closes by itself when done.")
        self.measure_text.setText(f"<b>Measuring {names[kind]}</b> · {text} {where}")
        if text.endswith("%"):
            if kind == "sharper":
                card.extra.setText(f"With Sharper picture on: {text}")
                card.extra.show()
            else:
                card.value.setText(text)
            card.meter.set_busy(False)
        elif kind != "sharper":
            card.meter.set_busy(True)
            card.use_label.setText(text if text.startswith("Measuring") else "Uses while playing")

    def _on_finished(self, result: Measured) -> None:
        self.stop_btn.hide()
        self.measure_btn.show()
        self.show_measured(result)

    def _on_failed(self, message: str) -> None:
        self.stop_btn.hide()
        self.measure_btn.show()
        self.measure_box.show()
        self.measure_text.setText(message)
        self.show_measured(Measured.load(self.ctx), keep_box=True)

    def show_measured(self, m: Measured | None, keep_box: bool = False) -> None:
        a, i = self.cards["anigui"], self.cards["iina"]
        for card in (a, i):
            card.use_label.setText("Uses while playing")
            card.meter.set_busy(False)
        if m is None or m.anigui is None:
            for card in (a, i):
                card.value.setText("—")
                card.meter.set_value(None)
                card.extra.hide()
            i.set_tag("LIGHTER" if self.iina_installed else "NOT INSTALLED", light=self.iina_installed)
            self.measure_box.show()
            if not keep_box:
                self.measure_text.setText("Plays 20 seconds of <b>the last episode you watched</b> in each player, "
                                          "muted, and checks how hard your Mac works. About a minute. Nothing "
                                          "is sent anywhere.")
            self.footnote.hide()
            return
        cool_iina = m.iina is not None and m.iina < m.anigui
        a.value.setText(f"{m.anigui:.0f}%")
        a.meter.set_value(m.anigui, cool=not cool_iina and m.iina is not None)
        if m.sharper is not None:
            extra = m.sharper - m.anigui
            a.extra.setText(f"With Sharper picture on: {m.sharper:.0f}%"
                            + (f"  (+{extra:.0f})" if extra >= 1 else ""))
            a.extra.show()
        else:
            a.extra.hide()
        if m.iina is not None:
            i.value.setText(f"{m.iina:.0f}%")
            i.meter.set_value(m.iina, cool=cool_iina)
            words = share_words(m.ratio)
            i.set_tag(f"{words.upper()} THE WORK" if words else "LIGHTER", light=True)
        else:
            i.value.setText("—")
            i.meter.set_value(None)
            i.set_tag("LIGHTER" if self.iina_installed else "NOT INSTALLED", light=self.iina_installed)
        if not keep_box:
            self.measure_box.hide()
        when = m.when
        try:
            day = dt.date.fromisoformat(m.when)
            when = "today" if day == dt.date.today() else f"on {day:%b} {day.day}"
        except (TypeError, ValueError):
            pass
        res = f" ({m.height}p)" if m.height else ""
        notes = (" " + " ".join(self.measurer.notes)) if self.measurer.notes else ""
        self.footnote.setText(f"Measured {when} on this Mac with {m.what}{res}. % is of one processor core.{notes} "
                              f'<a href="again" style="color:{theme.TEXT}">Measure again</a>')
        self.footnote.show()


# -- the hint in the player (on battery, once) ------------------------------------------------

class BatteryHint(QFrame):
    """On battery, the first time: IINA uses less. Shown once, ever."""

    def __init__(self, ctx, parent: QWidget) -> None:
        super().__init__(parent, objectName="BatteryHint")
        self.ctx = ctx
        self.setFixedWidth(400)
        icon = QLabel("🔋", objectName="BatteryIcon")
        self.title = QLabel("On battery", objectName="SettingTitle")
        self.text = QLabel("", objectName="Muted", wordWrap=True)
        self.use_iina = QPushButton("Use IINA from next episode", objectName="Primary",
                                    cursor=Qt.CursorShape.PointingHandCursor)
        self.keep = QPushButton("Keep this", cursor=Qt.CursorShape.PointingHandCursor)
        self.use_iina.clicked.connect(self._switch)
        self.keep.clicked.connect(self.hide)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.use_iina)
        buttons.addWidget(self.keep)
        buttons.addStretch(1)
        body = QVBoxLayout()
        body.setSpacing(4)
        body.addWidget(self.title)
        body.addWidget(self.text)
        body.addSpacing(6)
        body.addLayout(buttons)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(body, 1)
        self._auto = QTimer(self, singleShot=True, interval=25_000)
        self._auto.timeout.connect(self.hide)
        self.hide()

    @staticmethod
    def wanted(ctx) -> bool:
        if ctx.pref("battery_hint_done") or ctx.pref("player") != "anigui":
            return False
        found = find_player("iina")
        if not found or found[0] != "iina":
            return False
        m = Measured.load(ctx)
        if m is not None and m.ratio is not None and m.ratio > 0.8:
            return False                      # IINA wasn't clearly lighter on this Mac
        return cpu.on_battery()

    def offer(self) -> None:
        m = Measured.load(self.ctx)
        words = share_words(m.ratio if m else None)
        lead = (f"IINA uses {words} of the power the AniGUI player does on this Mac." if words
                else "IINA usually uses much less power than the AniGUI player.")
        self.text.setText(f"{lead} You'd lose the pop-out, moments and sleep timer.")
        self.ctx.set_pref("battery_hint_done", True)
        self.text.setFixedWidth(self.width() - 14 * 2 - 12 - 26)      # (the text wraps: its own width)
        self.text.setFixedHeight(self.text.heightForWidth(self.text.width()))
        self.layout().activate()
        self.setFixedHeight(self.layout().sizeHint().height())
        self.place()
        self.show()
        self.raise_()
        self._auto.start()

    def place(self) -> None:
        p = self.parentWidget()
        if p is not None:
            self.move(p.width() - self.width() - 20, max(10, p.height() - self.height() - 70))

    def _switch(self) -> None:
        self.ctx.set_pref("player", "iina")
        self.hide()
