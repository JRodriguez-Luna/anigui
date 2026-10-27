#!/usr/bin/env python3
"""Draw the AniGUI icon and write packaging/AniGUI.png (1024px) and packaging/AniGUI.icns.

    QT_QPA_PLATFORM=offscreen python packaging/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)

HERE = Path(__file__).resolve().parent
SIZE = 1024
BODY = QRectF(100, 100, 824, 824)  # Apple's grid: 824px body on a 1024 canvas
RADIUS = 186


def rounded_triangle(cx: float, cy: float, size: float, r: float) -> QPainterPath:
    """Play triangle pointing right with softened corners."""
    h = size * 0.866
    pts = [QPointF(cx - h / 3, cy - size / 2), QPointF(cx + 2 * h / 3, cy), QPointF(cx - h / 3, cy + size / 2)]
    path = QPainterPath()
    for i, p in enumerate(pts):
        prev, nxt = pts[i - 1], pts[(i + 1) % 3]
        a = p + (prev - p) * (r / _dist(prev, p))
        b = p + (nxt - p) * (r / _dist(nxt, p))
        if i == 0:
            path.moveTo(a)
        else:
            path.lineTo(a)
        path.quadTo(p, b)
    path.closeSubpath()
    return path


def _dist(a: QPointF, b: QPointF) -> float:
    d = a - b
    return (d.x() ** 2 + d.y() ** 2) ** 0.5


def draw() -> QImage:
    img = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # soft drop shadow
    for i, alpha in enumerate((26, 20, 14, 9, 5)):
        grow = 4 + i * 5
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, alpha))
        p.drawRoundedRect(BODY.adjusted(-grow / 2, -grow / 2 + 14, grow / 2, grow / 2 + 14), RADIUS + grow / 2, RADIUS + grow / 2)

    body = QPainterPath()
    body.addRoundedRect(BODY, RADIUS, RADIUS)
    p.setClipPath(body)

    bg = QLinearGradient(BODY.topLeft(), BODY.bottomRight())
    bg.setColorAt(0.0, QColor("#2B1B33"))
    bg.setColorAt(0.55, QColor("#14121D"))
    bg.setColorAt(1.0, QColor("#0A0A10"))
    p.fillRect(BODY, bg)

    glow = QRadialGradient(QPointF(560, 560), 430)
    glow.setColorAt(0.0, QColor(255, 107, 61, 120))
    glow.setColorAt(0.55, QColor(255, 107, 61, 28))
    glow.setColorAt(1.0, QColor(255, 107, 61, 0))
    p.fillRect(BODY, glow)

    # motion streaks behind the play mark
    p.setPen(Qt.PenStyle.NoPen)
    for y, x0, length, alpha in ((420, 230, 170, 120), (512, 190, 220, 170), (604, 250, 150, 110)):
        streak = QLinearGradient(x0, 0, x0 + length, 0)
        streak.setColorAt(0, QColor(255, 140, 92, 0))
        streak.setColorAt(1, QColor(255, 140, 92, alpha))
        p.setBrush(streak)
        p.drawRoundedRect(QRectF(x0, y - 11, length, 22), 11, 11)

    tri = rounded_triangle(555, 512, 430, 58)
    fill = QLinearGradient(QPointF(420, 300), QPointF(700, 720))
    fill.setColorAt(0.0, QColor("#FFA071"))
    fill.setColorAt(0.5, QColor("#FF6B3D"))
    fill.setColorAt(1.0, QColor("#E2492A"))
    p.setBrush(fill)
    p.drawPath(tri)
    p.setPen(QPen(QColor(255, 255, 255, 70), 6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(tri)

    # top sheen and hairline edge
    sheen = QLinearGradient(0, BODY.top(), 0, BODY.top() + 380)
    sheen.setColorAt(0, QColor(255, 255, 255, 30))
    sheen.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillRect(BODY, sheen)
    p.setClipping(False)
    p.setPen(QPen(QColor(255, 255, 255, 34), 3))
    p.drawRoundedRect(BODY.adjusted(1.5, 1.5, -1.5, -1.5), RADIUS, RADIUS)
    p.end()
    return img


def main() -> int:
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    img = draw()
    png = HERE / "AniGUI.png"
    img.save(str(png))
    try:
        from PIL import Image
    except ImportError:
        print(f"wrote {png} (install Pillow to also write the .icns)")
        return 0
    base = Image.open(png).convert("RGBA")
    sizes = [(s, s) for s in (16, 32, 64, 128, 256, 512, 1024)]
    base.save(HERE / "AniGUI.icns", sizes=sizes)
    print(f"wrote {png} and {HERE / 'AniGUI.icns'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
