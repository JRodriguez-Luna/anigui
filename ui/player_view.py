"""The built-in player: video inside AniGUI's window.

PlayerHost floats above the pages. On the playing show's page it sits exactly over the
page's video slot (the theater, with the episode list beside it); anywhere else it shrinks
to a mini-player in the corner; F makes it fill the screen. The video comes from libmpv
(VideoView). Everything else talks to mpv through the same control socket the external
players use, so progress, skips and auto-play work exactly as before (ui/playback.Session).
"""

from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu, QWidget

from core import libmpv

from . import festive, theme
from .motion import reduce_motion

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
        self.mpv = libmpv.Mpv(options)          # opens the control socket right away
        self.url, self.tracks = url, list(tracks)
        self.renderer: libmpv.GlRenderer | None = None
        self.frameReady.connect(self.update, Qt.ConnectionType.QueuedConnection)
        self.wakeup.connect(self._drain, Qt.ConnectionType.QueuedConnection)
        self.mpv.on_wakeup(self.wakeup.emit)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def initializeGL(self) -> None:
        if self.renderer is None and self.mpv.handle:
            self.renderer = libmpv.GlRenderer(self.mpv, libmpv.gl_proc_address())
            self.renderer.on_update(self.frameReady.emit)
            if self.url:
                self.mpv.command("loadfile", self.url)   # only now: mpv needs somewhere to draw
                self.url = ""

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
        wanted = paused and theme.HOLIDAY and festive_on("player_snow") and self.mode != "mini"
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
        if self.keep_visible() or (self.underMouse() and self.mode == "mini"):
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
        mini = self.mode == "mini"
        if theme.HOLIDAY and self.mode != "full":
            self._snow_cap(p, r)
        if self.flakes:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 210))
            for x, y, rad, _v, _d in self.flakes:
                p.drawEllipse(QPointF(x, y), rad, rad)
        a = self.alpha
        if a > 0.01:
            p.save()
            p.setOpacity(a)
            self._paint_controls(p, r, mini)
            p.restore()
        if self.skip_label and not mini:
            self._paint_skip(p, r)
        if self.countdown is not None:
            self._paint_up_next(p, r, mini)
        if self.message and not mini:
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
            self._button(p, "expand", QPointF(r.left() + 18, r.top() + 20 + cap / 2), 16, white)
            self._button(p, "close", QPointF(r.right() - 18, r.top() + 20 + cap / 2), 14, white)
            self._button(p, "play", r.center(), 34, white, "pause" if not self.paused else "play", circle=True)
        else:
            self._button(p, "down", QPointF(r.left() + pad + 8, r.top() + 24 + cap), 18, white)
            p.setFont(theme.font(13, QFont.Weight.DemiBold))
            p.setPen(white)
            title_rect = QRectF(r.left() + pad + 26, r.top() + 12 + cap, r.width() - 2 * pad - 110, 24)
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
        x = r.right() - pad - 10
        for name, icon in (("full", "unfull" if self.mode == "full" else "full"), ("mini", "pip"), ("menu", "gear")):
            self._button(p, name, QPointF(x, y), 20, white, icon)
            x -= 40

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
        for name in ("upnext:play", "upnext:cancel", "skip"):
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
        elif self.mode == "mini":
            self._press = e.globalPosition()           # a drag moves it, a click opens the show
            self._moved = False
        elif not was_hidden:
            self.action.emit("play")         # click the picture: pause / play

    def mouseReleaseEvent(self, _e) -> None:
        self.dragging = False
        if getattr(self, "_press", None) is not None:
            if not self._moved:
                self.action.emit("expand")
            self._press = None

    def mouseDoubleClickEvent(self, e) -> None:
        if not self._hit(e.position()) and self.mode != "mini":
            self.action.emit("full")


def festive_on(key: str) -> bool:
    """The player's holiday pieces each have their own switch (on unless turned off)."""
    return bool(_prefs.get(key, True))


_prefs: dict[str, bool] = {}


# -- the host -----------------------------------------------------------------------------------------

class PlayerHost(QWidget):
    """Floats above the pages and places the video where it belongs."""

    closed = Signal()
    expandRequested = Signal()       # mini-player clicked: go back to the show
    modeChanged = Signal(str)

    def __init__(self, ctx, parent: QWidget) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.session = None
        self.video: QWidget | None = None
        self.mode = "hidden"
        self.slot = None                 # callable -> (slot rect, visible rect) in my parent's coords, or None
        self.mini_pos: QPointF | None = None
        self.controls = PlayerControls(self)
        self.controls.action.connect(self._action)
        self.controls.seekTo.connect(lambda t: self._cmd("seek", f"{t:.2f}", "absolute"))
        self.controls.skip.connect(self._skip)
        self.controls.upNext.connect(self._up_next)
        self.controls.dragBy.connect(self._drag_mini)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._volume = 100.0
        self._tracks: list[dict] = []
        self._speed = 1.0
        self._was_maximized = False
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
        if self.mode == "full":
            self._leave_full()
        self.stop_engine()
        self.session = None
        self.mode = "hidden"
        self.hide()
        self.closed.emit()

    def close_player(self) -> None:
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
            c.position = float(value)
            s = self.session
            seg = s.segment_at(c.position) if s else None
            c.skip_label = seg.kind if seg and seg.kind not in s.now.skipped else None
            c.segments = list(s.now.skips or []) if s else []
        elif name == "duration" and isinstance(value, (int, float)):
            c.duration = float(value)
        elif name == "pause":
            c.set_paused(value is True)
            if c.paused:
                c.poke()
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
        elif name == "expand":
            self.expandRequested.emit()
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
        elif key == Qt.Key.Key_F:
            self._action("full")
        elif key == Qt.Key.Key_N:
            self._action("next")
        elif key == Qt.Key.Key_S and c.skip_label:
            self._skip()
        elif key == Qt.Key.Key_Escape:
            if self.mode == "full":
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
        speed = menu.addMenu("Speed")
        for value in SPEEDS:
            act = speed.addAction("Normal" if value == 1.0 else f"{value:g}×")
            act.setCheckable(True)
            act.setChecked(abs(value - self._speed) < 0.01)
            act.triggered.connect(lambda _c=False, v=value: self._cmd("set_property", "speed", v))
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

    # -- placing ---------------------------------------------------------------------------------

    def set_mode(self, mode: str, forced: bool = False) -> None:
        """theater | mini | full. A forced mini sticks until you go back to the show."""
        if mode == self.mode:
            return
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

    def _leave_full(self) -> None:
        win = self.window()
        if win.isFullScreen():
            win.showMaximized() if self._was_maximized else win.showNormal()
        self.controls.unsetCursor()

    def place(self) -> None:
        """Put the video where it belongs right now."""
        if self.video is None:
            self.hide()
            return
        parent = self.parentWidget()
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
                clip = shown
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
        if self.mode == "theater":
            # Clip to the page's visible area: the part scrolled away isn't drawn
            self.setGeometry(clip)
            inner = QRect(target.left() - clip.left(), target.top() - clip.top(), target.width(), target.height())
        else:
            self.setGeometry(target)
            inner = QRect(0, 0, target.width(), target.height())
        self.video.setGeometry(inner)
        self.controls.setGeometry(inner)
        self.controls.mode = self.mode
        self.show()
        self.raise_()
        self.video.show()

    def _set_mode_quiet(self, mode: str) -> None:
        if self.mode != mode:
            self.mode = mode
            self.controls.mode = mode
            self.modeChanged.emit(mode)

    def _drag_mini(self, delta: QPointF) -> None:
        if self.mode != "mini":
            return
        self.mini_pos = QPointF(self.pos()) + delta
        self.place()
