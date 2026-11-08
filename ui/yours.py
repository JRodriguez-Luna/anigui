"""Make it yours (2.0): your accent color, an app icon in your color, Home's rows in your order,
and a greeting with your name. All stored in AniGUI's settings on this Mac."""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsColorizeEffect, QGraphicsPixmapItem, QGraphicsScene

ICON_SIZES = (16, 32, 64, 128, 256, 512)

# Home's rows: (key, label). Your lists can be rows too ("list:<id>").
HOME_ROWS = (
    ("new", "New Episodes"),
    ("continue", "Continue Watching"),
    ("xmas", "Christmas anime (holidays)"),
    ("trending", "Trending Now"),
    ("season", "This season"),
    ("because", "Because you watched…"),
    ("saved", "Saved"),
)


def parse_rows(value: str | None) -> list[tuple[str, bool]]:
    """'continue:1,trending:0,…' -> [(key, on)]. Unknown keys are kept (your lists); rows
    missing from it (new in a later version) go at the end, switched on."""
    out: list[tuple[str, bool]] = []
    seen = set()
    for part in (value or "").split(","):
        key, _, on = part.strip().rpartition(":")
        if key and key not in seen:
            out.append((key, on != "0"))
            seen.add(key)
    for key, _label in HOME_ROWS:
        if key not in seen:
            out.append((key, True))
    return out


def join_rows(rows: list[tuple[str, bool]]) -> str:
    return ",".join(f"{k}:{1 if on else 0}" for k, on in rows)


def greeting(name: str, now: dt.datetime | None = None, holiday: bool = False) -> str:
    name = " ".join(name.split())
    if not name:
        return ""
    now = now or dt.datetime.now()
    if holiday and now.month == 12 and now.day in (24, 25):
        return f"Merry Christmas, {name} 🎄"
    if holiday and (now.month, now.day) in ((12, 31), (1, 1)):
        return f"Happy New Year, {name} 🎆"
    h = now.hour
    part = "Good morning" if 5 <= h < 12 else "Good afternoon" if 12 <= h < 17 else "Good evening" if 17 <= h < 22 \
        else "Up late"
    return f"{part}, {name}" + (" ❄" if holiday else "")


def tint(pm: QPixmap, color: str, strength: float = 0.88) -> QPixmap:
    """The picture recolored toward `color` (keeps its light and shade)."""
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(pm)
    effect = QGraphicsColorizeEffect()
    effect.setColor(QColor(color))
    effect.setStrength(strength)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    out = QImage(pm.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    scene.render(p, QRectF(out.rect()), item.boundingRect())
    p.end()
    res = QPixmap.fromImage(out)
    res.setDevicePixelRatio(pm.devicePixelRatio())
    return res


def tinted_icon(base: QIcon, color: str) -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        pm = base.pixmap(QSize(size, size))
        if not pm.isNull():
            icon.addPixmap(tint(pm, color))
    return icon if not icon.isNull() else base
