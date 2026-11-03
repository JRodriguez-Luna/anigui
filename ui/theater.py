"""The show page while the built-in player is playing it: a slot for the video with the
episode list beside it (the video itself floats above, in ui/player_view.PlayerHost), and
in the holiday season lights above it, a garland under it and a little snow around it."""

from __future__ import annotations

import math

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListView, QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from . import festive, theme
from .holiday import SnowLayer
from .motion import reduce_motion

RAIL_W = 300
ROLE = Qt.ItemDataRole.UserRole + 1


class VideoSlot(QWidget):
    """16:9 space on the page where the video goes."""

    moved = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(200)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return int(w * 9 / 16)

    def sizeHint(self) -> QSize:
        return QSize(960, 540)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.moved.emit()

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        self.moved.emit()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#000000"))
        p.drawRoundedRect(QRectF(self.rect()), 10, 10)


class Lights(QWidget):
    """A string of lights hanging above the video."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(22)
        self.t = 0.0
        self._timer = QTimer(self, interval=90)
        self._timer.timeout.connect(self._step)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not reduce_motion():
            self._timer.start()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._timer.stop()

    def _step(self) -> None:
        self.t += 0.09
        self.update()

    def _y(self, x: float, w: float) -> float:
        return 4 + 9 * abs(math.sin(math.pi * x / max(1.0, w / 4)))

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = float(self.width())
        wire = QPainterPath()
        wire.moveTo(-4, self._y(0, w))
        for i in range(1, 81):
            x = w * i / 80
            wire.lineTo(x, self._y(x, w))
        p.setPen(QPen(QColor("#3B4A3F"), 1.5))
        p.drawPath(wire)
        p.setPen(Qt.PenStyle.NoPen)
        n = max(8, int(w // 30))
        for i in range(n):
            x = w * (i + 0.5) / n
            y = self._y(x, w)
            c = QColor(festive.LIGHTS[i % len(festive.LIGHTS)])
            if self._timer.isActive():
                c.setAlphaF(max(0.35, 0.65 + 0.35 * math.sin(self.t * 2.1 + i * 1.9)))
            p.setBrush(QColor("#5A5A5A"))
            p.drawRect(QRectF(x - 1.5, y, 3, 2.5))
            p.setBrush(c)
            p.drawEllipse(QRectF(x - 3, y + 2, 6, 9))


class Garland(QWidget):
    """Pine garland with ornaments under the video."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(18)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = float(self.width())
        path = QPainterPath()
        path.moveTo(0, 6)
        steps = 60
        for i in range(1, steps + 1):
            x = w * i / steps
            path.lineTo(x, 6 + 4 * math.sin(2 * math.pi * x / max(1.0, w / 2)))
        p.setPen(QPen(QColor("#2E7D4F"), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
        p.setPen(QPen(QColor("#1F5C38"), 2, Qt.PenStyle.DotLine))
        p.drawPath(path)
        colors = ("#E0403C", "#F5C64A", "#4FA3E0")
        n = max(5, int(w // 110))
        for i in range(n):
            x = w * (i + 0.5) / n
            y = 6 + 4 * math.sin(2 * math.pi * x / max(1.0, w / 2)) + 5
            if i % 3 == 0:
                festive.ornament(p, QPointF(x, y), 4.2, True)
            else:
                p.setPen(QPen(QColor(255, 255, 255, 120), 1))
                p.setBrush(QColor(colors[i % 3]))
                p.drawEllipse(QPointF(x, y), 4.2, 4.2)


# -- the episode list beside the video ---------------------------------------------------------------

class RailModel(QAbstractListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.items: list[dict] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        if role == ROLE:
            return item
        if role == Qt.ItemDataRole.DisplayRole:
            return f"Episode {item['number']}"
        return None

    def set_items(self, items: list[dict]) -> None:
        self.beginResetModel()
        self.items = items
        self.endResetModel()


class RailDelegate(QStyledItemDelegate):
    H = 64

    def __init__(self, images, parent=None) -> None:
        super().__init__(parent)
        self.images = images

    def sizeHint(self, _option, _index) -> QSize:
        return QSize(RAIL_W - 12, self.H)

    def paint(self, p: QPainter, option, index) -> None:
        item = index.data(ROLE)
        if not item:
            return
        r = QRectF(option.rect).adjusted(2, 3, -2, -3)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        now = item.get("playing")
        if now or hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.SURFACE_2 if now else theme.SURFACE))
            p.drawRoundedRect(r, 8, 8)
        if now:
            mark = QRectF(r.left(), r.top() + 6, 3, r.height() - 12)
            if theme.HOLIDAY:
                festive.progress_bar(p, QRectF(mark.left(), mark.top(), mark.width(), mark.height()), 1.0,
                                     theme.ACCENT)
            else:
                p.fillRect(mark, QColor(theme.ACCENT))
        thumb = QRectF(r.left() + 8, r.top() + 5, 86, r.height() - 10)
        clip = QPainterPath()
        clip.addRoundedRect(thumb, 6, 6)
        p.save()
        p.setClipPath(clip)
        p.fillRect(thumb, QColor(theme.SURFACE_3))
        pm = self.images.pixmap(item.get("still"), int(thumb.width()), int(thumb.height())) if (
            self.images and item.get("still")) else None
        if pm is not None:
            if item.get("watched") and not now:
                p.setOpacity(0.5)
            p.drawPixmap(thumb.toRect(), pm)
            p.setOpacity(1.0)
        else:
            p.setPen(QColor(theme.MUTED))
            p.setFont(theme.font(13, QFont.Weight.Bold))
            p.drawText(thumb, Qt.AlignmentFlag.AlignCenter, str(item["number"]))
        if theme.HOLIDAY:
            cap = QRectF(thumb.left(), thumb.top() - 1, thumb.width(), 4)
            p.fillRect(cap, QColor(festive.SNOW))
        p.restore()
        x = thumb.right() + 10
        if now:
            label, color = f"▶ NOW PLAYING · EP {item['number']}", theme.ACCENT
        elif item.get("watched"):
            label, color = f"✓ EP {item['number']}", theme.GOOD
        else:
            label, color = f"EP {item['number']}", theme.MUTED
        if item.get("christmas") and theme.HOLIDAY:
            label += "  🎄"
        p.setFont(theme.font(10, QFont.Weight.Bold))
        p.setPen(QColor(color))
        p.drawText(QRectF(x, r.top() + 10, r.right() - x - 6, 15), Qt.AlignmentFlag.AlignLeft, label)
        title = item.get("title") or ""
        p.setFont(theme.font(12, QFont.Weight.DemiBold))
        p.setPen(QColor(theme.TEXT if not item.get("watched") or now else theme.MUTED))
        p.drawText(QRectF(x, r.top() + 27, r.right() - x - 6, 18), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, int(r.right() - x - 6)))
        p.restore()


class EpisodeRail(QWidget):
    episodeClicked = Signal(str)

    def __init__(self, images, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(RAIL_W)
        self.heading = QLabel("Episodes", objectName="PanelTitle")
        self.view = QListView(objectName="EpisodeRail")
        self.view.setMouseTracking(True)
        self.view.setUniformItemSizes(True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.model = RailModel(self)
        self.view.setModel(self.model)
        self.view.setItemDelegate(RailDelegate(images, self.view))
        self.view.clicked.connect(lambda idx: self.episodeClicked.emit(str(idx.data(ROLE)["number"])))
        if images is not None:
            images.loaded.connect(lambda *_: self.view.viewport().update())
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        col.addWidget(self.heading)
        col.addWidget(self.view, 1)

    def set_items(self, items: list[dict], heading: str) -> None:
        self.heading.setText(heading)
        self.model.set_items(items)
        for row, item in enumerate(items):
            if item.get("playing"):
                self.view.scrollTo(self.model.index(row), QListView.ScrollHint.PositionAtCenter)
                break


# -- the block --------------------------------------------------------------------------------------

class Theater(QWidget):
    """Top of the show page while the built-in player plays it."""

    back = Signal()
    episodeClicked = Signal(str)
    listToggled = Signal()

    def __init__(self, images, parent=None) -> None:
        super().__init__(parent, objectName="Theater")
        self.back_btn = QPushButton("‹  Back", objectName="Back", cursor=Qt.CursorShape.PointingHandCursor)
        self.back_btn.clicked.connect(self.back)
        self.lights = Lights()
        self.slot = VideoSlot()
        self.garland = Garland()
        self.rail = EpisodeRail(images)
        self.rail.episodeClicked.connect(self.episodeClicked)
        self.ep_title = QLabel("", objectName="TheaterTitle")
        self.ep_title.setTextFormat(Qt.TextFormat.PlainText)
        self.show_title = QLabel("", objectName="Muted")
        self.show_title.setTextFormat(Qt.TextFormat.PlainText)
        self.door_chip = QLabel("", objectName="TheaterChipGreen")
        self.day_chip = QLabel("", objectName="TheaterChip")
        self.list_btn = QPushButton("+  My List", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.list_btn.clicked.connect(self.listToggled)

        left = QVBoxLayout()
        left.setSpacing(0)
        left.addWidget(self.lights)
        left.addWidget(self.slot)
        left.addWidget(self.garland)
        row = QHBoxLayout()
        row.setSpacing(18)
        row.addLayout(left, 1)
        row.addWidget(self.rail, 0)
        info = QHBoxLayout()
        info.setSpacing(10)
        info.addWidget(self.ep_title)
        info.addWidget(self.show_title)
        info.addStretch(1)
        info.addWidget(self.door_chip)
        info.addWidget(self.day_chip)
        info.addWidget(self.list_btn)
        col = QVBoxLayout(self)
        col.setContentsMargins(44, 22, 44, 10)
        col.setSpacing(10)
        col.addWidget(self.back_btn, 0, Qt.AlignmentFlag.AlignLeft)
        col.addLayout(row)
        col.addLayout(info)
        self.snow = SnowLayer(self, flakes=36, alpha=150)
        self.snow.lower()
        self.slot.moved.connect(self._fit_rail)
        self.set_decor(False, False)

    def _fit_rail(self) -> None:
        h = self.slot.height() + (self.lights.height() if self.lights.isVisible() else 0) + (
            self.garland.height() if self.garland.isVisible() else 0)
        self.rail.setFixedHeight(max(220, h))

    def set_decor(self, lights: bool, snow: bool) -> None:
        self.lights.setVisible(lights)
        self.garland.setVisible(lights)
        if snow and self.isVisible():
            self.snow.start()
        elif not snow:
            self.snow.stop()
        self._snow_wanted = snow
        self._fit_rail()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if getattr(self, "_snow_wanted", False):
            self.snow.start()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self.snow.stop()
