"""The holiday theme's pieces: snow, the Santa hat, and November's "theme is ready" banner."""

from __future__ import annotations

import datetime as dt
import math
import random

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core import holiday

from . import theme
from .motion import fade_in, fade_out, reduce_motion


def is_on(ctx, today: dt.date | None = None) -> bool:
    return holiday.is_on(str(ctx.pref("holiday_theme", "auto")), today)


# -- snow -------------------------------------------------------------------------------------

class SnowLayer(QWidget):
    """Light snowfall painted over its parent (mouse clicks pass through). Runs only while
    it's on screen, and never with Reduce motion."""

    def __init__(self, parent: QWidget, flakes: int = 70, alpha: int = 215) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.count, self.alpha = flakes, alpha
        self.flakes: list[list[float]] = []
        self._timer = QTimer(self, interval=33)
        self._timer.timeout.connect(self._step)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.running = False

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
            self.flakes = []
        return False

    def start(self) -> None:
        self.running = True
        self.show()
        self.raise_()
        if not reduce_motion():
            self._timer.start()

    def stop(self) -> None:
        self.running = False
        self._timer.stop()
        self.hide()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.running and not reduce_motion():
            self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _seed(self) -> None:
        w, h = max(1, self.width()), max(1, self.height())
        self.flakes = [[random.uniform(0, w), random.uniform(0, h), random.uniform(0.8, 2.4),
                        random.uniform(0.3, 1.0), random.uniform(0, 6.28)] for _ in range(self.count)]

    def _step(self) -> None:
        if not self.isVisible():
            self._timer.stop()
            return
        if not self.flakes:
            self._seed()
        w, h = self.width(), self.height()
        for f in self.flakes:
            f[1] += f[3]
            f[4] += 0.02
            f[0] += math.sin(f[4]) * 0.35
            if f[1] > h + 3:
                f[0], f[1] = random.uniform(0, w), -3
        self.update()

    def paintEvent(self, _e) -> None:
        if not self.flakes:
            self._seed()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, self.alpha))
        for x, y, r, _s, _d in self.flakes:
            p.drawEllipse(QPointF(x, y), r, r)
        p.end()


# -- Santa hat ----------------------------------------------------------------------------------

def draw_hat(p: QPainter, x: float, y: float, size: float, angle: float = -18) -> None:
    """A small Santa hat whose brim's left end sits near (x, y), `size` wide."""
    p.save()
    p.translate(x, y)
    p.rotate(angle)
    s = size / 22
    p.scale(s, s)
    p.setPen(Qt.PenStyle.NoPen)
    hat = QPainterPath()
    hat.moveTo(2, 14)
    hat.quadTo(9, -2, 18, 6)
    hat.lineTo(20, 14)
    hat.closeSubpath()
    p.setBrush(QColor("#D93A3A"))
    p.drawPath(hat)
    p.setBrush(QColor("#F2F2F2"))
    p.drawRoundedRect(QRectF(0, 12, 21, 4.5), 2.2, 2.2)
    p.drawEllipse(QPointF(19, 5), 2.8, 2.8)
    p.restore()


class Brand(QLabel):
    """The sidebar's 'AniGUI', in the accent color, with a hat during the holidays."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, objectName="Brand")
        self.refresh()

    def refresh(self) -> None:
        self.setText(f"Ani<span style='color:{theme.ACCENT}'>GUI</span>")
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if theme.HOLIDAY:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            m = self.contentsMargins()
            draw_hat(p, m.left() - 4, m.top() - 1, 22)
            p.end()


def holiday_icon(base: QIcon) -> QIcon:
    """The app icon wearing a Santa hat (for the Dock while the theme is on)."""
    pm = base.pixmap(512, 512)
    if pm.isNull():
        return base
    out = QPixmap(pm)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_hat(p, out.width() * 0.50, out.height() * 0.06, out.width() * 0.44, 18)
    p.end()
    return QIcon(out)


# -- November's banner ----------------------------------------------------------------------------

LIGHT_COLORS = ("#FF5A5A", "#FFD54A", "#4FD18B", "#5AB4FF", "#FF8AD8")


class _Decor(QWidget):
    """The banner's string of twinkling lights and the swinging ornament (painted)."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.t = 0.0
        self._timer = QTimer(self, interval=40)
        self._timer.timeout.connect(self._step)

    def start(self) -> None:
        if not reduce_motion():
            self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _step(self) -> None:
        self.t += 0.04
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        # the wire, drooping across the top
        wire = QPainterPath()
        wire.moveTo(-10, 4)
        wire.quadTo(w / 2, 30, w + 10, 4)
        p.setPen(QPen(QColor("#3B4A3F"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(wire)
        n = max(8, int(w / 34))
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            u = (i + 0.5) / n
            x = -10 + (w + 20) * u
            y = (1 - u) ** 2 * 4 + 2 * (1 - u) * u * 30 + u ** 2 * 4      # on the curve
            color = QColor(LIGHT_COLORS[i % len(LIGHT_COLORS)])
            glow = 0.55 + 0.45 * math.sin(self.t * 2.4 + i * 1.3) if self._timer.isActive() else 1.0
            color.setAlphaF(max(0.35, glow))
            p.setBrush(QColor("#5A5A5A"))
            p.drawRect(QRectF(x - 2, y + 1, 4, 3))
            p.setBrush(color)
            p.drawEllipse(QRectF(x - 4, y + 3, 8, 11))
        # the ornament, swinging from its hook
        swing = 8 * math.sin(self.t * 2.2) if self._timer.isActive() else 0.0
        p.save()
        p.translate(34, 20)
        p.rotate(swing)
        p.setPen(QPen(QColor("#8A8A8A"), 1.5))
        p.drawLine(QPointF(0, 0), QPointF(0, 12))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#C9A227"))
        p.drawRoundedRect(QRectF(-5, 10, 10, 7), 2, 2)
        p.setBrush(QColor("#D93A3A"))
        p.drawEllipse(QPointF(0, 36), 19, 19)
        p.setPen(QPen(QColor("#F2E6C9"), 2.5))
        band = QPainterPath()
        band.moveTo(-17, 33)
        band.quadTo(0, 27, 17, 33)
        p.drawPath(band)
        band = QPainterPath()
        band.moveTo(-18, 41)
        band.quadTo(0, 47, 18, 41)
        p.drawPath(band)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 90))
        p.drawEllipse(QPointF(-7, 28), 4, 4)
        p.restore()
        p.end()


class HolidayBanner(QFrame):
    """'The holiday theme is ready … Want it now?' with Turn on now / Wait. Shown once."""

    turnOn = Signal()
    wait = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("HolidayBanner")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(96)
        title = QLabel("The holiday theme is ready", objectName="HolidayTitle")
        sub = QLabel("Snow, lights and red-and-green colors. It starts by itself the day after "
                     "Thanksgiving. Want it now?", objectName="HolidayText", wordWrap=True)
        self.on_btn = QPushButton("Turn on now", objectName="HolidayOn", cursor=Qt.CursorShape.PointingHandCursor)
        self.wait_btn = QPushButton("Wait", objectName="HolidayWait", cursor=Qt.CursorShape.PointingHandCursor)
        self.on_btn.clicked.connect(lambda: self._leave(self.turnOn))
        self.wait_btn.clicked.connect(lambda: self._leave(self.wait))
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(title)
        text.addWidget(sub)
        row = QHBoxLayout(self)
        row.setContentsMargins(74, 28, 18, 16)
        row.setSpacing(12)
        row.addLayout(text, 1)
        row.addWidget(self.on_btn)
        row.addWidget(self.wait_btn)
        self.snow = SnowLayer(self, flakes=40, alpha=190)
        self.decor = _Decor(self)
        self.setVisible(False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.decor.setGeometry(self.rect())

    def appear(self) -> None:
        fade_in(self, 420, rise=10)
        self.snow.start()
        self.snow.lower()
        self.decor.setGeometry(self.rect())
        self.decor.show()
        self.decor.raise_()
        self.decor.start()

    def _leave(self, signal) -> None:
        self.on_btn.setEnabled(False)
        self.wait_btn.setEnabled(False)
        fade_out(self, 320, drop=-8)
        signal.emit()
