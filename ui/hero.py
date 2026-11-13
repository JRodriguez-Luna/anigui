"""Cinematic backdrops: the rotating hero on Home and the header behind show details."""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from core.anilist import Media

from . import theme
from .cards import format_label
from .images import ImageLoader
from . import festive
from .motion import Fader, crossfade, quiet
from .widgets import WrapLabel

BUCKET = 320  # request banner widths in steps so resizing doesn't refetch constantly


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:")
    return cut + "…"


def media_meta(media: Media) -> str:
    bits = []
    if media.score:
        bits.append(f"★ {media.score}%")
    if media.year:
        bits.append(f"{(media.season or '').title()} {media.year}".strip())
    if media.format:
        bits.append(format_label(media.format) or "")
    if media.episodes:
        bits.append(f"{media.episodes} episodes")
    if media.genres:
        bits.append(", ".join(media.genres[:3]))
    return "  ·  ".join(b for b in bits if b)


def airing_note(media: Media) -> str | None:
    if not media.next_episode or not media.next_airing_at:
        return None
    when_at = dt.datetime.fromtimestamp(media.next_airing_at)
    delta = when_at - dt.datetime.now()
    if delta.total_seconds() <= 0:
        return f"Episode {media.next_episode} is out"
    if delta.days >= 7:
        return f"Episode {media.next_episode} airs {when_at:%b} {when_at.day}"
    days, hours = delta.days, delta.seconds // 3600
    when = f"{days}d {hours}h" if days else f"{hours}h {delta.seconds % 3600 // 60}m"
    return f"Episode {media.next_episode} airs in {when}"


class Backdrop(QWidget):
    """Paints a wide image cropped to fill, faded into the background color."""

    def __init__(self, images: ImageLoader, parent=None) -> None:
        super().__init__(parent)
        self.images = images
        self.image_url: str | None = None
        self.fallback_url: str | None = None   # tall cover if there's no banner
        self.tint: QColor | None = None
        self.dim = 0.0                          # extra darkening, 0..1
        self.ambient = None                     # cinema.Ambient, when it paints the art for us (2.0)
        images.loaded.connect(self._on_loaded)

    def set_image(self, url: str | None, fallback: str | None = None, tint: str | None = None) -> None:
        self.image_url, self.fallback_url = url, fallback
        self.tint = QColor(tint) if tint else None
        if self.ambient is not None:
            self.ambient.source_changed(self)
        self.update()

    def _on_loaded(self, url: str) -> None:
        if url in (self.image_url, self.fallback_url) and self.ambient is None:
            self.update()

    def paintEvent(self, _event) -> None:
        if self.ambient is not None:
            return      # the window's backdrop paints the art, edge to edge under the sidebar
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        p.fillRect(rect, QColor(theme.BG))

        w, h = self.width(), self.height()
        bucket_w = ((w + BUCKET - 1) // BUCKET) * BUCKET
        pm = self.images.pixmap(self.image_url or self.fallback_url, bucket_w, h)
        if pm is None and self.image_url and self.fallback_url:
            pm = self.images.pixmap(self.fallback_url, bucket_w, h)
        url = self.image_url if self.images.pixmap(self.image_url, bucket_w, h) is not None else self.fallback_url
        fade = self.images.alpha(url) if pm is not None else 1.0
        if (pm is None or fade < 1) and self.tint is not None:
            grad = QLinearGradient(rect.topRight(), rect.bottomLeft())
            grad.setColorAt(0, self.tint.darker(160))
            grad.setColorAt(1, QColor(theme.BG))
            p.fillRect(rect, grad)
        if pm is not None:
            dpr = pm.devicePixelRatio()
            src_w = w * dpr
            src = QRectF((pm.width() - src_w) / 2, 0, src_w, pm.height())
            p.setOpacity(fade)
            p.drawPixmap(rect, pm, src)
            p.setOpacity(1.0)

        if self.dim:
            p.fillRect(rect, QColor(10, 10, 15, int(255 * self.dim)))
        bg = QColor(theme.BG)
        left = QLinearGradient(0, 0, w, 0)
        left.setColorAt(0.0, bg)
        left.setColorAt(0.30, _alpha(bg, 215))
        left.setColorAt(0.70, _alpha(bg, 40))
        left.setColorAt(1.0, _alpha(bg, 0))
        p.fillRect(rect, left)
        bottom = QLinearGradient(0, h, 0, 0)
        bottom.setColorAt(0.0, bg)
        bottom.setColorAt(0.35, _alpha(bg, 140))
        bottom.setColorAt(1.0, _alpha(bg, 0))
        p.fillRect(rect, bottom)


def _alpha(c: QColor, a: int) -> QColor:
    out = QColor(c)
    out.setAlpha(a)
    return out


class HeroBanner(Backdrop):
    """Rotating spotlight of trending shows with Play / More info."""

    playRequested = Signal(object)  # Media
    infoRequested = Signal(object)  # Media
    ROTATE_MS = 9000

    def __init__(self, images: ImageLoader, parent=None) -> None:
        super().__init__(images, parent)
        self.setMinimumHeight(440)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.items: list[Media] = []
        self.current = 0

        self.kicker = QLabel("", objectName="Kicker")
        self.title = WrapLabel("", 760, objectName="HeroTitle")
        self.meta = QLabel("", objectName="Meta")
        self.synopsis = WrapLabel("", 620, objectName="Synopsis")
        for label in (self.kicker, self.title, self.meta, self.synopsis):
            label.setTextFormat(Qt.TextFormat.PlainText)   # text from AniList
        self.play = QPushButton("▶  Play", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        self.info = QPushButton("ⓘ  More info", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.play.clicked.connect(lambda: self.items and self.playRequested.emit(self.items[self.current]))
        self.info.clicked.connect(lambda: self.items and self.infoRequested.emit(self.items[self.current]))

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addWidget(self.play)
        buttons.addWidget(self.info)
        buttons.addStretch(1)
        self.dots = _Dots(self)
        self.dots.selected.connect(self.show_item)
        buttons.addWidget(self.dots, 0, Qt.AlignmentFlag.AlignBottom)

        col = QVBoxLayout(self)
        col.setContentsMargins(44, 40, 44, 34)
        col.setSpacing(10)
        col.addStretch(1)
        col.addWidget(self.kicker)
        col.addWidget(self.title)
        col.addWidget(self.meta)
        col.addSpacing(4)
        col.addWidget(self.synopsis)
        col.addSpacing(12)
        col.addLayout(buttons)

        self.timer = QTimer(self, interval=self.ROTATE_MS)
        self.timer.timeout.connect(self._rotate)
        self.set_loading()

    def set_loading(self) -> None:
        self.kicker.setText("")
        self.title.setText("")
        self.meta.setText("")
        self.synopsis.setText("")
        self.play.setVisible(False)
        self.info.setVisible(False)

    def set_items(self, items: list[Media]) -> None:
        self.items = [m for m in items if m.banner][:6] or items[:6]
        self.dots.set_count(len(self.items))
        for m in self.items:
            self.images.prefetch(m.banner or m.cover, ((max(self.width(), 900) + BUCKET - 1) // BUCKET) * BUCKET, self.height())
        if self.items:
            self.show_item(0)
            self.timer.start()

    def _rotate(self) -> None:
        if quiet():          # an episode is playing, or you're in another app: no need to (2.0.1)
            return
        self.show_item((self.current + 1) % max(1, len(self.items)))

    def show_item(self, i: int) -> None:
        if not self.items:
            return
        if i != self.current and self.isVisible() and self.title.text():
            crossfade(self, ms=450)                 # the old show dissolves into the new one
        self.current = i
        m = self.items[i]
        self.kicker.setText(f"#{i + 1} TRENDING NOW")
        self.title.setText(m.display_title)
        self.meta.setText(media_meta(m))
        self.synopsis.setText(truncate(m.description, 260))
        self.play.setVisible(True)
        self.info.setVisible(True)
        self.dots.set_current(i)
        self.set_image(m.banner, m.cover, m.cover_color)
        self.timer.start()  # restart the countdown after a manual pick

    def enterEvent(self, event) -> None:
        self.timer.stop()  # don't rotate while the pointer is on it
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self.items:
            self.timer.start()
        super().leaveEvent(event)


class _Dots(QWidget):
    selected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.count, self.current = 0, 0
        self.previous, self.t = 0, 1.0
        self._move = Fader(self._set_t, 300, self)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(18)

    def set_count(self, n: int) -> None:
        self.count = n
        self.setFixedWidth(max(0, n * 18 + 16))
        self.update()

    def set_current(self, i: int) -> None:
        if i != self.current:
            self.previous, self.t = self.current, 0.0
            self._move.stop()
            self._move.start()
        self.current = i
        self.update()

    def _set_t(self, t: float) -> None:
        self.t = t
        self.update()

    def _x(self, i: int) -> float:
        return i * 18 + 4

    def _width(self, i: int) -> float:
        """The active dot is 22 wide; while moving, the old one shrinks as the new one grows."""
        t = self.t
        if i == self.current:
            return 8 + 14 * t
        if i == self.previous and t < 1:
            return 22 - 14 * t
        return 8.0

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        if theme.HOLIDAY:                       # little ornaments instead of dots
            for i in range(self.count):
                festive.ornament(p, QPointF(self._x(i) + 6 + (14 if i > self.current else 0), 8.5),
                                 5.5 if i == self.current else 4.0, i == self.current)
            return
        x = 4.0
        for i in range(self.count):
            w = self._width(i)
            color = QColor(theme.ACCENT) if i == self.current else QColor(255, 255, 255, 80)
            if i == self.current and self.t < 1:
                color.setAlphaF(0.35 + 0.65 * self.t)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x, 3, w, 8), 4, 4)
            x += w + 10

    def mousePressEvent(self, e) -> None:
        for i in range(self.count):
            x = self._x(i) if i <= self.current else self._x(i) + 14
            if x - 4 <= e.position().x() <= x + (22 if i == self.current else 8) + 4:
                self.selected.emit(i)
                return
