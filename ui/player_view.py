"""The built-in player: video inside AniGUI's window.

PlayerHost floats above the pages. On the playing show's page it sits exactly over the
page's video slot (the theater, with the episode list beside it); anywhere else it shrinks
to a mini-player in the corner; F makes it fill the screen. The video comes from libmpv
(VideoView). Everything else talks to mpv through the same control socket the external
players use, so progress, skips and auto-play work exactly as before (ui/playback.Session).
"""

from __future__ import annotations

import math
import os
import random
import sys
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QSurfaceFormat
from PySide6.QtWidgets import QApplication, QFrame, QMenu, QPushButton, QVBoxLayout, QWidget

from core import libmpv, macwin, sharper
from core.power import KeepAwake

from . import festive, theme
from .motion import reduce_motion, set_quiet

MINI_W, MINI_H = 336, 189
HIDE_AFTER_MS = 2500
SPEEDS = (0.75, 1.0, 1.25, 1.5, 2.0)


def fmt_time(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or math.isnan(seconds):
        return "--:--"
    s = int(seconds)
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


_available: bool | None = None


def available() -> bool:
    """Can the built-in player run here (is there a libmpv that loads)?"""
    global _available
    if _available is None:
        try:
            libmpv.load()
            _available = True
        except Exception:  # noqa: BLE001
            _available = False
    return _available


# -- the video -------------------------------------------------------------------------------------

try:
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
except ImportError:  # pragma: no cover
    QOpenGLWidget = QWidget  # type: ignore[misc,assignment]


class VideoView(QOpenGLWidget):
    """libmpv drawing into AniGUI's window."""

    frameReady = Signal()
    wakeup = Signal()
    shutdown = Signal()

    def __init__(self, options: dict, url: str, tracks: list, parent=None) -> None:
        super().__init__(parent)
        # The video's OpenGL context must match the window's: a context of its own kind
        # (asking for a different version here) can't share with the window, and the slot then
        # shows a flipped copy of the window instead of the video (1.11.0).
        if os.environ.get("ANIGUI_GL") == "widget-core":
            fmt = QSurfaceFormat()
            fmt.setVersion(4, 1)
            fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
            self.setFormat(fmt)
        self.mpv = libmpv.Mpv(options)          # opens the control socket right away
        self.url, self.tracks = url, list(tracks)
        self.renderer: libmpv.GlRenderer | None = None
        self._gl_context = None
        self._vid: str | None = None             # the video track, while between windows
        self.frameReady.connect(self.update, Qt.ConnectionType.QueuedConnection)
        self.frameSwapped.connect(self._swapped)       # (helps mpv keep the timing even)
        self.wakeup.connect(self._drain, Qt.ConnectionType.QueuedConnection)
        self.mpv.on_wakeup(self.wakeup.emit)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def initializeGL(self) -> None:
        # Moving the video to another window (the pop-out and back) gives it a new OpenGL
        # context: the old renderer goes with the old context, and a new one is made here.
        ctx = self.context()
        if ctx is not None and ctx is not self._gl_context:
            self._gl_context = ctx
            ctx.aboutToBeDestroyed.connect(self._release_gl, Qt.ConnectionType.DirectConnection)
        if self.renderer is None and self.mpv.handle:
            self.renderer = libmpv.GlRenderer(self.mpv, libmpv.gl_proc_address())
            self.renderer.on_update(self.frameReady.emit)
            if self.url:
                self.mpv.command("loadfile", self.url)   # only now: mpv needs somewhere to draw
                self.url = ""
            elif self._vid not in (None, "", "no"):
                # mpv switched the picture off when the old renderer went away; switch it back on
                try:
                    self.mpv.set("vid", self._vid)
                except libmpv.LibMpvError:
                    self.mpv.set("vid", "auto")
                self._vid = None

    def _swapped(self) -> None:
        if self.renderer is not None:
            self.renderer.report_swap()

    def _release_gl(self) -> None:
        if self.renderer is None:
            return
        if self.mpv.handle:
            self._vid = self.mpv.get("vid")
        self.makeCurrent()
        self.renderer.close()
        self.doneCurrent()
        self.renderer = None

    def paintGL(self) -> None:
        if self.renderer is not None:
            r = self.devicePixelRatio()
            self.renderer.render(self.defaultFramebufferObject(), int(self.width() * r), int(self.height() * r))

    def _drain(self) -> None:
        if not self.mpv.handle:
            return
        for kind, _data in self.mpv.events():
            if kind == "loaded" and self.tracks:
                for cmd, url, flag in self.tracks:
                    self.mpv.command(cmd, url, flag)
                self.tracks = []
            elif kind == "shutdown":
                self.shutdown.emit()

    def close_engine(self) -> None:
        if self.renderer is not None:
            self.makeCurrent()
            self.renderer.close()
            self.doneCurrent()
            self.renderer = None
        self.mpv.close()


class Placeholder(QWidget):
    """Black, where the video goes when there's no libmpv (tests)."""

    def paintEvent(self, _e) -> None:
        QPainter(self).fillRect(self.rect(), QColor("#000000"))


# -- icons (drawn, so they're sharp at any size) -------------------------------------------------------

def _icon(p: QPainter, kind: str, c: QPointF, s: float, color: QColor) -> None:
    p.save()
    p.translate(c)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    pen = QPen(color, max(1.6, s * 0.11), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    h = s / 2
    path = QPainterPath()
    if kind == "play":
        path.moveTo(-h * 0.6, -h * 0.8)
        path.lineTo(h * 0.85, 0)
        path.lineTo(-h * 0.6, h * 0.8)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "pause":
        p.drawRoundedRect(QRectF(-h * 0.7, -h * 0.8, h * 0.5, h * 1.6), 1.5, 1.5)
        p.drawRoundedRect(QRectF(h * 0.2, -h * 0.8, h * 0.5, h * 1.6), 1.5, 1.5)
    elif kind == "next":
        path.moveTo(-h * 0.75, -h * 0.75)
        path.lineTo(h * 0.45, 0)
        path.lineTo(-h * 0.75, h * 0.75)
        path.closeSubpath()
        p.drawPath(path)
        p.drawRect(QRectF(h * 0.5, -h * 0.75, h * 0.25, h * 1.5))
    elif kind in ("back10", "fwd10"):
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(pen)
        sign = -1 if kind == "back10" else 1
        rect = QRectF(-h * 0.8, -h * 0.8, h * 1.6, h * 1.6)
        p.drawArc(rect, (90 + 40 * sign) * 16, int(-sign * 290 * 16))
        tip = QPointF(sign * h * 0.15, -h * 0.8)
        p.drawLine(tip, tip + QPointF(-sign * h * 0.35, -h * 0.3))
        p.drawLine(tip, tip + QPointF(-sign * h * 0.35, h * 0.3))
        p.setFont(theme.font(max(7, int(s * 0.32)), QFont.Weight.Bold))
        p.setPen(color)
        p.drawText(QRectF(-h, -h * 0.55, s, h * 1.3), Qt.AlignmentFlag.AlignCenter, "10")
    elif kind in ("volume", "muted"):
        path.moveTo(-h * 0.8, -h * 0.3)
        path.lineTo(-h * 0.35, -h * 0.3)
        path.lineTo(h * 0.15, -h * 0.75)
        path.lineTo(h * 0.15, h * 0.75)
        path.lineTo(-h * 0.35, h * 0.3)
        path.lineTo(-h * 0.8, h * 0.3)
        path.closeSubpath()
        p.drawPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(pen)
        if kind == "volume":
            p.drawArc(QRectF(-h * 0.2, -h * 0.55, h * 0.9, h * 1.1), -50 * 16, 100 * 16)
        else:
            p.drawLine(QPointF(h * 0.4, -h * 0.3), QPointF(h * 0.95, h * 0.3))
            p.drawLine(QPointF(h * 0.95, -h * 0.3), QPointF(h * 0.4, h * 0.3))
    elif kind == "gear":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(pen)
        p.drawEllipse(QPointF(0, 0), h * 0.32, h * 0.32)
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(QPointF(math.cos(a) * h * 0.55, math.sin(a) * h * 0.55),
                       QPointF(math.cos(a) * h * 0.85, math.sin(a) * h * 0.85))
        p.drawEllipse(QPointF(0, 0), h * 0.6, h * 0.6)
    elif kind == "pip":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(pen)
        p.drawRoundedRect(QRectF(-h * 0.85, -h * 0.65, h * 1.7, h * 1.3), 2, 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(0, 0, h * 0.7, h * 0.5), 1.5, 1.5)
    elif kind in ("full", "unfull", "expand"):
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(pen)
        out = kind != "unfull"                  # corners pointing out (enter) or in (leave)
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            corner = QPointF(sx * h * (0.8 if out else 0.3), sy * h * (0.8 if out else 0.3))
            arm = -0.4 * h if out else 0.4 * h
            p.drawLine(corner, corner + QPointF(sx * arm, 0))
            p.drawLine(corner, corner + QPointF(0, sy * arm))
    elif kind in ("popout", "popin"):
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(pen)
        frame = QPainterPath()
        frame.moveTo(h * 0.1, -h * 0.75)
        frame.lineTo(-h * 0.8, -h * 0.75)
        frame.lineTo(-h * 0.8, h * 0.75)
        frame.lineTo(h * 0.8, h * 0.75)
        frame.lineTo(h * 0.8, -h * 0.1)
        p.drawPath(frame)
        a, b = QPointF(-h * 0.15, h * 0.15), QPointF(h * 0.85, -h * 0.85)
        if kind == "popin":
            a, b = b, a
        p.drawLine(a, b)
        d = QPointF(b.x() - a.x(), b.y() - a.y())
        n = math.hypot(d.x(), d.y()) or 1
        ux, uy = d.x() / n, d.y() / n
        for side in (1, -1):
            p.drawLine(b, b - QPointF(ux * h * 0.45 - side * uy * h * 0.3, uy * h * 0.45 + side * ux * h * 0.3))
    elif kind == "list":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(pen)
        for y in (-0.55, 0.0, 0.55):
            p.drawLine(QPointF(-h * 0.75, y * h), QPointF(h * 0.75, y * h))
    elif kind == "close":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(pen)
        p.drawLine(QPointF(-h * 0.55, -h * 0.55), QPointF(h * 0.55, h * 0.55))
        p.drawLine(QPointF(h * 0.55, -h * 0.55), QPointF(-h * 0.55, h * 0.55))
    elif kind == "down":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(pen)
        p.drawLine(QPointF(-h * 0.55, -h * 0.25), QPointF(0, h * 0.3))
        p.drawLine(QPointF(0, h * 0.3), QPointF(h * 0.55, -h * 0.25))
    p.restore()


# -- the controls ------------------------------------------------------------------------------------

class PlayerControls(QWidget):
    """Everything drawn over the video: title, progress bar, buttons, Skip intro, Up next,
    short messages. Fades in on mouse move, out after a couple of seconds of playing."""

    action = Signal(str)          # play / back10 / fwd10 / next / mute / menu / mini / full / down / close / expand
    dragBy = Signal(QPointF)      # the mini-player being moved
    seekTo = Signal(float)        # seconds
    skip = Signal()
    upNext = Signal(bool)         # True: play now, False: cancel

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.title = ""
        self.chip = ""
        self.position: float | None = None
        self.duration: float | None = None
        self.paused = False
        self.muted = False
        self.segments: list = []
        self.skip_label: str | None = None
        self.countdown: tuple[str, int] | None = None   # ("Episode 6", seconds)
        self.next_title = ""
        self.message: tuple[str, float] | None = None
        self.mode = "theater"         # theater | mini | full
        self.shown = True
        self.alpha = 1.0
        self.menu_open = False
        self.hover = ""
        self.hover_x: float | None = None
        self.dragging = False
        self._hits: dict[str, QRectF] = {}
        self._hide = QTimer(self, singleShot=True, interval=HIDE_AFTER_MS)
        self._hide.timeout.connect(self._auto_hide)
        self._fade = QTimer(self, interval=16)
        self._fade.timeout.connect(self._fade_step)
        self._msg_timer = QTimer(self, singleShot=True)
        self._msg_timer.timeout.connect(self._clear_message)
        # Holiday: snow drifts over the picture while it's paused (and settles on the bar)
        self.flakes: list[list[float]] = []
        self._snow = QTimer(self, interval=33)
        self._snow.timeout.connect(self._snow_step)

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        wanted = paused and theme.HOLIDAY and festive_on("player_snow") and self.mode not in ("mini", "pop")
        if wanted and not reduce_motion():
            self._snow.start()
        else:
            self._snow.stop()
            self.flakes = []
        self.update()

    def _snow_step(self) -> None:
        w, h = self.width(), self.height()
        if len(self.flakes) < 70:
            self.flakes.append([random.uniform(0, w), -4.0, random.uniform(1.2, 2.8), random.uniform(0.6, 1.5),
                                random.uniform(0, 6.3)])
        for f in self.flakes:
            f[1] += f[3]
            f[4] += 0.04
            f[0] += math.sin(f[4]) * 0.5
        floor = h - 92
        self.flakes = [f for f in self.flakes if f[1] < floor]
        self.update()

    # -- state ------------------------------------------------------------------------

    def keep_visible(self) -> bool:
        return (self.paused or self.menu_open or self.dragging or self.countdown is not None
                or self.hover.startswith(("bar", "btn")))

    def poke(self) -> None:
        """Mouse moved: show the controls and start the hide timer again."""
        self._set_shown(True)
        self._hide.start()

    def _auto_hide(self) -> None:
        if self.keep_visible() or (self.underMouse() and self.mode in ("mini", "pop")):
            self._hide.start()
            return
        self._set_shown(False)

    def _set_shown(self, on: bool) -> None:
        if on == self.shown:
            return
        self.shown = on
        if self.mode == "full":
            self.setCursor(Qt.CursorShape.ArrowCursor if on else Qt.CursorShape.BlankCursor)
        if reduce_motion():
            self.alpha = 1.0 if on else 0.0
            self.update()
        else:
            self._fade.start()

    def _fade_step(self) -> None:
        target = 1.0 if self.shown else 0.0
        self.alpha += (0.12 if self.shown else -0.08)
        if (self.shown and self.alpha >= 1) or (not self.shown and self.alpha <= 0):
            self.alpha = target
            self._fade.stop()
        self.update()

    sleep_text = ""

    def show_message(self, text: str, ms: int) -> None:
        self.message = (text, time.monotonic() + ms / 1000)
        self._msg_timer.start(max(500, ms))
        self.update()

    def _clear_message(self) -> None:
        self.message = None
        self.update()

    def set_countdown(self, label: str, seconds: int) -> None:
        self.countdown = (label, seconds) if seconds >= 0 else None
        if self.countdown:
            self._set_shown(True)
        self.update()

    # -- painting -----------------------------------------------------------------------

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hits = {}
        r = QRectF(self.rect())
        mini = self.mode in ("mini", "pop")
        if theme.HOLIDAY and self.mode != "full":
            self._snow_cap(p, r)
        if self.flakes:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 210))
            for x, y, rad, _v, _d in self.flakes:
                p.drawEllipse(QPointF(x, y), rad, rad)
        a = self.alpha
        if a <= 0.01 and self.mode == "theater":
            self._back_chip(p, r, 10 if theme.HOLIDAY else 0, 0.75)
        if a > 0.01:
            p.save()
            p.setOpacity(a)
            self._paint_controls(p, r, mini)
            p.restore()
        if self.skip_label and self.mode != "mini":
            self._paint_skip(p, r)
        if self.countdown is not None:
            self._paint_up_next(p, r, mini)
        if self.message and self.mode != "mini":
            self._paint_message(p, r)
        if theme.HOLIDAY and self.mode == "theater" and festive_on("player_bow"):
            self._bow(p, r)
        p.end()

    def _snow_cap(self, p: QPainter, r: QRectF) -> None:
        path = QPainterPath()
        path.moveTo(r.left(), r.top())
        path.lineTo(r.right(), r.top())
        path.lineTo(r.right(), r.top() + 4)
        x, up = r.right(), True
        step = 34.0
        while x > r.left():
            nx = max(r.left(), x - step)
            path.quadTo(QPointF((x + nx) / 2, r.top() + (11 if up else 3)), QPointF(nx, r.top() + 4))
            x, up = nx, not up
        path.closeSubpath()
        p.fillPath(path, QColor(festive.SNOW))

    def _bow(self, p: QPainter, r: QRectF) -> None:
        p.save()
        p.translate(r.right() - 26, r.top() + 14)
        red, dark = QColor("#E0403C"), QColor("#B3302D")
        for sign in (-1, 1):
            loop = QPainterPath()
            loop.moveTo(0, 0)
            loop.lineTo(sign * 16, -10)
            loop.quadTo(QPointF(sign * 21, 0), QPointF(sign * 14, 8))
            loop.closeSubpath()
            p.fillPath(loop, red)
            tail = QPainterPath()
            tail.moveTo(sign * 1.5, 0)
            tail.lineTo(sign * 9, 16)
            tail.lineTo(sign * 5, 15)
            tail.lineTo(sign * 0.5, 2)
            tail.closeSubpath()
            p.fillPath(tail, dark)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dark)
        p.drawEllipse(QPointF(0, 0), 4, 4)
        p.restore()

    def _paint_controls(self, p: QPainter, r: QRectF, mini: bool) -> None:
        white, muted = QColor("#FFFFFF"), QColor(255, 255, 255, 190)
        top_h = 64 if not mini else 44
        p.fillRect(QRectF(r.left(), r.top(), r.width(), top_h), QColor(0, 0, 0, 90))
        bottom_h = 92 if not mini else 30
        p.fillRect(QRectF(r.left(), r.bottom() - bottom_h, r.width(), bottom_h), QColor(0, 0, 0, 120))
        pad = 16 if not mini else 10
        cap = 10 if theme.HOLIDAY and self.mode != "full" else 0
        if mini:
            top = r.top() + 20 + cap / 2
            if self.mode == "pop":
                self._button(p, "popin", QPointF(r.left() + 20, top), 16, white)
                if r.width() >= 380:
                    p.setFont(theme.font(12, QFont.Weight.DemiBold))
                    p.setPen(muted)
                    title = QRectF(r.left() + 44, top - 10, r.width() - 88, 20)
                    p.drawText(title, Qt.AlignmentFlag.AlignCenter, p.fontMetrics().elidedText(
                        self.title, Qt.TextElideMode.ElideRight, int(title.width())))
            else:
                self._button(p, "expand", QPointF(r.left() + 18, top), 16, white)
                self._button(p, "popout", QPointF(r.right() - 52, top), 16, white)
            self._button(p, "close", QPointF(r.right() - 18, top), 14, white)
            big = 34 if r.width() < 420 else 42
            self._button(p, "play", r.center(), big, white, "pause" if not self.paused else "play", circle=True)
            if self.mode == "pop" and r.width() >= 300:
                gap = big * 1.9
                self._button(p, "back10", r.center() - QPointF(gap, 0), 24, white)
                self._button(p, "fwd10", r.center() + QPointF(gap, 0), 24, white)
        else:
            back_w = self._back_chip(p, r, cap, 1.0)
            p.setFont(theme.font(13, QFont.Weight.DemiBold))
            p.setPen(white)
            title_rect = QRectF(r.left() + pad + back_w + 10, r.top() + 12 + cap, r.width() - 2 * pad - back_w - 110, 24)
            p.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(self.title, Qt.TextElideMode.ElideRight, int(title_rect.width())))
            if self.chip:
                p.setFont(theme.font(10, QFont.Weight.Bold))
                w = p.fontMetrics().horizontalAdvance(self.chip) + 14
                chip = QRectF(r.right() - pad - w - (34 if theme.HOLIDAY and festive_on("player_bow") else 0),
                              r.top() + 14 + cap, w, 20)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 40))
                p.drawRoundedRect(chip, 5, 5)
                p.setPen(white)
                p.drawText(chip, Qt.AlignmentFlag.AlignCenter, self.chip)
            if self.paused:
                self._button(p, "play", r.center(), 54, white, "play", circle=True)
        # progress bar
        bar_y = r.bottom() - (62 if not mini else 8)
        bar = QRectF(r.left() + pad, bar_y, r.width() - 2 * pad, 5 if not mini else 3)
        self._hits["bar"] = bar.adjusted(0, -9, 0, 9)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawRoundedRect(bar, 2.5, 2.5)
        if self.duration:
            for seg in self.segments:
                x0 = bar.left() + bar.width() * max(0.0, seg.start / self.duration)
                x1 = bar.left() + bar.width() * min(1.0, seg.end / self.duration)
                p.fillRect(QRectF(x0, bar.top(), max(2.0, x1 - x0), bar.height()), QColor(255, 255, 255, 110))
            frac = max(0.0, min(1.0, (self.position or 0) / self.duration))
            festive.progress_bar(p, bar, frac, theme.ACCENT)
            if not mini:
                kx = bar.left() + bar.width() * frac
                if theme.HOLIDAY:
                    festive.ornament(p, QPointF(kx, bar.center().y()), 7.5, True)
                else:
                    p.setBrush(white)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.drawEllipse(QPointF(kx, bar.center().y()), 6.5, 6.5)
                if self.hover == "bar" and self.hover_x is not None:
                    t = (self.hover_x - bar.left()) / bar.width() * self.duration
                    self._tooltip(p, QPointF(self.hover_x, bar.top() - 16), fmt_time(t))
        if mini:
            return
        y = r.bottom() - 30
        x = r.left() + pad + 10
        icons = [("play", "pause" if not self.paused else "play", 22), ("back10", "back10", 22),
                 ("fwd10", "fwd10", 22), ("next", "next", 18), ("mute", "muted" if self.muted else "volume", 22)]
        for name, icon, size in icons:
            self._button(p, name, QPointF(x, y), size, white, icon)
            x += 40
        p.setFont(theme.font(12))
        p.setPen(muted)
        p.drawText(QRectF(x - 6, y - 10, 160, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{fmt_time(self.position)} / {fmt_time(self.duration)}")
        if self.sleep_text:                      # Sleep timer (2.0)
            p.setPen(QColor("#C9B8FF"))
            p.drawText(QRectF(x + 120, y - 10, 160, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       ("❄ " if theme.HOLIDAY else "☾ ") + self.sleep_text)
        x = r.right() - pad - 10
        for name, icon in (("full", "unfull" if self.mode == "full" else "full"), ("popout", "popout"),
                           ("mini", "pip"), ("menu", "gear"), ("list", "list")):
            self._button(p, name, QPointF(x, y), 20, white, icon)
            x -= 40

    def _back_chip(self, p: QPainter, r: QRectF, cap: float, opacity: float) -> float:
        """'‹ Back' in the top-left corner: always there (even when the rest fades out)."""
        p.save()
        p.setOpacity(opacity)
        p.setFont(theme.font(12, QFont.Weight.Bold))
        w = p.fontMetrics().horizontalAdvance("Back") + 34
        box = QRectF(r.left() + 14, r.top() + 12 + cap, w, 26)
        self._hits["btn:back"] = box.adjusted(-4, -4, 4, 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 150) if self.hover != "btn:back" else QColor(30, 30, 40, 220))
        p.drawRoundedRect(box, 8, 8)
        p.setPen(QPen(QColor("#FFFFFF"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        cx, cy = box.left() + 13, box.center().y()
        p.drawLine(QPointF(cx + 3, cy - 5), QPointF(cx - 2, cy))
        p.drawLine(QPointF(cx - 2, cy), QPointF(cx + 3, cy + 5))
        p.setPen(QColor("#FFFFFF"))
        p.drawText(box.adjusted(20, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Back")
        p.restore()
        return w

    def _button(self, p: QPainter, name: str, c: QPointF, size: float, color: QColor, icon: str | None = None,
                circle: bool = False) -> None:
        hit = QRectF(c.x() - size / 2 - 7, c.y() - size / 2 - 7, size + 14, size + 14)
        self._hits["btn:" + name] = hit
        if circle:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 120))
            p.drawEllipse(c, size * 0.9, size * 0.9)
        elif self.hover == "btn:" + name:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 36))
            p.drawEllipse(c, size * 0.85, size * 0.85)
        _icon(p, icon or name, c + (QPointF(size * 0.06, 0) if (icon or name) == "play" else QPointF()), size, color)

    def _tooltip(self, p: QPainter, at: QPointF, text: str) -> None:
        p.setFont(theme.font(11, QFont.Weight.Bold))
        w = p.fontMetrics().horizontalAdvance(text) + 14
        box = QRectF(at.x() - w / 2, at.y() - 22, w, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.SURFACE_2))
        p.drawRoundedRect(box, 5, 5)
        p.setPen(QColor(theme.TEXT))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_skip(self, p: QPainter, r: QRectF) -> None:
        text = f"Skip {self.skip_label}"
        p.setFont(theme.font(12, QFont.Weight.Bold))
        w = p.fontMetrics().horizontalAdvance(text) + (46 if theme.HOLIDAY else 40)
        box = QRectF(r.right() - 16 - w, r.bottom() - 92 - 42, w, 34)
        self._hits["skip"] = box
        if theme.HOLIDAY:                       # a gift tag
            tag = QPainterPath()
            tag.moveTo(box.left() + 12, box.top())
            tag.lineTo(box.right() - 6, box.top())
            tag.quadTo(box.topRight(), box.topRight() + QPointF(0, 6))
            tag.lineTo(box.right(), box.bottom() - 6)
            tag.quadTo(box.bottomRight(), box.bottomRight() - QPointF(6, 0))
            tag.lineTo(box.left() + 12, box.bottom())
            tag.lineTo(box.left(), box.center().y())
            tag.closeSubpath()
            p.fillPath(tag, QColor("#F4E7C8"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#5A2629"))
            p.drawEllipse(QPointF(box.left() + 10, box.center().y()), 2.6, 2.6)
            p.setPen(QPen(QColor("#E0403C"), 1.6))
            p.drawLine(QPointF(box.left() + 10, box.center().y()), QPointF(box.left() - 6, box.center().y() + 9))
            p.setPen(QColor("#5A2629"))
            p.drawText(box.adjusted(16, 0, 0, 0), Qt.AlignmentFlag.AlignCenter, "🎁 " + text)
        else:
            p.setPen(QPen(QColor(255, 255, 255, 90), 1))
            p.setBrush(QColor(20, 20, 28, 225) if self.hover != "skip" else QColor(40, 40, 52, 235))
            p.drawRoundedRect(box, 8, 8)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(box.adjusted(0, 0, -14, 0), Qt.AlignmentFlag.AlignCenter, text)
            _icon(p, "next", QPointF(box.right() - 18, box.center().y()), 12, QColor("#FFFFFF"))

    def _paint_up_next(self, p: QPainter, r: QRectF, mini: bool) -> None:
        label, secs = self.countdown
        holiday = theme.HOLIDAY
        if mini:
            box = QRectF(r.left() + 8, r.bottom() - 40, r.width() - 16, 30)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.SURFACE_2))
            p.drawRoundedRect(box, 7, 7)
            p.setFont(theme.font(11, QFont.Weight.Bold))
            p.setPen(QColor(theme.TEXT))
            p.drawText(box.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter,
                       f"{'Unwrap' if holiday else 'Up next'}: {label} in {secs} s")
            self._hits["upnext:play"] = box
            return
        box = QRectF(r.right() - 16 - 236, r.bottom() - 92 - 132, 236, 124)
        p.setPen(QPen(QColor("#5A2629" if holiday else theme.BORDER), 1))
        p.setBrush(QColor(theme.SURFACE_2))
        p.drawRoundedRect(box, 10, 10)
        thumb = QRectF(box.left() + 1, box.top() + 1, box.width() - 2, 50)
        clip = QPainterPath()
        clip.addRoundedRect(thumb, 9, 9)
        p.save()
        p.setClipPath(clip)
        p.fillRect(thumb, QColor("#3a2a44"))
        if holiday:                             # wrapped: a ribbon each way and a bow
            p.fillRect(QRectF(thumb.left(), thumb.center().y() - 4, thumb.width(), 8), QColor("#E0403C"))
            p.fillRect(QRectF(thumb.center().x() - 4, thumb.top(), 8, thumb.height()), QColor("#E0403C"))
            p.setFont(theme.font(20))
            p.drawText(QRectF(thumb.center().x() - 16, thumb.top() + 2, 32, 32), Qt.AlignmentFlag.AlignCenter, "🎀")
        p.restore()
        p.setFont(theme.font(10, QFont.Weight.Bold))
        p.setPen(QColor("#6FD39A" if holiday else theme.MUTED))
        p.drawText(QRectF(box.left() + 12, thumb.bottom() + 6, box.width() - 24, 16), Qt.AlignmentFlag.AlignLeft,
                   f"{'Unwrap' if holiday else 'Up next'} in {secs} s")
        p.setFont(theme.font(12, QFont.Weight.DemiBold))
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(box.left() + 12, thumb.bottom() + 22, box.width() - 24, 18), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.next_title or label, Qt.TextElideMode.ElideRight, int(box.width() - 24)))
        p.setFont(theme.font(11, QFont.Weight.Bold))
        play = QRectF(box.left() + 12, box.bottom() - 30, 96, 22)
        cancel = QRectF(play.right() + 8, play.top(), 70, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(play, 6, 6)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(cancel, 6, 6)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(play, Qt.AlignmentFlag.AlignCenter, "Open now" if holiday else "Play now")
        p.drawText(cancel, Qt.AlignmentFlag.AlignCenter, "Cancel")
        self._hits["upnext:play"] = play
        self._hits["upnext:cancel"] = cancel

    def _paint_message(self, p: QPainter, r: QRectF) -> None:
        text = self.message[0]
        p.setFont(theme.font(12, QFont.Weight.Bold))
        w = p.fontMetrics().horizontalAdvance(text) + 28
        box = QRectF(r.center().x() - w / 2, r.top() + 70, w, 30)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 28, 220))
        p.drawRoundedRect(box, 8, 8)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    # -- mouse ------------------------------------------------------------------------------

    def _hit(self, pos: QPointF) -> str:
        for name in ("upnext:play", "upnext:cancel", "skip", "btn:back"):
            if name in self._hits and self._hits[name].contains(pos):
                return name
        if self.alpha > 0.3:
            for name, rect in self._hits.items():
                if name.startswith("btn:") and rect.contains(pos):
                    return name
            if "bar" in self._hits and self._hits["bar"].contains(pos):
                return "bar"
        return ""

    def _seek_at(self, x: float) -> None:
        bar = self._hits.get("bar")
        if bar is None or not self.duration:
            return
        frac = max(0.0, min(1.0, (x - bar.left()) / bar.width()))
        self.position = frac * self.duration
        self.seekTo.emit(self.position)
        self.update()

    def mouseMoveEvent(self, e) -> None:
        self.poke()
        pos = e.position()
        press = getattr(self, "_press", None)
        if press is not None and e.buttons() & Qt.MouseButton.LeftButton:
            delta = e.globalPosition() - press
            if not self._moved and self.mode == "pop" and abs(delta.x()) + abs(delta.y()) > 3:
                # Let macOS move the floating window: as smooth as dragging any window
                handle = self.window().windowHandle()
                if handle is not None and handle.startSystemMove():
                    self._moved = True
                    self._press = None
                    return
            if self._moved or abs(delta.x()) + abs(delta.y()) > 5:
                self._moved = True
                self._press = e.globalPosition()
                self.dragBy.emit(delta)
                return
        self.hover = self._hit(pos)
        self.hover_x = pos.x()
        if self.dragging:
            self._seek_at(pos.x())
        self.setCursor(Qt.CursorShape.PointingHandCursor if self.hover else Qt.CursorShape.ArrowCursor)
        self.update()

    def leaveEvent(self, _e) -> None:
        self.hover = ""
        if self.mode == "pop" and not self.keep_visible():
            self._set_shown(False)             # the floating window shows only the picture until you point at it
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        was_hidden = self.alpha < 0.3
        self.poke()
        if self.parentWidget() is not None:
            self.parentWidget().setFocus()          # keys (space, arrows, F) go to the player
        hit = self._hit(e.position())
        if hit == "bar":
            self.dragging = True
            self._seek_at(e.position().x())
        elif hit.startswith("btn:"):
            self.action.emit(hit[4:])
        elif hit == "skip":
            self.skip.emit()
        elif hit.startswith("upnext:"):
            self.upNext.emit(hit == "upnext:play")
        elif self.mode in ("mini", "pop"):
            self._press = e.globalPosition()           # a drag moves it; a click opens the show (or pauses)
            self._moved = False
        elif not was_hidden:
            self.action.emit("play")         # click the picture: pause / play

    def mouseReleaseEvent(self, _e) -> None:
        self.dragging = False
        if getattr(self, "_press", None) is not None:
            if not self._moved:
                self.action.emit("play" if self.mode == "pop" else "expand")
            elif self.mode == "pop":
                self.action.emit("moved")
            self._press = None

    def mouseDoubleClickEvent(self, e) -> None:
        if self._hit(e.position()):
            return
        if self.mode == "pop":
            self.action.emit("popin")          # double-click the floating video: back into AniGUI
        elif self.mode != "mini":
            self.action.emit("full")


def festive_on(key: str) -> bool:
    """The player's holiday pieces each have their own switch (on unless turned off)."""
    return bool(_prefs.get(key, True))


_prefs: dict[str, bool] = {}


# -- the host -----------------------------------------------------------------------------------------

# -- the pop-out window ---------------------------------------------------------------------

POP_MIN_W = 288
POP_DEFAULT_W = 480


def clamp_to_screen(rect: QRect) -> QRect:
    """Keep the floating video whole on a screen (the one its middle is on)."""
    screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
    if screen is None:
        return rect
    area = screen.availableGeometry()
    w = max(POP_MIN_W, min(rect.width(), area.width()))
    h = round(w * 9 / 16)
    if h > area.height():
        h = area.height()
        w = round(h * 16 / 9)
    x = max(area.left(), min(area.right() - w + 1, rect.x()))
    y = max(area.top(), min(area.bottom() - h + 1, rect.y()))
    return QRect(x, y, w, h)


class PopOutWindow(QWidget):
    """The video in its own small window, above every app (and every Space on a Mac), so you
    can watch while you do something else. Drag it anywhere; pull a corner to resize."""

    closing = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("AniGUI")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setStyleSheet("background: #000000;")
        self.setMinimumSize(POP_MIN_W, round(POP_MIN_W * 9 / 16))
        self.floating = False
        self._settle = QTimer(self, singleShot=True, interval=250)
        self._settle.timeout.connect(self.settled)

    settled = Signal()     # stopped moving: keep it on screen, remember the spot

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        self._settle.start()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self.floating and QGuiApplication.platformName() == "cocoa":   # (a real Mac window)
            self.floating = macwin.float_everywhere(int(self.winId()))

    def closeEvent(self, e) -> None:
        e.ignore()                 # ⌘W: close the player, not just its window
        self.closing.emit()


class _Grip(QWidget):
    """A corner of the pop-out: pull it to resize (the picture stays 16:9)."""

    resized = Signal()

    def __init__(self, corner: tuple[int, int], parent: QWidget) -> None:
        super().__init__(parent)
        self.corner = corner
        self.setFixedSize(16, 16)
        diag = corner in ((1, 1), (-1, -1))
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if diag else Qt.CursorShape.SizeBDiagCursor)
        self._start: tuple[QPointF, QRect] | None = None
        self.pending: QRect | None = None
        self._tick = QTimer(self, singleShot=True, interval=16)   # one resize per frame, at most
        self._tick.timeout.connect(self._apply)

    def _apply(self) -> None:
        if self.pending is not None:
            self.window().setGeometry(self.pending)
            self.pending = None

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._start = (e.globalPosition(), self.window().geometry())

    def mouseMoveEvent(self, e) -> None:
        if self._start is None:
            return
        origin, geo = self._start
        sx, sy = self.corner
        d = e.globalPosition() - origin
        grow = max(d.x() * sx, d.y() * sy * 16 / 9)
        w = max(POP_MIN_W, round(geo.width() + grow))
        h = round(w * 9 / 16)
        x = geo.right() - w + 1 if sx < 0 else geo.left()      # the opposite corner stays put
        y = geo.bottom() - h + 1 if sy < 0 else geo.top()
        self.pending = clamp_to_screen(QRect(x, y, w, h))
        if not self._tick.isActive():
            self._tick.start()

    def mouseReleaseEvent(self, _e) -> None:
        if self._start is not None:
            self._start = None
            self._tick.stop()
            self._apply()
            self.resized.emit()


class PlayerHost(QWidget):
    """Floats above the pages and places the video where it belongs."""

    closed = Signal()
    expandRequested = Signal()       # mini-player clicked: go back to the show
    backRequested = Signal()         # the player's Back
    modeChanged = Signal(str)
    drawerChanged = Signal(bool)     # the episode list opened or closed
    momentSaved = Signal()           # Moments (2.0)

    def __init__(self, ctx, parent: QWidget) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.session = None
        self.video: QWidget | None = None
        self.mode = "hidden"
        self.slot = None                 # callable -> (slot rect, visible rect) in my parent's coords, or None
        self.slot_widget = None          # callable -> the page's video slot (I sit inside it on the show page)
        self.mini_pos: QPointF | None = None
        self.controls = PlayerControls(self)
        self.controls.action.connect(self._action)
        self.controls.seekTo.connect(lambda t: self._cmd("seek", f"{t:.2f}", "absolute"))
        self.controls.skip.connect(self._skip)
        self.controls.upNext.connect(self._up_next)
        self.controls.dragBy.connect(self._drag_mini)
        # The episode list, sliding in over the right of the video (☰ or E)
        self.drawer = QFrame(self, objectName="PlayerDrawer")
        self.drawer.setLayout(QVBoxLayout())
        self.drawer.layout().setContentsMargins(0, 0, 0, 0)
        self.drawer.hide()
        self.drawer_open = False
        self.drawer_close = QPushButton("✕", self.drawer, objectName="DrawerClose",
                                        cursor=Qt.CursorShape.PointingHandCursor)
        self.drawer_close.setToolTip("Close the episode list (E or Esc)")
        self.drawer_close.setFixedSize(30, 30)
        self.drawer_close.clicked.connect(lambda: self.toggle_drawer(False))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.awake = KeepAwake()              # the Mac stays awake while an episode plays
        self._volume = 100.0
        # Sleep timer (2.0): after a while, or at the end of this episode, fade out and pause
        self.sleep_at: float | None = None          # monotonic time it goes off
        self.sleep_after_episode = False
        self._sleep_tick = QTimer(self, interval=1000)
        self._sleep_tick.timeout.connect(self._sleep_check)
        self._fade_steps = 0
        self._fade_from = 100.0
        self._tracks: list[dict] = []
        self._speed = 1.0
        self._was_maximized = False
        self.home = parent                    # where I live when not popped out
        self.popout: PopOutWindow | None = None
        self.grips: list[_Grip] = []
        # A new player starting soon after a popped-out one stopped (dub, another episode)
        # goes straight back out
        self._repop = QTimer(self, singleShot=True, interval=5000)
        self._user_closing = False
        self.hide()
        self._refresh_prefs()
        ctx.events.changed.connect(lambda key, _v: key.startswith("player_") and self._refresh_prefs())

    def _refresh_prefs(self) -> None:
        for key in ("player_lights", "player_snow", "player_bow"):
            _prefs[key] = bool(self.ctx.pref(key, True))
        self.controls.update()

    # -- engine ------------------------------------------------------------------------------

    def start(self, options: dict | None, url: str, tracks: list) -> None:
        """Player.launch's embed hook: make the video (libmpv), or a stand-in for tests."""
        self.stop_engine()
        if options is not None:
            self.video = VideoView(options, url, tracks, self)
            self.video.shutdown.connect(self._engine_shutdown)
        else:
            self.video = Placeholder(self)
        self.video.lower()
        self.controls.raise_()
        self.controls.position = self.controls.duration = None
        self.controls.segments = []
        self.controls.skip_label = None
        self.controls.countdown = None
        if self.mode in ("hidden",):
            self.mode = "pending"
        self.place()
        if self._repop.isActive():
            self._repop.stop()
            self.pop_out()

    def attach(self, session) -> None:
        """The playback session for this video: its control socket drives the controls."""
        if self.session is session:
            return
        self.session = session
        session.ipc.propertyChanged.connect(self._on_property)
        session.ipc.connected.connect(self._observe)
        if session.ipc.is_connected:
            self._observe()
        session.osd.connect(self.controls.show_message)
        session.countdown.connect(self._on_countdown)
        session.ended.connect(self.stop)
        session.episodeChanged.connect(lambda *_: self._new_episode())
        self._new_episode()

    def _observe(self) -> None:
        for name in ("volume", "mute", "track-list", "speed"):
            self.session.ipc.observe(name)

    def _new_episode(self) -> None:
        s = self.session
        if s is None:
            return
        n = s.now
        self.controls.title = f"{n.title} · Episode {n.episode}"
        dub = bool(self.ctx.pref("dub", False))
        self.controls.chip = "DUB" if dub else "SUB"
        self.controls.segments = []
        self.controls.skip_label = None
        self.controls.countdown = None
        self.controls.update()

    def _engine_shutdown(self) -> None:
        if self.session is not None and not self.session.closed:
            self.session.close()
        else:
            self.stop()

    def stop_engine(self) -> None:
        if self.video is not None:
            if isinstance(self.video, VideoView):
                self.video.close_engine()
            self.video.deleteLater()
            self.video = None

    def stop(self) -> None:
        """The session ended (or you closed the player)."""
        self.awake.release()
        set_quiet("video", False)
        self.sleep_at, self.sleep_after_episode = None, False      # (a sleep timer ends with the player)
        self._sleep_tick.stop()
        self.controls.sleep_text = ""
        if self.mode == "full":
            self._leave_full()
        if self.mode == "pop":
            self.pop_in()
            if not self._user_closing:
                self._repop.start()
        self._user_closing = False
        self.stop_engine()
        self.session = None
        self.mode = "hidden"
        self.hide()
        self.closed.emit()

    def close_player(self) -> None:
        self._user_closing = True
        self._repop.stop()
        if self.session is not None and not self.session.closed:
            self.session.close()            # saves; ended → stop()
        else:
            self.stop()

    @property
    def active(self) -> bool:
        return self.video is not None

    # -- the session's properties --------------------------------------------------------------

    def _on_property(self, name: str, value) -> None:
        c = self.controls
        if name == "time-pos" and isinstance(value, (int, float)):
            # This arrives many times a second. Repainting everything over the video each time
            # made the watch page lag (2.0): only the time and bar change, once a second.
            before = (None if c.position is None else int(c.position), c.skip_label, len(c.segments))
            c.position = float(value)
            s = self.session
            seg = s.segment_at(c.position) if s else None
            c.skip_label = seg.kind if seg and seg.kind not in s.now.skipped else None
            c.segments = list(s.now.skips or []) if s else []
            if (c.skip_label, len(c.segments)) != before[1:] or c.countdown is not None:
                c.update()
            elif c.alpha > 0.01 and int(c.position) != before[0]:
                band = 100 if c.mode not in ("mini", "pop") else 40
                c.update(0, max(0, c.height() - band), c.width(), band)
            return
        elif name == "duration" and isinstance(value, (int, float)):
            c.duration = float(value)
        elif name == "pause":
            c.set_paused(value is True)
            if c.paused:
                c.poke()
                self.awake.release()
            else:
                self.awake.hold()
            set_quiet("video", not c.paused)      # decorations hold still while it plays (2.0.1)
        elif name == "mute":
            c.muted = value is True
        elif name == "volume" and isinstance(value, (int, float)):
            self._volume = float(value)
        elif name == "speed" and isinstance(value, (int, float)):
            self._speed = float(value)
        elif name == "track-list" and isinstance(value, list):
            self._tracks = [t for t in value if isinstance(t, dict)]
        else:
            return
        c.update()

    def _on_countdown(self, label: str, seconds: int) -> None:
        if self.sleep_after_episode and self.session is not None:
            self.session.cancel_countdown()        # Sleep timer: this was the last one tonight
            self._sleep_now()
            return
        self.controls.next_title = label
        self.controls.set_countdown(label, seconds)

    def _cmd(self, *args) -> None:
        if self.session is not None:
            self.session.ipc.command(*args)

    def _skip(self) -> None:
        s = self.session
        seg = s.segment_at(self.controls.position) if s else None
        if seg:
            s.skip(seg)
            self.controls.skip_label = None
            self.controls.update()

    def _up_next(self, play: bool) -> None:
        if self.session is None:
            return
        if play:
            self.session.play_next_now()
        else:
            self.session.cancel_countdown()

    # -- buttons and keys -------------------------------------------------------------------------

    def _action(self, name: str) -> None:
        c = self.controls
        if name == "play":
            if self.drawer_open and self.drawer.isVisible():
                self.toggle_drawer(False)          # a click beside the open list closes it
                return
            self._cmd("cycle", "pause")
        elif name == "back10":
            self._cmd("seek", "-10", "relative")
        elif name == "fwd10":
            self._cmd("seek", "10", "relative")
        elif name == "next":
            if c.countdown:
                self._up_next(True)
            else:
                self._play_next()
        elif name == "mute":
            self._cmd("cycle", "mute")
        elif name == "menu":
            self._menu()
        elif name in ("mini", "down"):
            self.set_mode("mini", forced=True)
        elif name == "back":
            if self.mode == "full":
                self.set_mode("theater", forced=True)
            self.backRequested.emit()
        elif name == "list":
            self.toggle_drawer()
        elif name == "expand":
            self.expandRequested.emit()
        elif name == "popout":
            self.pop_out()
        elif name == "popin":
            self.pop_in(show_app=True)
        elif name == "moved":
            self._save_popout()
        elif name == "close":
            self.close_player()
        elif name == "full":
            self.set_mode("theater" if self.mode == "full" else "full", forced=True)

    def _play_next(self) -> None:
        s = self.session
        target = s._next_target() if s else None
        if target is None:
            self.controls.show_message("That's the last episode", 2500)
            return
        s._target = target
        s.play_next_now()

    def keyPressEvent(self, e) -> None:
        key = e.key()
        c = self.controls
        c.poke()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_K):
            self._action("play")
        elif key == Qt.Key.Key_Left:
            self._action("back10")
        elif key == Qt.Key.Key_Right:
            self._action("fwd10")
        elif key == Qt.Key.Key_Up:
            self._cmd("set_property", "volume", min(100.0, self._volume + 5))
        elif key == Qt.Key.Key_Down:
            self._cmd("set_property", "volume", max(0.0, self._volume - 5))
        elif key == Qt.Key.Key_M:
            self._action("mute")
        elif key == Qt.Key.Key_F and self.mode != "pop":
            self._action("full")
        elif key == Qt.Key.Key_P:
            self.pop_in(show_app=True) if self.mode == "pop" else self.pop_out()
        elif key == Qt.Key.Key_B or (key == Qt.Key.Key_S and e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.save_moment()
        elif key == Qt.Key.Key_N:
            self._action("next")
        elif key == Qt.Key.Key_E:
            self.toggle_drawer()
        elif key == Qt.Key.Key_S and c.skip_label:
            self._skip()
        elif key == Qt.Key.Key_Escape:
            if self.drawer_open and self.drawer.isVisible():
                self.toggle_drawer(False)
            elif self.mode == "full":
                self.set_mode("theater", forced=True)
            elif c.countdown:
                self._up_next(False)
            else:
                e.ignore()
                return
        else:
            super().keyPressEvent(e)
            return
        e.accept()

    # -- the menu --------------------------------------------------------------------------------

    def _menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("PlayerMenu")
        audio = menu.addMenu("Audio")
        subs = menu.addMenu("Subtitles")
        for kind, sub in (("audio", audio), ("sub", subs)):
            tracks = [t for t in self._tracks if t.get("type") == kind]
            if kind == "sub":
                off = sub.addAction("Off")
                off.setCheckable(True)
                off.setChecked(not any(t.get("selected") for t in tracks))
                off.triggered.connect(lambda _c=False: self._cmd("set_property", "sid", "no"))
            for t in tracks:
                name = t.get("title") or t.get("lang") or f"Track {t.get('id')}"
                if t.get("lang") and t.get("title") and t["lang"] not in t["title"]:
                    name = f"{t['title']} ({t['lang']})"
                act = sub.addAction(str(name))
                act.setCheckable(True)
                act.setChecked(bool(t.get("selected")))
                prop = "aid" if kind == "audio" else "sid"
                act.triggered.connect(lambda _c=False, i=t.get("id"), p=prop: self._cmd("set_property", p, i))
            if not tracks and kind == "audio":
                sub.addAction("Only one").setEnabled(False)
        sleep = menu.addMenu("Sleep timer")
        for label, value in (("Off", None), ("15 minutes", 15), ("30 minutes", 30), ("45 minutes", 45),
                             ("1 hour", 60), ("End of this episode", "episode")):
            act = sleep.addAction(label)
            act.setCheckable(True)
            on = (value is None and self.sleep_at is None and not self.sleep_after_episode) or \
                 (value == "episode" and self.sleep_after_episode)
            act.setChecked(on)
            act.triggered.connect(lambda _c=False, v=value: self.set_sleep(v))
        speed = menu.addMenu("Speed")
        for value in SPEEDS:
            act = speed.addAction("Normal" if value == 1.0 else f"{value:g}×")
            act.setCheckable(True)
            act.setChecked(abs(value - self._speed) < 0.01)
            act.triggered.connect(lambda _c=False, v=value: self._cmd("set_property", "speed", v))
        sharp = menu.addAction("Sharper picture")
        sharp.setCheckable(True)
        sharp.setChecked(bool(self.ctx.pref("sharper")))
        sharp.setEnabled(sharper.available())
        sharp.toggled.connect(self.set_sharper)
        menu.addSeparator()
        menu.addAction("Save this moment  (B)").triggered.connect(self.save_moment)
        menu.addSeparator()
        auto = menu.addAction("Auto-play next episode")
        auto.setCheckable(True)
        auto.setChecked(bool(self.ctx.pref("autoplay", True)))
        auto.toggled.connect(lambda on: self.ctx.set_pref("autoplay", on))
        if theme.HOLIDAY:
            menu.addSeparator()
            head = menu.addAction("Holiday")
            head.setEnabled(False)
            for key, label in (("player_lights", "Lights"), ("player_snow", "Snow around the player"),
                               ("player_bow", "Bow")):
                act = menu.addAction(label)
                act.setCheckable(True)
                act.setChecked(bool(self.ctx.pref(key, True)))
                act.toggled.connect(lambda on, k=key: self.ctx.set_pref(k, on))
        self.controls.menu_open = True
        menu.aboutToHide.connect(lambda: setattr(self.controls, "menu_open", False))
        gear = self.controls._hits.get("btn:menu")
        at = self.controls.mapToGlobal(gear.topLeft().toPoint()) if gear else QCursor.pos()
        if not getattr(self, "menu_test", False):
            menu.popup(at - QPoint(0, menu.sizeHint().height() + 6))
        self.last_menu = menu
        return menu

    def set_sharper(self, on: bool) -> None:
        """Anime4K on or off, for this episode and the next ones."""
        self.ctx.set_pref("sharper", bool(on))
        self._cmd("set_property", "glsl-shaders", sharper.shaders_value(bool(on)))

    # -- placing ---------------------------------------------------------------------------------

    def set_mode(self, mode: str, forced: bool = False) -> None:
        """theater | mini | full. A forced mini sticks until you go back to the show."""
        if mode == self.mode:
            return
        if self.mode == "pop":
            self.pop_in()
        if self.mode == "full" and mode != "full":
            self._leave_full()
        if mode == "full":
            win = self.window()
            self._was_maximized = win.isMaximized()
            win.showFullScreen()
        self.forced_mini = forced and mode == "mini"
        self.mode = mode
        self.controls.mode = mode
        self.modeChanged.emit(mode)
        self.place()

    def _cover(self, on: bool) -> None:
        """Full screen hides the sidebar and the page under the video. They stop repainting
        meanwhile: otherwise every change to the controls repainted all of them, under the
        video, on every frame (2.0.1)."""
        covered = getattr(self, "_covered", [])
        if on and not covered:
            self._covered = [w for w in self.home.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
                             if w is not self and not w.isWindow() and w.updatesEnabled()]
            for w in self._covered:
                w.setUpdatesEnabled(False)
        elif not on and covered:
            self._covered = []
            for w in covered:
                try:
                    w.setUpdatesEnabled(True)
                    w.update()
                except RuntimeError:       # (deleted meanwhile)
                    pass

    def _leave_full(self) -> None:
        self._cover(False)
        win = self.window()
        if win.isFullScreen():
            win.showMaximized() if self._was_maximized else win.showNormal()
        self.controls.unsetCursor()

    def place(self) -> None:
        """Put the video where it belongs right now."""
        if self.video is None:
            self.hide()
            return
        if self.mode == "pop" and self.popout is not None:
            inner = self.popout.rect()
            self.setGeometry(inner)
            self.video.setGeometry(inner)
            self.controls.setGeometry(inner)
            self.controls.mode = "pop"
            self.drawer.hide()
            for g in self.grips:
                sx, sy = g.corner
                g.move(inner.right() - g.width() + 1 if sx > 0 else 0, inner.bottom() - g.height() + 1 if sy > 0 else 0)
                g.show()
                g.raise_()
            self.show()
            self.video.show()
            return
        for g in self.grips:
            g.hide()
        parent = self.home
        target = None
        slot = self.slot() if self.slot else None
        if self.mode == "full":
            target = parent.rect()
        elif slot is not None and not getattr(self, "forced_mini", False):
            rect, visible = slot
            shown = rect.intersected(visible)
            if shown.height() >= rect.height() * 0.35:
                self._set_mode_quiet("theater")
                target = rect
        if target is None and self.mode != "full":
            self._set_mode_quiet("mini")
            area = parent.rect()
            w, h = MINI_W, MINI_H
            if self.mini_pos is None:
                x, y = area.right() - w - 24, area.bottom() - h - 24
            else:
                x = max(area.left() + 8, min(area.right() - w - 8, self.mini_pos.x()))
                y = max(area.top() + 8, min(area.bottom() - h - 8, self.mini_pos.y()))
            target = QRect(int(x), int(y), w, h)
        self._cover(self.mode == "full")
        holder = self.slot_widget() if (self.mode == "theater" and self.slot_widget) else None
        if holder is not None:
            # On the show page the video is part of the page (inside its slot), so it scrolls
            # with it and nothing floats over the page: scrolling can reuse what's drawn (2.0)
            moved = self._move_to(holder)
            target = holder.rect()
        else:
            moved = self._move_to(self.home)
        inner = QRect(0, 0, target.width(), target.height())
        self.setGeometry(target)
        self.video.setGeometry(inner)
        self.controls.setGeometry(inner)
        self.controls.mode = self.mode
        self._place_drawer(inner)
        if moved or self.isHidden():
            self.show()
            self.raise_()
            self.video.show()

    def _move_to(self, parent: QWidget) -> bool:
        if self.parentWidget() is parent:
            return False
        self._reparent(parent)
        return True

    def _reparent(self, parent: QWidget) -> None:
        """Move the player (page, window corner, pop-out). Let go of the keyboard first: Qt
        would hand it to the next thing on the page and scroll the page to show it."""
        fw = QApplication.focusWidget()
        had = fw is not None and (fw is self or self.isAncestorOf(fw))
        if had:
            fw.clearFocus()
        self.setParent(parent)
        if had:
            self.setFocus()

    def _set_mode_quiet(self, mode: str) -> None:
        if self.mode != mode:
            self.mode = mode
            self.controls.mode = mode
            self.modeChanged.emit(mode)

    # -- the episode drawer --------------------------------------------------------------

    def set_drawer_content(self, widget: QWidget) -> None:
        """The show page's episode list lives here while the video plays."""
        if widget.parentWidget() is not self.drawer:
            self.drawer.layout().addWidget(widget)
        widget.show()

    def toggle_drawer(self, on: bool | None = None) -> None:
        was = self.drawer_open
        self.drawer_open = (not self.drawer_open) if on is None else bool(on)
        self.place()
        if self.drawer_open != was:
            self.drawerChanged.emit(self.drawer_open)
            if not self.drawer_open:
                self.setFocus()

    def _place_drawer(self, inner: QRect) -> None:
        show = self.drawer_open and self.mode in ("theater", "full") and self.drawer.layout().count() > 0
        if show:
            w = min(320, max(240, int(inner.width() * 0.34)))
            self.drawer.setGeometry(inner.right() - w + 1, inner.top(), w, inner.height())
            self.drawer.raise_()
            self.drawer_close.move(w - self.drawer_close.width() - 34, 12)    # (clear of the holiday bow)
            self.drawer_close.raise_()
        self.drawer.setVisible(show)

    def _drag_mini(self, delta: QPointF) -> None:
        if self.mode == "pop" and self.popout is not None:
            geo = self.popout.geometry()
            self.popout.setGeometry(clamp_to_screen(geo.translated(int(delta.x()), int(delta.y()))))
            return
        if self.mode != "mini":
            return
        self.mini_pos = QPointF(self.pos()) + delta
        self.place()

    # -- the pop-out window ------------------------------------------------------------------

    def pop_out(self) -> None:
        """Move the video into its own floating window."""
        if self.video is None or self.mode == "pop":
            return
        if self.mode == "full":
            self._leave_full()
        if self.popout is None:
            self.popout = PopOutWindow()
            self.destroyed.connect(self.popout.deleteLater)     # (it has no parent to go with)
            self.popout.closing.connect(self.close_player)
            self.popout.settled.connect(self._settled)
            self.grips = [_Grip(c, self) for c in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            for g in self.grips:
                g.resized.connect(self._save_popout)
            self.popout.installEventFilter(self)
        self.popout.setGeometry(self._popout_rect())
        self._reparent(self.popout)
        self.drawer_open = False
        self._set_mode_quiet("pop")
        self.popout.show()
        self.place()
        self.setFocus()
        self.controls.poke()

    def pop_in(self, show_app: bool = False) -> None:
        """Back into AniGUI's window (where it was: the show page, or the corner)."""
        if self.mode != "pop":
            return
        self._repop.stop()
        self._save_popout()
        self._reparent(self.home)
        for g in self.grips:
            g.hide()
        self.mode = "pending"
        self.forced_mini = False
        if self.popout is not None:
            self.popout.hide()
        self.place()
        if self.mode == "pending":
            self._set_mode_quiet("mini")
        if show_app:
            win = self.home.window()
            win.showNormal() if win.isMinimized() else None
            win.raise_()
            win.activateWindow()
            self.expandRequested.emit()

    def _popout_rect(self) -> QRect:
        saved = self.ctx.pref("popout_rect")
        if isinstance(saved, (list, tuple)) and len(saved) == 3:
            x, y, w = (int(v) for v in saved)
            return clamp_to_screen(QRect(x, y, w, round(w * 9 / 16)))
        screen = QGuiApplication.screenAt(self.home.window().geometry().center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1440, 900)
        w = POP_DEFAULT_W
        h = round(w * 9 / 16)
        return clamp_to_screen(QRect(area.right() - w - 24, area.bottom() - h - 24, w, h))

    def _settled(self) -> None:
        if self.mode != "pop" or self.popout is None:
            return
        geo = self.popout.geometry()
        fixed = clamp_to_screen(geo)
        if fixed != geo:
            self.popout.setGeometry(fixed)      # dropped partly off screen: slide back on
        self._save_popout()

    def _save_popout(self) -> None:
        if self.popout is not None and self.popout.isVisible():
            g = self.popout.geometry()
            self.ctx.set_pref("popout_rect", [g.x(), g.y(), g.width()])

    def eventFilter(self, obj, event) -> bool:
        if obj is self.popout and event.type() == QEvent.Type.Resize and self.mode == "pop":
            self.place()
        return False

    # -- sleep timer (2.0) -----------------------------------------------------------------

    def set_sleep(self, value) -> None:
        """None: off. A number: minutes. "episode": at the end of this episode."""
        self.sleep_after_episode = value == "episode"
        self.sleep_at = time.monotonic() + float(value) * 60 if isinstance(value, (int, float)) else None
        if self.sleep_at is not None or self.sleep_after_episode:
            self._sleep_tick.start()
            self.controls.show_message("Sleep timer: " + ("at the end of this episode" if self.sleep_after_episode
                                                          else f"{int(value)} minutes"), 2000)
        else:
            self._sleep_tick.stop()
            self.controls.show_message("Sleep timer off", 1500)
        self._sleep_check()

    def _sleep_check(self) -> None:
        c = self.controls
        if self.sleep_after_episode:
            c.sleep_text = "end of episode"
        elif self.sleep_at is not None:
            left = self.sleep_at - time.monotonic()
            if left <= 0:
                self._sleep_now()
                return
            c.sleep_text = f"{int(left // 60) + 1} min" if left >= 60 else f"{int(left)} s"
        else:
            c.sleep_text = ""
        c.update()

    def _sleep_now(self) -> None:
        """Fade the sound out over a few seconds, then pause."""
        self.sleep_at = None
        self.sleep_after_episode = False
        self._sleep_tick.stop()
        self.controls.sleep_text = ""
        self._fade_from = self._volume
        self._fade_steps = 8
        self._fade_down()

    def _fade_down(self) -> None:
        if self.session is None:
            return
        if self._fade_steps > 0:
            self._fade_steps -= 1
            self._cmd("set_property", "volume", self._fade_from * self._fade_steps / 8)
            QTimer.singleShot(600, self._fade_down)
            return
        self._cmd("set_property", "pause", True)
        self._cmd("set_property", "volume", self._fade_from)
        self.controls.show_message("Sweet dreams ❄  Paused by the sleep timer" if theme.HOLIDAY
                                   else "Good night ☾  Paused by the sleep timer", 6000)

    # -- Moments (2.0) ---------------------------------------------------------------------

    def save_moment(self) -> int | None:
        """Keep this frame and the time: Library → Moments takes you back to it."""
        s = self.session
        if s is None or self.controls.position is None:
            return None
        from core import paths

        n = s.now
        folder = paths.data_dir() / "Moments"
        folder.mkdir(parents=True, exist_ok=True)
        pos = float(self.controls.position)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in n.anime_id)[:60]
        image = folder / f"{safe}-ep{n.episode}-{int(pos)}-{int(time.time())}.jpg"
        self._cmd("screenshot-to-file", str(image), "video")
        moment = self.ctx.store.add_moment(n.anime_id, n.episode, pos, str(image))
        self.controls.show_message(("❄  " if theme.HOLIDAY else "✨  ") + "Moment saved: Library → Moments", 2200)
        self.momentSaved.emit()
        return moment
