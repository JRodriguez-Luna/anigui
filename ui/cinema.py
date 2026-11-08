"""The Cinema look (2.0): one backdrop behind the whole window.

The page's artwork (Home's spotlight, a show's banner) is painted here, edge to edge, so it
runs under the see-through sidebar instead of stopping at it. Pages are transparent and only
hold the text and buttons; the hero and show header tell this layer what to paint and where.

Scenes:
  band  - the art fills the source widget's rows, from the window's left edge to its right
  glow  - watching: the show's art, blurred and dim, behind the whole page (ambient light)
  none  - plain background (with a faint red and green glow while the holiday theme is on)
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap, QRadialGradient, QRegion
from PySide6.QtWidgets import QAbstractScrollArea, QWidget

from . import theme
from .images import ImageLoader
from .motion import note_scroll, reduce_motion

BUCKET = 320         # ask for pictures in width steps so resizing doesn't refetch constantly
FADE_MS = 450


def _bucket(n: int) -> int:
    return max(BUCKET, ((int(n) + BUCKET - 1) // BUCKET) * BUCKET)


def _alpha(c: QColor, a: int) -> QColor:
    out = QColor(c)
    out.setAlpha(max(0, min(255, int(a))))
    return out


class _PageBacking(QObject):
    """Paints the scene behind a page's content, inside the page itself."""

    def __init__(self, ambient: "Ambient") -> None:
        super().__init__(ambient)
        self.ambient = ambient

    def eventFilter(self, obj: QObject, event) -> bool:
        if event.type() == QEvent.Type.Paint and obj is self.ambient.page_body:
            self.ambient.paint_into(obj, event)
        return False


class Ambient(QWidget):
    def __init__(self, images: ImageLoader, parent: QWidget, sidebar_width: int = 208) -> None:
        super().__init__(parent)
        self.images = images
        self.sidebar_width = sidebar_width
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.source = None            # a hero.Backdrop
        self.mode = "none"
        self.page_body: QWidget | None = None    # the open page's scrolling content
        self._backing = _PageBacking(self)
        self._backed: set[int] = set()
        self._scroll = None           # the open page's scroll bar
        self._last_extent: QRectF | None = None
        self._prev: QPixmap | None = None
        self._fade_rect = QRect()
        self._layer: tuple[tuple, QPixmap] | None = None   # the scene, drawn once and then copied
        self._prev_opacity = 0.0
        self._fade = QVariantAnimation(self, startValue=1.0, endValue=0.0, duration=FADE_MS)
        self._fade.valueChanged.connect(self._fading)
        self._fade.finished.connect(self._faded)
        images.loaded.connect(self._on_loaded)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.lower()

    # -- scenes ----------------------------------------------------------------------------

    def set_page(self, body: QWidget | None) -> None:
        """The open page's content widget. It paints the scene behind itself and is opaque, so
        scrolling can move what's already drawn instead of redrawing the page (2.0)."""
        if body is self.page_body:
            return
        if self._scroll is not None:
            try:
                self._scroll.valueChanged.disconnect(self._moved)
            except (RuntimeError, TypeError):
                pass
            self._scroll = None
        self.page_body = body
        if body is not None:
            if id(body) not in self._backed:
                self._backed.add(id(body))
                body.installEventFilter(self._backing)
                body.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
            area = self._scroll_area(body)
            if area is not None:
                self._scroll = area.verticalScrollBar()
                self._scroll.valueChanged.connect(self._moved)
        self._refresh()

    def follow(self, source, mode: str = "band") -> None:
        """Paint `source`'s art (a hero.Backdrop), or nothing with source=None."""
        mode = mode if source is not None else "none"
        if source is self.source and mode == self.mode:
            return
        self._end_fade()
        if self.source is not None and self.source is not source:
            self.source.ambient = None
            self.source.update()
        self.source, self.mode = source, mode
        if source is not None:
            source.ambient = self
            source.update()
        self._refresh()

    def source_changed(self, source) -> None:
        """The hero moved on to another show (or the show page got its banner)."""
        if source is self.source:
            self._snapshot()
            self._refresh()

    def _refresh(self, rect: QRect | None = None) -> None:
        """Repaint the scene (in this window's coordinates), here and in the page."""
        if rect is None:
            self.update()
        else:
            self.update(rect)
        body = self.page_body
        if body is not None and body.isVisible():
            if rect is None:
                body.update()
            else:
                body.update(rect.translated(-body.mapTo(self.parentWidget(), QPoint(0, 0))))

    @staticmethod
    def _scroll_area(w: QWidget):
        while w is not None:
            if isinstance(w, QAbstractScrollArea):
                return w
            w = w.parentWidget()
        return None

    def _moved(self, _v=None) -> None:
        note_scroll()
        self._moved_paint()

    def _moved_paint(self) -> None:
        """The page scrolled. The page moves its own pixels (the scene scrolls with it); only
        the strips it doesn't cover (under the sidebar, the scroll bar) are painted here."""
        # Only rows where the picture was or is now need it; plain background stays put
        now = self._scene_extent()
        rows = [r for r in (self._last_extent, now) if r is not None]
        self._last_extent = now
        if not rows:
            return
        dirty = QRegion()
        for r in rows:
            dirty += QRegion(QRect(0, int(r.top()) - 1, self.width(), int(r.height()) + 2))
        body = self.page_body
        if body is not None and body.isVisible():
            area = self._scroll_area(body)
            vp = area.viewport() if area is not None else body
            shown = QRect(vp.mapTo(self.parentWidget(), QPoint(0, 0)), vp.size())
            dirty -= QRegion(shown)
        self.update(dirty)

    def _on_loaded(self, url: str) -> None:
        s = self.source
        if s is not None and url in (s.image_url, s.fallback_url):
            self._refresh()

    # -- the old scene fades out over the new one ------------------------------------------

    def _snapshot(self) -> None:
        """The hero's art is changing: fade the old picture out, in the hero's rows only
        (repainting the whole window every frame made starting a video stutter)."""
        band = self.band_rect() if self.mode == "band" else None
        if band is None or not self.isVisible() or reduce_motion():
            return
        self._fade_rect = band.toAlignedRect().intersected(self.rect())
        if self._fade_rect.isEmpty():
            return
        self._prev = self._render_scene(self._fade_rect)
        self._prev_opacity = 1.0
        self._fade.stop()
        self._fade.start()

    def _end_fade(self) -> None:
        self._fade.stop()
        self._prev = None

    def _fading(self, v) -> None:
        self._prev_opacity = float(v)
        self._refresh(self._fade_rect)

    def _faded(self) -> None:
        self._prev = None
        self._refresh(self._fade_rect)

    # -- geometry ------------------------------------------------------------------------

    def eventFilter(self, obj: QObject, event) -> bool:
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
            self.lower()
        return False

    def band_rect(self) -> QRectF | None:
        """Where the source sits in this window, stretched to both edges."""
        s = self.source
        if s is None or not s.isVisible():
            return None
        top = s.mapTo(self.parentWidget(), QPoint(0, 0)).y()
        return QRectF(0, top, self.width(), s.height())

    def scene_rect(self) -> QRectF | None:
        """Where the scene's picture goes, in this window's coordinates. It's pinned to the
        page (the hero's rows, or the top of the page), so it scrolls with the page."""
        if self.mode == "band":
            return self.band_rect()
        top = 0
        body = self.page_body
        if body is not None and body.isVisible():
            top = body.mapTo(self.parentWidget(), QPoint(0, 0)).y()
        return QRectF(0, top, self.width(), self.height())

    def _scene_extent(self) -> QRectF | None:
        """The rows where the scene isn't plain background (None: it's plain everywhere)."""
        if self.mode == "none" and not theme.HOLIDAY:
            return None
        rect = self.scene_rect()
        if rect is None or rect.bottom() < 0 or rect.top() > self.height():
            return None
        return rect

    # -- painting ------------------------------------------------------------------------

    def _paint_scene(self, p: QPainter, clip: QRect, offset: QPoint) -> None:
        """The scene, for the part `clip` (window coordinates), drawn with `offset` subtracted."""
        p.fillRect(clip.translated(-offset), QColor(theme.BG))
        rect = self.scene_rect()
        if rect is not None and rect.bottom() >= 0 and rect.width() > 0 and rect.height() > 0:
            layer = self._layer_for(int(rect.width()), int(rect.height()))
            p.drawPixmap(QPoint(int(rect.left()), int(rect.top())) - offset, layer)
        if self._prev is not None and self._prev_opacity > 0:
            p.setOpacity(self._prev_opacity)
            p.drawPixmap(self._fade_rect.topLeft() - offset, self._prev)
            p.setOpacity(1.0)

    def _render_scene(self, rect: QRect) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pm = QPixmap(max(1, int(rect.width() * dpr)), max(1, int(rect.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        p = QPainter(pm)
        self._paint_scene(p, rect, rect.topLeft())
        p.end()
        return pm

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        self._paint_scene(p, event.rect(), QPoint(0, 0))

    def paint_into(self, widget: QWidget, event) -> None:
        """Called while `widget` (the page's content) paints: the scene behind it."""
        offset = widget.mapTo(self.parentWidget(), QPoint(0, 0))
        p = QPainter(widget)
        self._paint_scene(p, event.rect().translated(offset), offset)
        p.end()

    def _layer_for(self, w: int, h: int) -> QPixmap:
        """The scene at this size. Drawing the art (scaled, blurred, with its fades) is slow;
        copying the finished picture is fast, and the window repaints often while a video plays."""
        s = self.source
        urls = (s.image_url, s.fallback_url, s.tint.name() if s.tint else None, s.dim) if s is not None else None
        key = (self.mode, id(s), urls, w, h, theme.HOLIDAY, theme.BG)
        if self._layer is not None and self._layer[0] == key:
            return self._layer[1]
        dpr = self.devicePixelRatioF()
        pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
        pm.setDevicePixelRatio(dpr)
        bg = QColor(theme.BG)
        pm.fill(bg)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        settled = True
        if self.mode == "band":
            settled = self._paint_band(p, bg, QRectF(0, 0, w, h))
        elif self.mode == "glow":
            settled = self._paint_glow(p, bg, w, h)
        if self.mode != "band" and theme.HOLIDAY:
            self._paint_holiday(p, w, h)
        p.end()
        if settled:          # (not while the picture is still loading or fading in)
            self._layer = (key, pm)
        return pm

    def _art(self, w: int, h: int, blurred: bool = False):
        s = self.source
        get = self.images.blurred if blurred else self.images.pixmap
        for url in (s.image_url, s.fallback_url):
            pm = get(url, w, h) if url else None
            if pm is not None:
                return pm, url
        return None, None

    def _paint_band(self, p: QPainter, bg: QColor, rect: QRectF) -> bool:
        s = self.source
        w, h = int(rect.width()), int(rect.height())
        pm, url = self._art(_bucket(w), h)
        fade = self.images.alpha(url) if pm is not None else 1.0
        if (pm is None or fade < 1) and s.tint is not None:
            grad = QLinearGradient(rect.topRight(), rect.bottomLeft())
            grad.setColorAt(0, s.tint.darker(160))
            grad.setColorAt(1, bg)
            p.fillRect(rect, grad)
        if pm is not None:
            dpr = pm.devicePixelRatio()
            src = QRectF((pm.width() - w * dpr) / 2, 0, w * dpr, pm.height())
            p.setOpacity(fade)
            p.drawPixmap(rect, pm, src)
            p.setOpacity(1.0)
        if s.dim:
            p.fillRect(rect, QColor(10, 10, 15, int(255 * s.dim)))
        # Darker where the words are; lighter under the glass sidebar so the art shows through
        side = min(0.45, self.sidebar_width / max(1, w))
        left = QLinearGradient(rect.left(), 0, rect.right(), 0)
        left.setColorAt(0.0, _alpha(bg, 70))
        left.setColorAt(side, _alpha(bg, 205))
        left.setColorAt(side + (1 - side) * 0.30, _alpha(bg, 190))
        left.setColorAt(side + (1 - side) * 0.70, _alpha(bg, 40))
        left.setColorAt(1.0, _alpha(bg, 0))
        p.fillRect(rect, left)
        bottom = QLinearGradient(0, rect.bottom(), 0, rect.top())
        bottom.setColorAt(0.0, bg)
        bottom.setColorAt(0.35, _alpha(bg, 140))
        bottom.setColorAt(1.0, _alpha(bg, 0))
        p.fillRect(rect, bottom)
        return (pm is not None and fade >= 1) or not (s.image_url or s.fallback_url)

    def _paint_glow(self, p: QPainter, bg: QColor, w: int, h: int) -> bool:
        pm, _url = self._art(_bucket(w), _bucket(h), blurred=True)
        rect = QRectF(0, 0, w, h)
        if pm is not None:
            dpr = pm.devicePixelRatio()
            sw, sh = pm.width() / dpr, pm.height() / dpr
            scale = max(w / sw, h / sh)
            src = QRectF((sw - w / scale) / 2 * dpr, (sh - h / scale) / 2 * dpr, w / scale * dpr, h / scale * dpr)
            p.setOpacity(0.32)
            p.drawPixmap(rect, pm, src)
            p.setOpacity(1.0)
        elif self.source.tint is not None:
            glow = QRadialGradient(QPointF(w * 0.6, h * 0.2), max(w, h) * 0.7)
            glow.setColorAt(0, _alpha(self.source.tint, 60))
            glow.setColorAt(1, _alpha(self.source.tint, 0))
            p.fillRect(rect, glow)
        fade = QLinearGradient(0, h, 0, 0)
        fade.setColorAt(0.0, bg)
        fade.setColorAt(0.45, _alpha(bg, 150))
        fade.setColorAt(1.0, _alpha(bg, 60))
        p.fillRect(rect, fade)
        return pm is not None or not (self.source.image_url or self.source.fallback_url)

    def _paint_holiday(self, p: QPainter, w: int, h: int) -> None:
        for x, y, color in ((w * 0.85, -h * 0.05, "#E0403C"), (w * 0.05, h * 1.05, "#3FAE6A")):
            g = QRadialGradient(QPointF(x, y), max(w, h) * 0.55)
            g.setColorAt(0, _alpha(QColor(color), 26))
            g.setColorAt(1, _alpha(QColor(color), 0))
            p.fillRect(QRectF(0, 0, w, h), g)
