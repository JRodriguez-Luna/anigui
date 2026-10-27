#!/usr/bin/env python3
"""Draw the installer window background (1x and @2x) for the .dmg.

    QT_QPA_PLATFORM=offscreen python packaging/make_dmg_background.py build/

Layout must match packaging/dmg_settings.py: a 660x400 window with the app icon
centred at (170, 190) and the Applications link at (490, 190).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)

W, H = 660, 400
APP_X, LINK_X, ICON_Y = 170, 490, 190


def draw(scale: int) -> QImage:
    img = QImage(W * scale, H * scale, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(scale, scale)

    bg = QLinearGradient(0, 0, W, H)
    bg.setColorAt(0.0, QColor("#22172A"))
    bg.setColorAt(0.6, QColor("#121019"))
    bg.setColorAt(1.0, QColor("#0B0B10"))
    p.fillRect(QRectF(0, 0, W, H), bg)

    glow = QRadialGradient(QPointF(W / 2, ICON_Y), 300)
    glow.setColorAt(0.0, QColor(255, 107, 61, 55))
    glow.setColorAt(1.0, QColor(255, 107, 61, 0))
    p.fillRect(QRectF(0, 0, W, H), glow)

    # Mid-tone shelf under the icons: Finder draws labels black in Light Mode and
    # white in Dark Mode, and both stay readable on this tone.
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#8E8A9B"))
    for x in (APP_X, LINK_X):
        pill = QPainterPath()
        pill.addRoundedRect(QRectF(x - 78, ICON_Y + 64, 156, 36), 18, 18)
        p.drawPath(pill)

    # Arrow from the app to Applications
    arrow = QLinearGradient(APP_X + 85, 0, LINK_X - 85, 0)
    arrow.setColorAt(0, QColor(255, 107, 61, 90))
    arrow.setColorAt(1, QColor("#FF6B3D"))
    pen = QPen(arrow, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    x0, x1, y = APP_X + 88, LINK_X - 92, ICON_Y - 8
    p.drawLine(QPointF(x0, y), QPointF(x1, y))
    p.drawPolyline([QPointF(x1 - 16, y - 15), QPointF(x1, y), QPointF(x1 - 16, y + 15)])

    title = QFont()
    title.setPixelSize(22)
    title.setWeight(QFont.Weight.Bold)
    p.setFont(title)
    p.setPen(QColor("#ECECF1"))
    p.drawText(QRectF(0, 30, W, 32), Qt.AlignmentFlag.AlignHCenter, "Install AniGUI")
    sub = QFont()
    sub.setPixelSize(13)
    p.setFont(sub)
    p.setPen(QColor("#A8A6B6"))
    p.drawText(QRectF(0, 62, W, 22), Qt.AlignmentFlag.AlignHCenter, "Drag AniGUI onto the Applications folder")
    p.setPen(QColor("#7C7A8C"))
    p.drawText(QRectF(0, H - 46, W, 20), Qt.AlignmentFlag.AlignHCenter,
               "Needs ani-cli, fzf and IINA or mpv from Homebrew. See the README.")
    p.end()
    return img


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    draw(1).save(str(out / "dmg-background.png"))
    draw(2).save(str(out / "dmg-background@2x.png"))
    print(out / "dmg-background.png", out / "dmg-background@2x.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
