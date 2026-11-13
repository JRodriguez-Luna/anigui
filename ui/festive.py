"""Holiday touches that paint over or inside existing pieces: candy-cane progress bars, snow
caps on posters, gift-tag badges, ornament dots, sidebar lights, the countdown chip, the
sweater band, a snow flurry, Santa's sleigh, and New Year's fireworks.

Everything checks theme.HOLIDAY (painters) or is shown only while it's on (widgets), and
nothing moves with Reduce motion.
"""

from __future__ import annotations

import datetime as dt
import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QWidget

from . import theme
from .motion import holding_still, park, reduce_motion

LIGHTS = ("#FF5A5A", "#FFD54A", "#4FD18B", "#5AB4FF", "#FF8AD8")
CANE_RED, CANE_WHITE = "#E0403C", "#F4F4F4"
SNOW = QColor("#F4F7FA")


# -- painters (used by the card, episode and season delegates) -----------------------------------

def progress_bar(p: QPainter, bar: QRectF, fraction: float, color: str) -> None:
    """The watch-progress fill: candy-cane stripes during the holidays, the accent otherwise."""
    fill = QRectF(bar.left(), bar.top(), bar.width() * max(0.0, min(1.0, fraction)), bar.height())
    if not theme.HOLIDAY:
        p.fillRect(fill, QColor(color))
        return
    p.save()
    p.setClipRect(fill)
    p.fillRect(fill, QColor(CANE_WHITE))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(CANE_RED))
    step = 8.0
    x = fill.left() - fill.height()
    while x < fill.right() + step:
        stripe = QPainterPath()
        stripe.moveTo(x, fill.bottom())
        stripe.lineTo(x + step / 2, fill.bottom())
        stripe.lineTo(x + step / 2 + fill.height(), fill.top())
        stripe.lineTo(x + fill.height(), fill.top())
        stripe.closeSubpath()
        p.drawPath(stripe)
        x += step
    p.restore()


def snow_cap(p: QPainter, poster: QRectF) -> None:
    """A little snow resting on top of a poster."""
    if not theme.HOLIDAY:
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(SNOW)
    l, t, w = poster.left() - 2, poster.top() - 4, poster.width() + 4
    cap = QPainterPath()
    cap.moveTo(l + 6, t + 3)
    cap.quadTo(l + w * 0.25, t - 2, l + w * 0.5, t + 1)
    cap.quadTo(l + w * 0.75, t - 3, l + w - 6, t + 2)
    cap.quadTo(l + w + 1, t + 4, l + w - 1, t + 9)
    # the drips along the front edge
    cap.quadTo(l + w * 0.82, t + 12, l + w * 0.7, t + 9)
    cap.quadTo(l + w * 0.6, t + 8, l + w * 0.52, t + 10)
    cap.quadTo(l + w * 0.44, t + 17, l + w * 0.36, t + 10)
    cap.quadTo(l + w * 0.2, t + 8, l + w * 0.12, t + 10)
    cap.quadTo(l - 1, t + 11, l + 1, t + 6)
    cap.closeSubpath()
    p.drawPath(cap)
    p.restore()


def gift_tag(p: QPainter, rect: QRectF, text: str) -> None:
    """A red gift tag with a notch and a hole (holiday NEW badges)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    tag = QPainterPath()
    n = rect.height() / 2
    tag.moveTo(rect.left() + n, rect.top())
    tag.lineTo(rect.right() - 3, rect.top())
    tag.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + 3)
    tag.lineTo(rect.right(), rect.bottom() - 3)
    tag.quadTo(rect.right(), rect.bottom(), rect.right() - 3, rect.bottom())
    tag.lineTo(rect.left() + n, rect.bottom())
    tag.lineTo(rect.left(), rect.center().y())
    tag.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(CANE_RED))
    p.drawPath(tag)
    p.setBrush(QColor(255, 255, 255, 220))
    p.drawEllipse(QPointF(rect.left() + n * 0.9, rect.center().y()), 2, 2)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(rect.adjusted(n + 2, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
    p.restore()


def ornament(p: QPainter, center: QPointF, r: float, lit: bool) -> None:
    """A round bauble with a gold cap (the Home banner's dots)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#C9A227") if lit else QColor(255, 255, 255, 70))
    p.drawRoundedRect(QRectF(center.x() - r * 0.35, center.y() - r - 2.5, r * 0.7, 3), 1, 1)
    p.setBrush(QColor(theme.ACCENT) if lit else QColor(255, 255, 255, 80))
    p.drawEllipse(center, r, r)
    if lit:
        p.setBrush(QColor(255, 255, 255, 110))
        p.drawEllipse(QPointF(center.x() - r * 0.35, center.y() - r * 0.35), r * 0.25, r * 0.25)
    p.restore()


def christmas_tag(p: QPainter, rect: QRectF) -> None:
    """'🎄 Christmas episode' chip on an episode card."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setFont(theme.font(10, QFont.Weight.Bold))
    text = "🎄 Christmas episode"
    w = p.fontMetrics().horizontalAdvance(text) + 14
    chip = QRectF(rect.left() + 8, rect.top() + 8, w, 18)
    p.setPen(QPen(QColor("#2E5A40"), 1))
    p.setBrush(QColor("#12261C"))
    p.drawRoundedRect(chip, 9, 9)
    p.setPen(QColor("#BFE9CF"))
    p.drawText(chip, Qt.AlignmentFlag.AlignCenter, text)
    p.restore()


# -- sidebar ----------------------------------------------------------------------------------------

class SidebarLights(QWidget):
    """A string of twinkling lights along the top of the sidebar."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.t = 0.0
        self._timer = QTimer(self, interval=80)
        self._timer.timeout.connect(self._step)
        self.setFixedHeight(22)
        self.hide()

    def set_on(self, on: bool) -> None:
        self.setVisible(on)
        if on:
            self.setGeometry(0, 0, self.parentWidget().width(), 22)
            self.raise_()
            if not reduce_motion():
                self._timer.start()
        else:
            self._timer.stop()

    def _step(self) -> None:
        if park(self._timer, self) or holding_still():
            return
        self.t += 0.08
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        wire = QPainterPath()
        wire.moveTo(-6, 3)
        wire.quadTo(w / 2, 17, w + 6, 3)
        p.setPen(QPen(QColor("#3B4A3F"), 1.5))
        p.drawPath(wire)
        p.setPen(Qt.PenStyle.NoPen)
        n = max(6, w // 24)
        for i in range(n):
            u = (i + 0.5) / n
            x = -6 + (w + 12) * u
            y = (1 - u) ** 2 * 3 + 2 * (1 - u) * u * 17 + u ** 2 * 3
            c = QColor(LIGHTS[i % len(LIGHTS)])
            if self._timer.isActive():
                c.setAlphaF(max(0.35, 0.6 + 0.4 * math.sin(self.t * 2.3 + i * 1.7)))
            p.setBrush(QColor("#5A5A5A"))
            p.drawRect(QRectF(x - 1.5, y, 3, 2.5))
            p.setBrush(c)
            p.drawEllipse(QRectF(x - 3, y + 2, 6, 8.5))
        p.end()


def countdown_text(today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    christmas = dt.date(today.year, 12, 25)
    if today.month == 1 and today.day == 1:
        return f"✨ Happy New Year {today.year}!"
    if today == christmas:
        return "🎄 Merry Christmas!"
    if today == christmas - dt.timedelta(days=1):
        return "🎄 Christmas is tomorrow!"
    if today > christmas:
        return "❄ Happy holidays"
    days = (christmas - today).days
    return f"🎄 {days} days to Christmas"


class CountdownChip(QLabel):
    """'🎄 22 days to Christmas' at the bottom of the sidebar. Click it for a snow flurry."""

    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("", parent, objectName="Countdown")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Let it snow")
        self.hide()

    def refresh(self, today: dt.date | None = None) -> None:
        self.setText(countdown_text(today))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


# -- the Stats page's sweater band ----------------------------------------------------------------

class SweaterBand(QWidget):
    """A knitted Christmas-sweater pattern behind the Stats title."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(64)
        self.clear_left = 0          # room kept plain for the title
        self.hide()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(r, 12, 12)
        p.setClipPath(clip)
        p.fillRect(r, QColor("#8E1F22"))
        white, green = QColor(CANE_WHITE), QColor("#2E7D4F")
        p.setPen(QPen(white, 3))
        for x in range(-14, int(r.width()) + 28, 28):
            p.drawPolyline([QPointF(x, 9), QPointF(x + 7, 3), QPointF(x + 14, 9), QPointF(x + 21, 3), QPointF(x + 28, 9)])
        p.setPen(QPen(green, 3))
        for x in range(-14, int(r.width()) + 28, 28):
            y = r.height() - 9
            p.drawPolyline([QPointF(x, y), QPointF(x + 7, y + 6), QPointF(x + 14, y), QPointF(x + 21, y + 6),
                            QPointF(x + 28, y)])
        p.setPen(Qt.PenStyle.NoPen)
        for i, x in enumerate(range(14, int(r.width()), 56)):
            cy = r.height() / 2
            if x < self.clear_left:
                continue
            if i % 2 == 0:                       # a snowflake-ish diamond
                d = QPainterPath()
                d.moveTo(x, cy - 9)
                d.lineTo(x + 7, cy)
                d.lineTo(x, cy + 9)
                d.lineTo(x - 7, cy)
                d.closeSubpath()
                p.setBrush(white)
                p.drawPath(d)
                p.setBrush(green)
                p.drawEllipse(QPointF(x, cy), 2.2, 2.2)
            else:                                # a little tree
                t = QPainterPath()
                t.moveTo(x, cy - 10)
                t.lineTo(x + 8, cy + 7)
                t.lineTo(x - 8, cy + 7)
                t.closeSubpath()
                p.setBrush(green)
                p.drawPath(t)
                p.setBrush(white)
                p.drawRect(QRectF(x - 1.5, cy + 7, 3, 3))
        p.end()


# -- overlays: flurry, sleigh, fireworks -------------------------------------------------------------

class _Overlay(QWidget):
    """A transparent layer over a widget for a few seconds."""

    def __init__(self, host: QWidget, frame_ms: int = 30) -> None:
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setGeometry(host.rect())
        self._timer = QTimer(self, interval=frame_ms)
        self._timer.timeout.connect(self._frame)
        self.hide()

    def play(self) -> bool:
        if reduce_motion():
            return False
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self._timer.start()
        return True

    def finish(self) -> None:
        self._timer.stop()
        self.hide()

    def _frame(self) -> None:
        if not self.step():
            self.finish()
        self.update()

    def step(self) -> bool:            # False when done
        return False


class Flurry(_Overlay):
    """A quick burst of snow over the whole window (click the countdown chip). It goes by the
    clock, not by frames, so it's over in a few seconds even on a busy Mac."""

    SECONDS = 4.5          # at most; the last half second fades out

    def __init__(self, host: QWidget) -> None:
        super().__init__(host, 16)
        self.flakes: list[list[float]] = []
        self.started = self.last = 0.0
        self.alpha = 1.0

    def play(self) -> bool:
        w, h = max(1, self.parentWidget().width()), max(1, self.parentWidget().height())
        # x, y, radius, speed (px/s: crosses the window in 2.2-4 s), sway phase
        self.flakes += [[random.uniform(0, w), random.uniform(-120, -4), random.uniform(1.2, 3.0),
                         (h + 130) / random.uniform(2.2, 4.0), random.uniform(0, 6.3)] for _ in range(160)]
        self.started = self.last = time.monotonic()
        self.alpha = 1.0
        return super().play()

    def step(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        dt, self.last = min(0.1, max(0.0, now - self.last)), now
        h = self.height()
        for f in self.flakes:
            f[1] += f[3] * dt
            f[4] += 3.0 * dt
            f[0] += math.sin(f[4]) * 48 * dt
        self.flakes = [f for f in self.flakes if f[1] < h + 6]
        age = now - self.started
        self.alpha = max(0.0, min(1.0, (self.SECONDS - age) / 0.5))
        if age >= self.SECONDS:
            self.flakes = []
        return bool(self.flakes)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, int(225 * self.alpha)))
        for x, y, r, _s, _d in self.flakes:
            p.drawEllipse(QPointF(x, y), r, r)
        p.end()


class Sleigh(_Overlay):
    """Santa's sleigh across the Home banner (once a day)."""

    TEXT = "🦌 🦌 🛷🎅"
    SECONDS = 5.0

    def __init__(self, host: QWidget) -> None:
        super().__init__(host, 30)
        self.t = 0.0
        self.font_ = theme.font(26)

    def play(self) -> bool:
        self.t = 0.0
        return super().play()

    def step(self) -> bool:
        self.t += 0.03 / self.SECONDS
        return self.t < 1.0

    def position(self) -> QPointF:
        w, h = self.width(), self.height()
        x = w + 40 - (w + 320) * self.t          # right to left: the reindeer face left, so they lead
        y = h * 0.16 + h * 0.08 * math.sin(self.t * math.pi * 2) - h * 0.06 * self.t
        return QPointF(x, y)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(self.font_)
        pos = self.position()
        end = pos.x() + p.fontMetrics().horizontalAdvance(self.TEXT)
        # a short sparkle trail behind the sleigh
        for k in range(6):
            q = QPointF(end + 12 + k * 16, pos.y() + 14 + math.sin((self.t * 40) + k) * 3)
            c = QColor("#FFD54A")
            c.setAlphaF(max(0.0, 0.7 - k * 0.12))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(q, 2.0, 2.0)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(pos.x(), pos.y() - 20, 260, 40), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.TEXT)
        p.end()


class Fireworks(_Overlay):
    """New Year's fireworks with 'Happy New Year 2027' (about seven seconds)."""

    def __init__(self, host: QWidget) -> None:
        super().__init__(host, 30)
        self.sparks: list[list] = []
        self.frames = 0
        self.year = dt.date.today().year
        self.title_font = theme.font(34, QFont.Weight.Bold)

    def play(self, year: int | None = None) -> bool:
        self.year = year or dt.date.today().year
        self.frames = 0
        self.sparks = []
        return super().play()

    def burst(self) -> None:
        w, h = self.width(), self.height()
        cx, cy = random.uniform(w * 0.15, w * 0.85), random.uniform(h * 0.12, h * 0.45)
        color = random.choice(LIGHTS + ("#FFFFFF",))
        for i in range(48):
            a = math.tau * i / 48
            v = random.uniform(2.0, 4.6)
            self.sparks.append([cx, cy, math.cos(a) * v, math.sin(a) * v, 70, color])

    def step(self) -> bool:
        self.frames += 1
        if self.frames < 180 and self.frames % 14 == 1:
            self.burst()
        for s in self.sparks:
            s[0] += s[2]
            s[1] += s[3]
            s[3] += 0.05
            s[2] *= 0.985
            s[4] -= 1
        self.sparks = [s for s in self.sparks if s[4] > 0]
        return self.frames < 240 or bool(self.sparks)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fade = min(1.0, self.frames / 20) * (1.0 if self.frames < 200 else max(0.0, 1 - (self.frames - 200) / 40))
        p.fillRect(self.rect(), QColor(5, 5, 12, int(150 * fade)))
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, _vx, _vy, life, color in self.sparks:
            c = QColor(color)
            c.setAlphaF(max(0.0, life / 70))
            p.setBrush(c)
            p.drawEllipse(QPointF(x, y), 2.0, 2.0)
        p.setFont(self.title_font)
        c = QColor("#FFFFFF")
        c.setAlphaF(fade)
        p.setPen(c)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"Happy New Year {self.year} ✨")
        p.end()


class BowPop(_Overlay):
    """A bow that pops out of the My List button when you add a show."""

    MS = 760

    def __init__(self, host: QWidget) -> None:
        super().__init__(host, 16)
        self.t = 0.0
        self.at = QPointF()

    def pop(self, at: QPointF) -> bool:
        self.at = QPointF(at)
        self.t = 0.0
        return self.play()

    def step(self) -> bool:
        self.t += 16 / self.MS
        return self.t < 1.0

    def scale(self) -> float:
        """Springs up past full size, then settles."""
        t = min(1.0, self.t)
        if t < 0.35:
            return 1.25 * (t / 0.35)
        return 1.25 - 0.25 * min(1.0, (t - 0.35) / 0.25)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = min(1.0, self.t)
        p.setOpacity(1.0 if t < 0.7 else max(0.0, 1 - (t - 0.7) / 0.3))
        s = self.scale()
        p.translate(self.at.x(), self.at.y() - 26 * t)
        p.scale(s, s)
        p.setFont(theme.font(26))
        p.drawText(QRectF(-24, -24, 48, 48), Qt.AlignmentFlag.AlignCenter, "🎀")
        p.end()


# -- Christmas Day ----------------------------------------------------------------------------------

def first_name() -> str:
    """The first word of the Mac account's full name ('' if there isn't one)."""
    try:
        import os
        import pwd
        full = (pwd.getpwuid(os.getuid()).pw_gecos or "").split(",")[0].strip()
    except (ImportError, KeyError, OSError):
        return ""
    return full.split()[0] if full else ""


def greeting_lines(name: str, seconds_this_year: float, year: int) -> tuple[str, str]:
    from core.stats import hours_text
    title = f"Merry Christmas, {name}! 🎄" if name else "Merry Christmas! 🎄"
    if seconds_this_year >= 60:
        body = (f"You've watched {hours_text(seconds_this_year)} of anime in {year}. "
                "Thanks for spending some of it here. Enjoy the day!")
    else:
        body = "Thanks for being here this year. Enjoy the day!"
    return title, body


class ChristmasCard(QWidget):
    """Once, on Christmas Day: a card over the window."""

    closed = Signal()

    def __init__(self, host: QWidget) -> None:
        from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("ChristmasScrim")
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.card = QFrame(objectName="ChristmasCard")
        self.card.setFixedWidth(440)
        col = QVBoxLayout(self.card)
        col.setContentsMargins(30, 28, 30, 24)
        col.setSpacing(10)
        self.icon = QLabel("🎁", objectName="ChristmasIcon", alignment=Qt.AlignmentFlag.AlignCenter)
        self.title = QLabel("", objectName="ChristmasTitle", alignment=Qt.AlignmentFlag.AlignCenter, wordWrap=True)
        self.body = QLabel("", objectName="ChristmasBody", alignment=Qt.AlignmentFlag.AlignCenter, wordWrap=True)
        self.ok = QPushButton("Thanks!", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        self.ok.clicked.connect(self.dismiss)
        for w in (self.icon, self.title, self.body):
            col.addWidget(w)
        col.addSpacing(8)
        col.addWidget(self.ok, alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.card)
        self.hide()

    def present(self, title: str, body: str) -> None:
        self.title.setText(title)
        self.body.setText(body)
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.ok.setFocus()

    def dismiss(self) -> None:
        self.hide()
        self.closed.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.dismiss()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if not self.card.geometry().contains(event.position().toPoint()):
            self.dismiss()
        super().mousePressEvent(event)
