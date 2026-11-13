"""Draw a card once, then copy the finished picture (2.0).

A card (cover with rounded corners, badges, the snow cap, its title) takes many steps to draw.
Scrolling repaints every card on screen many times a second, so each card's finished look is
kept as a picture and copied after the first time. A card is drawn again only when something
on it changes (its key), and pictures that are still loading or fading in aren't kept.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from typing import Callable, Hashable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap

from . import theme


class PaintCache:
    def __init__(self, max_items: int = 700, max_bytes: int = 96 * 1024 * 1024) -> None:
        self.max_items = max_items
        self.max_bytes = max_bytes          # by memory, not count: big cards on a 4K screen (2.0.1)
        self.bytes = 0
        self._items: OrderedDict[Hashable, QPixmap] = OrderedDict()
        self.hits = self.misses = 0

    def clear(self) -> None:
        self._items.clear()
        self.bytes = 0

    def __len__(self) -> int:
        return len(self._items)

    def draw(self, p: QPainter, rect: QRectF, key: Hashable,
             render: Callable[[QPainter, QRectF], bool], margin: int = 0) -> None:
        """Copy the cached picture for `key` to `rect`, or draw it with `render(painter, rect)`
        first. `render` returns True when what it drew is final (worth keeping). `margin`: extra
        room around rect for things that stick out (the snow cap)."""
        dev = p.device()
        dpr = dev.devicePixelRatioF() if dev is not None else 1.0
        w, h = rect.width() + 2 * margin, rect.height() + 2 * margin
        full = (key, round(w), round(h), dpr, theme.HOLIDAY, theme.ACCENT, theme.BG)
        pm = self._items.get(full)
        if pm is not None:
            self._items.move_to_end(full)
            self.hits += 1
            p.drawPixmap(QPointF(rect.x() - margin, rect.y() - margin), pm)
            return
        self.misses += 1
        pm = QPixmap(max(1, math.ceil(w * dpr)), max(1, math.ceil(h * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        q = QPainter(pm)
        q.setFont(p.font())
        keep = render(q, QRectF(margin, margin, rect.width(), rect.height()))
        q.end()
        p.drawPixmap(QPointF(rect.x() - margin, rect.y() - margin), pm)
        if keep:
            self._items[full] = pm
            self.bytes += pm.width() * pm.height() * 4
            while len(self._items) > 1 and (len(self._items) > self.max_items or self.bytes > self.max_bytes):
                _k, gone = self._items.popitem(last=False)
                self.bytes -= gone.width() * gone.height() * 4


CARDS = PaintCache()
