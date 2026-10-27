"""Async image loading for covers and banners.

Views ask for `pixmap(url, w, h)` while painting. A miss returns None and starts a
background load (download via CoverCache, decode and crop to exactly w x h at the
screen's pixel density). When it lands, `loaded` fires and views repaint.
"""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap

from core.covers import CoverCache
from core.tasks import TaskRunner

Key = tuple[str, int, int]


def load_cropped(covers: CoverCache, url: str, w: int, h: int, dpr: float) -> QImage:
    """Worker-thread safe: QImage (unlike QPixmap) can be used off the UI thread."""
    path = covers.get(url)
    img = QImage(str(path))
    if img.isNull():
        raise ValueError(f"Unreadable image: {url}")
    tw, th = max(1, round(w * dpr)), max(1, round(h * dpr))
    scaled = img.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
    x = (scaled.width() - tw) // 2
    y = (scaled.height() - th) // 3  # bias toward the top; faces and titles live there
    return scaled.copy(QRect(x, max(0, y), tw, th))


class ImageLoader(QObject):
    loaded = Signal(str)  # url

    def __init__(self, covers: CoverCache, parent: QObject | None = None, max_items: int = 500) -> None:
        super().__init__(parent)
        self.covers = covers
        self.runner = TaskRunner(self, max_threads=6)  # own pool so images never starve data calls
        self.max_items = max_items
        self._cache: OrderedDict[Key, QPixmap] = OrderedDict()
        self._pending: set[Key] = set()
        self._failed: set[str] = set()

    def pixmap(self, url: str | None, w: int, h: int) -> QPixmap | None:
        if not url or w <= 0 or h <= 0:
            return None
        key = (url, int(w), int(h))
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit
        if key in self._pending or url in self._failed:
            return None
        self._pending.add(key)
        dpr = QGuiApplication.instance().devicePixelRatio() if QGuiApplication.instance() else 1.0
        self.runner.submit(
            load_cropped, self.covers, url, key[1], key[2], dpr,
            on_done=lambda img, k=key, d=dpr: self._done(k, img, d),
            on_error=lambda _msg, k=key: self._fail(k),
        )
        return None

    def prefetch(self, url: str | None, w: int, h: int) -> None:
        self.pixmap(url, w, h)

    def _done(self, key: Key, img: QImage, dpr: float) -> None:
        self._pending.discard(key)
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(dpr)
        self._cache[key] = pm
        while len(self._cache) > self.max_items:
            self._cache.popitem(last=False)
        self.loaded.emit(key[0])

    def _fail(self, key: Key) -> None:
        self._pending.discard(key)
        self._failed.add(key[0])  # don't hammer a broken URL every repaint
