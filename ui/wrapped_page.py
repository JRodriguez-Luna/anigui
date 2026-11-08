"""Wrapped (2.0): your year in anime as a few big slides. ← → to move, Save picture to keep one.
Made from what's on this Mac; nobody else sees it unless you share the picture."""

from __future__ import annotations

import datetime as dt
import random
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from core.store import stars
from core.wrapped import Wrapped

from . import theme

NORMAL = (("#FF6B3D", "#7B2FF7"), ("#1D4ED8", "#0EA5E9"), ("#7C3AED", "#DB2777"), ("#0F766E", "#22C55E"),
          ("#B45309", "#F59E0B"), ("#1E293B", "#6366F1"), ("#BE123C", "#F97316"), ("#111827", "#FF6B3D"))
HOLIDAY = (("#B91C1C", "#14532D"), ("#14532D", "#166534"), ("#991B1B", "#DC2626"), ("#065F46", "#B91C1C"))
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def wrapped_year(today: dt.date | None = None) -> int:
    """The year to wrap: this one, or last year until mid-January."""
    today = today or dt.date.today()
    return today.year - 1 if (today.month == 1 and today.day <= 15) else today.year


class WrappedPage(QWidget):
    backRequested = Signal()

    def __init__(self, images, parent=None) -> None:
        super().__init__(parent)
        self.images = images
        self.setObjectName("WrappedPage")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.data: Wrapped | None = None
        self.name = ""
        self.slides: list[str] = []
        self.index = 0
        images.loaded.connect(lambda _u: self.update())

        self.back = QPushButton("‹  Back", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.back.clicked.connect(self.backRequested)
        self.save_btn = QPushButton("Save picture", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.save_btn.setToolTip("Save this slide as a picture you can share")
        self.save_btn.clicked.connect(lambda: self.save_picture())
        self.prev_btn = QPushButton("‹", objectName="WrapArrow", cursor=Qt.CursorShape.PointingHandCursor)
        self.next_btn = QPushButton("›", objectName="WrapArrow", cursor=Qt.CursorShape.PointingHandCursor)
        self.prev_btn.clicked.connect(lambda: self.go(-1))
        self.next_btn.clicked.connect(lambda: self.go(1))
        top = QHBoxLayout()
        top.addWidget(self.back)
        top.addStretch(1)
        top.addWidget(self.save_btn)
        mid = QHBoxLayout()
        mid.addWidget(self.prev_btn)
        mid.addStretch(1)
        mid.addWidget(self.next_btn)
        col = QVBoxLayout(self)
        col.setContentsMargins(28, 24, 28, 24)
        col.addLayout(top)
        col.addStretch(1)
        col.addLayout(mid)
        col.addStretch(1)

    # -- data -----------------------------------------------------------------------------------

    def set_data(self, data: Wrapped, name: str = "") -> None:
        self.data, self.name, self.index = data, " ".join(name.split()), 0
        if data.empty:
            self.slides = ["empty"]
        else:
            self.slides = ["intro", "time", "top"]
            if len(data.top) >= 3:
                self.slides.append("five")
            if data.genres:
                self.slides.append("genre")
            if data.longest_streak >= 2 or data.busiest_day:
                self.slides.append("streak")
            if data.rated or data.lists_made or data.favorite:
                self.slides.append("yours")
            self.slides.append("kind")
        self._buttons()
        self.update()

    def go(self, step: int) -> None:
        self.index = max(0, min(len(self.slides) - 1, self.index + step))
        self._buttons()
        self.update()

    def _buttons(self) -> None:
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < len(self.slides) - 1)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Space):
            self.go(1)
        elif e.key() == Qt.Key.Key_Left:
            self.go(-1)
        elif e.key() == Qt.Key.Key_Escape:
            self.backRequested.emit()
        else:
            super().keyPressEvent(e)

    def save_picture(self, path: str | None = None) -> Path | None:
        if self.data is None:
            return None
        if path is None:
            start = str(Path.home() / "Pictures" / f"AniGUI Wrapped {self.data.year} - {self.index + 1}.png")
            path, _ = QFileDialog.getSaveFileName(self, "Save picture", start, "PNG picture (*.png)")
        if not path:
            return None
        pm = QPixmap(1080, 1350)        # portrait, the size phones like
        p = QPainter(pm)
        self.paint_slide(p, QRectF(0, 0, 1080, 1350), self.slides[self.index], scale=1.45)
        p.end()
        pm.save(path, "PNG")
        return Path(path)

    # -- painting ---------------------------------------------------------------------------------

    def paintEvent(self, _e) -> None:
        if self.data is None:
            return
        p = QPainter(self)
        self.paint_slide(p, QRectF(self.rect()), self.slides[self.index], scale=1.0)
        # where you are
        n = len(self.slides)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            p.setBrush(QColor(255, 255, 255, 230 if i == self.index else 80))
            x = self.width() / 2 + (i - (n - 1) / 2) * 16
            p.drawEllipse(QPointF(x, self.height() - 30), 4, 4)

    def paint_slide(self, p: QPainter, r: QRectF, kind: str, scale: float) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        colors = HOLIDAY if theme.HOLIDAY else NORMAL
        a, b = colors[self.slides.index(kind) % len(colors)] if kind in self.slides else colors[0]
        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        grad.setColorAt(0, QColor(a))
        grad.setColorAt(1, QColor(b))
        p.fillRect(r, grad)
        self._shapes(p, r, kind)
        d, s = self.data, scale
        cx = r.center().x()
        w = min(r.width() - 120 * s, 760 * s)
        left = cx - w / 2

        def text(y, size, words, weight=QFont.Weight.Bold, alpha=255, h=None, color=None):
            p.setFont(theme.font(int(size * s), weight))
            p.setPen(QColor(color) if color else QColor(255, 255, 255, alpha))
            box = QRectF(left, y, w, h or size * s * 1.6)
            p.drawText(box, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, words)

        top = r.top() + r.height() * 0.18
        if kind == "empty":
            text(top + 60 * s, 40, "Not much to wrap yet")
            text(top + 140 * s, 18, "Watch a few episodes in AniGUI and your year in anime shows up here.",
                 QFont.Weight.Medium, 220, 80 * s)
        elif kind == "intro":
            text(top, 22, f"{self.name}, here's your" if self.name else "Here's your", QFont.Weight.DemiBold, 230)
            text(top + 50 * s, 120, str(d.year), QFont.Weight.Black, h=170 * s)
            text(top + 220 * s, 34, "in anime")
            text(top + 300 * s, 15, "Made on your Mac from what AniGUI keeps there. Nobody else sees it.",
                 QFont.Weight.Medium, 190)
        elif kind == "time":
            text(top, 22, "You watched", QFont.Weight.DemiBold, 230)
            text(top + 40 * s, 130, f"{d.hours:,}", QFont.Weight.Black, h=180 * s)
            text(top + 210 * s, 32, "hours of anime" if d.hours != 1 else "hour of anime")
            text(top + 280 * s, 18, f"{d.episodes:,} episodes · {d.shows} shows · {d.days_watched} days",
                 QFont.Weight.DemiBold, 220)
            if d.first_show:
                text(top + 330 * s, 15, f"It started with {d.first_show}.", QFont.Weight.Medium, 190)
        elif kind == "top":
            t = d.top[0]
            text(top - 40 * s, 22, "Your #1 show", QFont.Weight.DemiBold, 230)
            self._poster(p, QRectF(cx - 105 * s, top + 10 * s, 210 * s, 300 * s), t.poster, t.title)
            text(top + 330 * s, 34, t.title, h=100 * s)
            text(top + 430 * s, 18, f"{t.seconds / 3600:.0f} hours · {t.episodes} episodes", QFont.Weight.DemiBold, 220)
        elif kind == "five":
            text(top - 40 * s, 30, "Your top shows")
            y = top + 30 * s
            for i, t in enumerate(d.top[:5], 1):
                row = QRectF(left + 40 * s, y, w - 80 * s, 74 * s)
                p.setFont(theme.font(int(30 * s), QFont.Weight.Black))
                p.setPen(QColor(255, 255, 255, 200))
                p.drawText(QRectF(row.left(), row.top(), 50 * s, row.height()), Qt.AlignmentFlag.AlignVCenter, str(i))
                self._poster(p, QRectF(row.left() + 50 * s, row.top() + 4 * s, 47 * s, 66 * s), t.poster, t.title, small=True)
                p.setFont(theme.font(int(19 * s), QFont.Weight.Bold))
                p.setPen(QColor("#FFFFFF"))
                tx = row.left() + 115 * s
                p.drawText(QRectF(tx, row.top() + 10 * s, row.right() - tx, 28 * s), Qt.AlignmentFlag.AlignVCenter,
                           p.fontMetrics().elidedText(t.title, Qt.TextElideMode.ElideRight, int(row.right() - tx)))
                p.setFont(theme.font(int(14 * s), QFont.Weight.Medium))
                p.setPen(QColor(255, 255, 255, 200))
                p.drawText(QRectF(tx, row.top() + 38 * s, row.right() - tx, 24 * s), Qt.AlignmentFlag.AlignVCenter,
                           f"{t.seconds / 3600:.1f} hours · {t.episodes} episodes")
                y += 86 * s
        elif kind == "genre":
            text(top, 22, "You were all about", QFont.Weight.DemiBold, 230)
            text(top + 50 * s, 80, d.genres[0][0], QFont.Weight.Black, h=130 * s)
            rest = [g for g, _ in d.genres[1:]]
            if rest:
                text(top + 200 * s, 20, "with a side of " + " and ".join(rest), QFont.Weight.DemiBold, 220)
        elif kind == "streak":
            if d.longest_streak >= 2:
                text(top, 22, "Your longest streak", QFont.Weight.DemiBold, 230)
                text(top + 40 * s, 120, str(d.longest_streak), QFont.Weight.Black, h=170 * s)
                text(top + 200 * s, 30, "days in a row")
            if d.busiest_day:
                day, secs = d.busiest_day
                text(top + 290 * s, 18, f"Your biggest day: {day.strftime('%B %-d')} ({secs / 3600:.1f} hours)",
                     QFont.Weight.DemiBold, 225)
            if d.busiest_month:
                text(top + 330 * s, 18, f"Your busiest month: {MONTHS[d.busiest_month[0] - 1]}", QFont.Weight.DemiBold, 225)
        elif kind == "yours":
            text(top - 20 * s, 30, "Made it yours")
            y = top + 50 * s
            if d.favorite:
                title, poster, rating = d.favorite
                self._poster(p, QRectF(cx - 80 * s, y, 160 * s, 228 * s), poster, title)
                text(y + 240 * s, 24, title, h=70 * s)
                text(y + 300 * s, 28, stars(rating), color="#FFD66B")
                y += 360 * s
            bits = []
            if d.rated:
                bits.append(f"rated {d.rated} show{'s' if d.rated != 1 else ''}")
            if d.lists_made:
                bits.append(f"made {d.lists_made} list{'s' if d.lists_made != 1 else ''}")
            if bits:
                text(y, 20, "You " + " and ".join(bits) + ".", QFont.Weight.DemiBold, 225)
        elif kind == "kind":
            what, why = d.kind
            text(top, 22, "This year you were a", QFont.Weight.DemiBold, 230)
            text(top + 50 * s, 84, what, QFont.Weight.Black, h=130 * s)
            text(top + 190 * s, 20, why, QFont.Weight.DemiBold, 225, 70 * s)
            text(top + 290 * s, 26, f"Here's to {d.year + 1}." + (" 🎄" if theme.HOLIDAY else ""))
        p.setFont(theme.font(int(13 * s), QFont.Weight.Bold))
        p.setPen(QColor(255, 255, 255, 150))
        p.drawText(QRectF(r.left(), r.bottom() - 70 * s, r.width(), 20 * s), Qt.AlignmentFlag.AlignHCenter,
                   f"AniGUI Wrapped {d.year}")

    def _shapes(self, p: QPainter, r: QRectF, kind: str) -> None:
        """Soft circles (snow in the holiday theme), the same every time for a slide."""
        rng = random.Random(hash(kind) & 0xFFFF)
        p.setPen(Qt.PenStyle.NoPen)
        if theme.HOLIDAY:
            for _ in range(70):
                x, y, rad = rng.random() * r.width(), rng.random() * r.height(), 1.5 + rng.random() * 3
                p.setBrush(QColor(255, 255, 255, 60 + int(rng.random() * 120)))
                p.drawEllipse(QPointF(r.left() + x, r.top() + y), rad, rad)
            return
        for _ in range(5):
            x, y = rng.random() * r.width(), rng.random() * r.height()
            rad = (0.15 + rng.random() * 0.25) * max(r.width(), r.height())
            p.setBrush(QColor(255, 255, 255, 14))
            p.drawEllipse(QPointF(r.left() + x, r.top() + y), rad, rad)

    def _poster(self, p: QPainter, rect: QRectF, url: str | None, title: str, small: bool = False) -> None:
        path = QPainterPath()
        path.addRoundedRect(rect, 6 if small else 14, 6 if small else 14)
        p.save()
        p.setClipPath(path)
        pm = self.images.pixmap(url, int(rect.width()), int(rect.height())) if url else None
        if pm is not None:
            p.drawPixmap(rect.toRect(), pm)
        else:
            p.fillRect(rect, QColor(255, 255, 255, 40))
            if not small:
                p.setPen(QColor(255, 255, 255, 220))
                p.setFont(theme.font(14, QFont.Weight.Bold))
                p.drawText(rect.adjusted(10, 10, -10, -10), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, title)
        p.restore()
        if not small:      # a little shadow line under it
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 40))
            p.drawRoundedRect(QRectF(rect.left() + 10, rect.bottom() + 6, rect.width() - 20, 6), 3, 3)
