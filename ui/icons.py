"""Sidebar icons, drawn as simple line art so they look the same on every Mac
(text symbols depend on the font and can come out blank)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import theme

SIZE = 18
SCALE = 3   # drawn at 3x so it stays sharp on Retina screens


def _path(kind: str) -> QPainterPath:
    """Outline for an 18x18 box."""
    p = QPainterPath()
    if kind == "home":
        p.moveTo(2.5, 8.5)
        p.lineTo(9, 3)
        p.lineTo(15.5, 8.5)
        p.moveTo(4.5, 7.2)
        p.lineTo(4.5, 15)
        p.lineTo(13.5, 15)
        p.lineTo(13.5, 7.2)
        p.moveTo(7.5, 15)
        p.lineTo(7.5, 11)
        p.lineTo(10.5, 11)
        p.lineTo(10.5, 15)
    elif kind == "search":
        p.addEllipse(QPointF(7.8, 7.8), 4.6, 4.6)
        p.moveTo(11.2, 11.2)
        p.lineTo(15.2, 15.2)
    elif kind == "heart":
        p.moveTo(9, 15)
        p.cubicTo(3, 11, 2, 8.2, 2.6, 6.2)
        p.cubicTo(3.4, 3.4, 7.2, 2.8, 9, 5.6)
        p.cubicTo(10.8, 2.8, 14.6, 3.4, 15.4, 6.2)
        p.cubicTo(16, 8.2, 15, 11, 9, 15)
    elif kind == "stats":
        for x, top in ((4, 9.5), (9, 4.5), (14, 7.5)):
            p.moveTo(x, 15)
            p.lineTo(x, top)
        p.moveTo(2, 15.5)
        p.lineTo(16, 15.5)
    elif kind == "calendar":
        p.addRoundedRect(QRectF(2.5, 3.8, 13, 11.7), 2, 2)
        p.moveTo(2.5, 7.3)
        p.lineTo(15.5, 7.3)
        for x in (6, 12):
            p.moveTo(x, 2.2)
            p.lineTo(x, 5)
        for x, y in ((6, 10.3), (9, 10.3), (12, 10.3), (6, 13), (9, 13)):
            p.addEllipse(QPointF(x, y), 0.45, 0.45)
    elif kind == "settings":
        cx, cy = 9.0, 9.0
        for i in range(8):  # eight short teeth around a ring
            a = i * math.pi / 4
            p.moveTo(cx + 5.0 * math.cos(a), cy + 5.0 * math.sin(a))
            p.lineTo(cx + 7.0 * math.cos(a), cy + 7.0 * math.sin(a))
        p.addEllipse(QPointF(cx, cy), 4.8, 4.8)
        p.addEllipse(QPointF(cx, cy), 2.0, 2.0)
    return p


def _pixmap(kind: str, color: str) -> QPixmap:
    pm = QPixmap(SIZE * SCALE, SIZE * SCALE)
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(SCALE)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(_path(kind))
    painter.end()
    return pm


def nav_icon(kind: str) -> QIcon:
    """Muted normally; bright when hovered or selected, like the button text."""
    icon = QIcon()
    icon.addPixmap(_pixmap(kind, theme.MUTED), QIcon.Mode.Normal, QIcon.State.Off)
    bright = _pixmap(kind, theme.TEXT)
    for mode in (QIcon.Mode.Active, QIcon.Mode.Selected):
        icon.addPixmap(bright, mode, QIcon.State.Off)
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
        icon.addPixmap(bright, mode, QIcon.State.On)
    return icon


KINDS = ("home", "search", "heart", "stats", "calendar", "settings")
