"""The show page while the built-in player is playing it: a slot for the video with the
episode list beside it (the video itself floats above, in ui/player_view.PlayerHost), and
in the holiday season lights above it, a garland under it and a little snow around it."""

from __future__ import annotations

import math

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListView, QMenu, QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout,
    QWidget,
)

from . import festive, theme
from .holiday import SnowLayer
from .paintcache import CARDS
from .motion import reduce_motion, scrolling
from .widgets import Combo, PosterWidget, WrapLabel

RAIL_W = 300
ROLE = Qt.ItemDataRole.UserRole + 1


def nice_date(iso: str | None) -> str:
    """'2022-10-14' -> 'Oct 14, 2022' ('' if there isn't one)."""
    import datetime as dt
    try:
        d = dt.date.fromisoformat(str(iso or "")[:10])
    except ValueError:
        return ""
    return f"{d:%b} {d.day}, {d.year}"


class VideoSlot(QWidget):
    """Where the video goes: the page's full width, 16:9, but never taller than the window
    leaves room for (so the title and choices under it are always on screen). When the
    height wins, mpv letterboxes the picture in the middle."""

    moved = Signal()
    bringBack = Signal()   # clicked while the video is popped out
    RESERVE = 170          # the title row and the top of the episode strip stay in view

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.max_h = 10_000
        # Solid black: nothing behind it needs repainting while the video plays over it
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    def set_room(self, viewport_height: int) -> None:
        self.max_h = max(220, int(viewport_height) - self.RESERVE)
        self.updateGeometry()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return min(int(w * 9 / 16), self.max_h)

    def sizeHint(self) -> QSize:
        return QSize(960, 540)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.moved.emit()

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        self.moved.emit()

    def set_popped(self, on: bool) -> None:
        """The video is in its own floating window: say so here, and a click brings it back."""
        self.popped = on
        self.setCursor(Qt.CursorShape.PointingHandCursor if on else Qt.CursorShape.ArrowCursor)
        self.update()

    def mousePressEvent(self, e) -> None:
        if getattr(self, "popped", False) and e.button() == Qt.MouseButton.LeftButton:
            self.bringBack.emit()
        super().mousePressEvent(e)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000000"))
        if getattr(self, "popped", False):
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            c = QPointF(self.rect().center())
            # a small window with an arrow out of it
            p.setPen(QPen(QColor(255, 255, 255, 150), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(c.x() - 26, c.y() - 52, 52, 34), 5, 5)
            p.setBrush(QColor(theme.ACCENT))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(c.x() + 2, c.y() - 36, 22, 15), 3, 3)
            p.setPen(QColor(theme.TEXT))
            p.setFont(theme.font(17, QFont.Weight.Bold))
            p.drawText(QRectF(0, c.y() - 6, self.width(), 26), Qt.AlignmentFlag.AlignCenter,
                       "Playing in the pop-out window")
            p.setPen(QColor(theme.MUTED))
            p.setFont(theme.font(13, QFont.Weight.DemiBold))
            p.drawText(QRectF(0, c.y() + 22, self.width(), 22), Qt.AlignmentFlag.AlignCenter,
                       "Click to bring it back here")


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
        if scrolling():
            return
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
        pm = (self.images.blurred if item.get("shield") else self.images.pixmap)(
            item.get("still"), int(thumb.width()), int(thumb.height())) if (self.images and item.get("still")) else None
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
        if item.get("kind"):
            label += f"  ·  {item['kind'].upper()}"
        if item.get("christmas") and theme.HOLIDAY:
            label += "  🎄"
        p.setFont(theme.font(10, QFont.Weight.Bold))
        p.setPen(QColor(color))
        p.drawText(QRectF(x, r.top() + 10, r.right() - x - 6, 15), Qt.AlignmentFlag.AlignLeft, label)
        title = item.get("title") or ""
        p.setFont(theme.font(12, QFont.Weight.DemiBold))
        p.setPen(QColor(theme.TEXT if not item.get("watched") or now else theme.MUTED))
        p.drawText(QRectF(x, r.top() + 25, r.right() - x - 6, 18), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, int(r.right() - x - 6)))
        if item.get("date"):
            p.setFont(theme.font(10))
            p.setPen(QColor(theme.FAINT))
            p.drawText(QRectF(x, r.top() + 42, r.right() - x - 6, 14), Qt.AlignmentFlag.AlignLeft, item["date"])
        p.restore()


class EpisodeRail(QFrame):
    """The show's episodes beside the video: what's playing, what's watched, filler tags.
    Find one, sort, hide watched; right-click to mark watched."""

    episodeClicked = Signal(str)
    markRequested = Signal(str, str)     # episode, "watched" | "unwatched" | "upto"
    fillersToggled = Signal(str, bool)   # "hide_fillers" | "skip_fillers", on

    def __init__(self, images, parent=None) -> None:
        super().__init__(parent, objectName="RailPanel")
        self.setFixedWidth(RAIL_W)
        self.all_items: list[dict] = []
        self.newest_first = False
        self.hide_watched = False
        self.heading = QLabel("Episodes", objectName="PanelTitle")
        self.count = QLabel("", objectName="Muted")
        self.find = QLineEdit(objectName="RailFind", placeholderText="Find an episode", clearButtonEnabled=True)
        self.find.textChanged.connect(lambda _t: self._apply())
        self.sort_btn = QPushButton("↑↓", objectName="RailTool", checkable=True, cursor=Qt.CursorShape.PointingHandCursor)
        self.sort_btn.setToolTip("Newest first")
        self.sort_btn.toggled.connect(self._set_sort)
        self.watched_btn = QPushButton("Hide watched", objectName="RailTool", checkable=True,
                                       cursor=Qt.CursorShape.PointingHandCursor)
        self.watched_btn.toggled.connect(self._set_hide_watched)
        self.filler_btn = QPushButton("Fillers ▾", objectName="RailTool", cursor=Qt.CursorShape.PointingHandCursor)
        self.filler_btn.clicked.connect(self._filler_menu)
        self.filler_btn.setVisible(False)
        self.filler_prefs = {"hide_fillers": False, "skip_fillers": False}
        self.view = QListView(objectName="EpisodeRail")
        self.view.setMouseTracking(True)
        self.view.setUniformItemSizes(True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.model = RailModel(self)
        self.view.setModel(self.model)
        self.view.setItemDelegate(RailDelegate(images, self.view))
        self.view.clicked.connect(lambda idx: self.episodeClicked.emit(str(idx.data(ROLE)["number"])))
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        if images is not None:
            images.loaded.connect(lambda *_: self.view.viewport().update())
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(self.heading)
        head.addWidget(self.count)
        head.addStretch(1)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        tools.addWidget(self.watched_btn)
        tools.addWidget(self.filler_btn)
        tools.addStretch(1)
        tools.addWidget(self.sort_btn)
        col = QVBoxLayout(self)
        col.setContentsMargins(10, 10, 6, 8)
        col.setSpacing(8)
        col.addLayout(head)
        col.addWidget(self.find)
        col.addLayout(tools)
        col.addWidget(self.view, 1)

    def set_items(self, items: list[dict], heading: str, has_fillers: bool = False) -> None:
        self.heading.setText(heading)
        self.all_items = items
        self.filler_btn.setVisible(has_fillers)
        current = next((i for i in items if i.get("playing")), None)
        done = sum(1 for i in items if i.get("watched"))
        where = f"{current['number']} / {len(items)}" if current else f"{done} / {len(items)} watched"
        self.count.setText(where if items else "")
        self._apply(scroll=True)

    def visible_items(self) -> list[dict]:
        return list(self.model.items)

    def _apply(self, scroll: bool = False) -> None:
        text = self.find.text().strip().lower()
        items = list(self.all_items)
        if self.hide_watched:
            items = [i for i in items if not i.get("watched") or i.get("playing")]
        if self.filler_prefs.get("hide_fillers"):
            items = [i for i in items if not i.get("kind") or i.get("playing")]
        if text:
            items = [i for i in items if text == str(i["number"]).lower() or text in str(i.get("title", "")).lower()
                     or str(i["number"]).startswith(text)]
        if self.newest_first:
            items.reverse()
        self.model.set_items(items)
        if scroll or not text:
            for row, item in enumerate(items):
                if item.get("playing"):
                    self.view.scrollTo(self.model.index(row), QListView.ScrollHint.PositionAtCenter)
                    break

    def _set_sort(self, on: bool) -> None:
        self.newest_first = on
        self._apply()

    def _set_hide_watched(self, on: bool) -> None:
        self.hide_watched = on
        self._apply()

    def _filler_menu(self) -> None:
        menu = QMenu(self)
        for key, label in (("hide_fillers", "Hide fillers"), ("skip_fillers", "Skip fillers when auto-playing")):
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(bool(self.filler_prefs.get(key)))
            act.toggled.connect(lambda on, k=key: self.fillersToggled.emit(k, on))
        menu.exec(self.filler_btn.mapToGlobal(self.filler_btn.rect().bottomLeft()))

    def _menu(self, pos) -> None:
        idx = self.view.indexAt(pos)
        if not idx.isValid():
            return
        item = idx.data(ROLE)
        number = str(item["number"])
        menu = QMenu(self)
        if item.get("watched"):
            menu.addAction("Mark as unwatched", lambda: self.markRequested.emit(number, "unwatched"))
        else:
            menu.addAction("Mark as watched", lambda: self.markRequested.emit(number, "watched"))
        menu.addAction(f"Mark episodes up to {number} as watched", lambda: self.markRequested.emit(number, "upto"))
        menu.exec(self.view.viewport().mapToGlobal(pos))


class StripDelegate(QStyledItemDelegate):
    W, H = 176, 99

    def __init__(self, images, parent=None) -> None:
        super().__init__(parent)
        self.images = images

    def sizeHint(self, _option, _index) -> QSize:
        return QSize(self.W + 12, self.H + 26)

    def paint(self, p: QPainter, option, index) -> None:
        item = index.data(ROLE)
        if not item:
            return
        r = QRectF(option.rect)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        try:
            key = ("strip", tuple(sorted(item.items())))
            hash(key)
        except TypeError:
            key = None
        if hover or key is None:
            self._draw(p, r, item, hover)
            return
        CARDS.draw(p, r, key, lambda q, rr: self._draw(q, rr, item, False))

    def _draw(self, p: QPainter, r: QRectF, item: dict, hover: bool) -> bool:
        thumb = QRectF(r.left() + 6, r.top() + 2, self.W, self.H)
        now = item.get("playing")
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(thumb, 8, 8)
        p.save()
        p.setClipPath(clip)
        p.fillRect(thumb, QColor(theme.SURFACE_3))
        pm = (self.images.blurred if item.get("shield") else self.images.pixmap)(
            item.get("still"), int(thumb.width()), int(thumb.height())) if (self.images and item.get("still")) else None
        final = pm is not None or not item.get("still")
        if pm is not None:
            p.drawPixmap(thumb.toRect(), pm)
        else:
            p.setPen(QColor(theme.MUTED))
            p.setFont(theme.font(18, QFont.Weight.Bold))
            p.drawText(thumb, Qt.AlignmentFlag.AlignCenter, str(item["number"]))
        if theme.HOLIDAY:
            p.fillRect(QRectF(thumb.left(), thumb.top(), thumb.width(), 4), QColor(festive.SNOW))
        if item.get("watched") and not now:
            p.fillRect(QRectF(thumb.left(), thumb.bottom() - 4, thumb.width(), 4), QColor(theme.GOOD))
        if hover and not now:
            p.fillRect(thumb, QColor(255, 255, 255, 24))
        p.restore()
        if now:
            p.setPen(QPen(QColor(theme.ACCENT), 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(thumb.adjusted(1, 1, -1, -1), 8, 8)
        label = (f"▶ Now · Ep {item['number']}" if now else f"Ep {item['number']}")
        if item.get("kind"):
            label += f" · {item['kind'].title()}"
        if item.get("christmas") and theme.HOLIDAY:
            label += " 🎄"
        title = item.get("title") or ""
        p.setFont(theme.font(11, QFont.Weight.Bold))
        p.setPen(QColor(theme.ACCENT if now else (theme.TEXT if hover else theme.MUTED)))
        text = f"{label}  {title}" if title else label
        p.drawText(QRectF(thumb.left(), thumb.bottom() + 5, thumb.width(), 16), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(thumb.width())))
        p.restore()
        return final


class EpisodeStrip(QListView):
    """The season's episodes as a sideways strip of thumbnails under the video."""

    episodeClicked = Signal(str)

    def __init__(self, images, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("EpisodeStrip")
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(StripDelegate.H + 26 + 14)
        self.model_ = RailModel(self)
        self.setModel(self.model_)
        self.setItemDelegate(StripDelegate(images, self))
        self.clicked.connect(lambda idx: self.episodeClicked.emit(str(idx.data(ROLE)["number"])))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if images is not None:
            images.loaded.connect(lambda *_: self.viewport().update())

    def set_items(self, items: list[dict]) -> None:
        self.model_.set_items(items)
        for row, item in enumerate(items):
            if item.get("playing"):
                self.scrollTo(self.model_.index(row), QListView.ScrollHint.PositionAtCenter)
                break

    def wheelEvent(self, e) -> None:
        # a mouse wheel scrolls the strip sideways; a trackpad's sideways swipe already does
        if abs(e.angleDelta().y()) > abs(e.angleDelta().x()) and not e.pixelDelta().x():
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - e.angleDelta().y())
            e.accept()
            return
        super().wheelEvent(e)


# -- the block --------------------------------------------------------------------------------------

class Theater(QWidget):
    """Top of the show page while the built-in player plays it (Full bleed): the video edge to
    edge, sized to the window; under it the episode (title, date, Sub/Dub, quality), a strip of
    the season's episodes, and the show (poster, My Library, the episode's summary). The full
    list with search and filters slides in over the video (☰ / E). The page's Seasons row,
    Related and You might also like follow; its episode grid steps aside."""

    episodeClicked = Signal(str)
    listToggled = Signal()
    dubChanged = Signal(bool)
    qualityChanged = Signal(str)
    openOutside = Signal(str)            # "iina" | "mpv"

    def __init__(self, images, qualities=(), parent=None) -> None:
        super().__init__(parent, objectName="Theater")
        self.lights = Lights()
        self.slot = VideoSlot()
        self.garland = Garland()
        self.rail = EpisodeRail(images)            # (shown in the player's drawer: ☰ or E)
        self.rail.episodeClicked.connect(self.episodeClicked)
        self.strip_title = QLabel("Episodes", objectName="SectionTitle")
        self.strip_count = QLabel("", objectName="Muted")
        self.all_btn = QPushButton("☰  All episodes", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.all_btn.setToolTip("The full list, with search and filters (E)")
        self.strip = EpisodeStrip(images)
        self.strip.episodeClicked.connect(self.episodeClicked)

        # the episode
        self.ep_meta = QLabel("", objectName="Muted")
        self.ep_title = QLabel("", objectName="TheaterTitle", wordWrap=True)
        self.ep_title.setTextFormat(Qt.TextFormat.PlainText)
        self.door_chip = QLabel("", objectName="TheaterChipGreen")
        self.day_chip = QLabel("", objectName="TheaterChip")
        self.audio = Combo(cursor=Qt.CursorShape.PointingHandCursor)
        self.audio.addItem("Sub", False)
        self.audio.addItem("Dub", True)
        self.audio.setToolTip("Japanese audio with subtitles, or the English dub")
        self.audio.currentIndexChanged.connect(lambda _i: self.dubChanged.emit(bool(self.audio.currentData())))
        self.quality = Combo(cursor=Qt.CursorShape.PointingHandCursor)
        for label, value in qualities:
            self.quality.addItem(label, value)
        self.quality.setToolTip("Stream quality (falls back to best if unavailable)")
        self.quality.currentIndexChanged.connect(lambda _i: self.qualityChanged.emit(str(self.quality.currentData())))
        self.more = QPushButton("⋯", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.more.setToolTip("More")
        self.more.clicked.connect(self._more_menu)

        # the show
        self.card = QFrame(objectName="ShowCard")
        self.poster = PosterWidget(images, 58, 84)
        self.show_title = QLabel("", objectName="ShowCardTitle")
        self.show_title.setTextFormat(Qt.TextFormat.PlainText)
        self.show_meta = QLabel("", objectName="Muted")
        self.show_meta.setTextFormat(Qt.TextFormat.PlainText)
        self.list_btn = QPushButton("+  Save", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.list_btn.clicked.connect(self.listToggled)
        self.summary = WrapLabel("", 900, objectName="Synopsis")
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.more_text = QPushButton("Show more ▾", objectName="LinkButton", cursor=Qt.CursorShape.PointingHandCursor)
        self.more_text.clicked.connect(self._toggle_summary)
        self._summary_full = ""
        self._expanded = False


        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self.ep_meta)
        titles.addWidget(self.ep_title)
        info = QHBoxLayout()
        info.setSpacing(8)
        info.addLayout(titles, 1)
        for w in (self.door_chip, self.day_chip, self.audio, self.quality, self.more):
            info.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)

        card_text = QVBoxLayout()
        card_text.setSpacing(4)
        top = QHBoxLayout()
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addWidget(self.show_title)
        names.addWidget(self.show_meta)
        top.addLayout(names, 1)
        top.addWidget(self.list_btn, 0, Qt.AlignmentFlag.AlignTop)
        card_text.addLayout(top)
        card_text.addSpacing(4)
        card_text.addWidget(self.summary)
        card_text.addWidget(self.more_text, 0, Qt.AlignmentFlag.AlignLeft)
        card = QHBoxLayout(self.card)
        card.setContentsMargins(14, 12, 14, 12)
        card.setSpacing(14)
        card.addWidget(self.poster, 0, Qt.AlignmentFlag.AlignTop)
        card.addLayout(card_text, 1)

        strip_head = QHBoxLayout()
        strip_head.setSpacing(10)
        strip_head.addWidget(self.strip_title)
        strip_head.addWidget(self.strip_count, 0, Qt.AlignmentFlag.AlignBottom)
        strip_head.addStretch(1)
        strip_head.addWidget(self.all_btn)

        under = QVBoxLayout()
        under.setContentsMargins(44, 14, 44, 10)
        under.setSpacing(12)
        under.addLayout(info)
        under.addSpacing(4)
        under.addLayout(strip_head)
        under.addWidget(self.strip)
        under.addWidget(self.card)

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self.lights)
        col.addWidget(self.slot)
        col.addWidget(self.garland)
        col.addLayout(under)
        self.snow = SnowLayer(self, flakes=36, alpha=150)
        self.snow.lower()
        self.set_decor(False, False)

    # -- the episode and the show ---------------------------------------------------------

    def set_summary(self, text: str) -> None:
        self._summary_full = text or ""
        self._expanded = False
        self._show_summary()

    def _show_summary(self) -> None:
        text = self._summary_full
        long = len(text) > 260
        shown = text if self._expanded or not long else text[:240].rsplit(" ", 1)[0] + "…"
        self.summary.setText(shown)
        self.summary.setVisible(bool(text))
        self.more_text.setVisible(long)
        self.more_text.setText("Show less ▴" if self._expanded else "Show more ▾")

    def _toggle_summary(self) -> None:
        self._expanded = not self._expanded
        self._show_summary()

    def set_choices(self, dub: bool, quality: str) -> None:
        for combo, value in ((self.audio, dub), (self.quality, quality)):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.blockSignals(False)

    def _more_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Open in IINA", lambda: self.openOutside.emit("iina"))
        menu.addAction("Open in mpv", lambda: self.openOutside.emit("mpv"))
        menu.exec(self.more.mapToGlobal(self.more.rect().bottomLeft()))

    def set_episodes(self, items: list[dict], heading: str, has_fillers: bool = False) -> None:
        self.rail.set_items(items, heading, has_fillers=has_fillers)
        self.strip.set_items(items)
        self.strip_title.setText(heading)
        self.strip_count.setText(self.rail.count.text())

    def set_decor(self, lights: bool, snow: bool) -> None:
        self.lights.setVisible(lights)
        self.garland.setVisible(lights)
        if snow and self.isVisible():
            self.snow.start()
        elif not snow:
            self.snow.stop()
        self._snow_wanted = snow

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if getattr(self, "_snow_wanted", False):
            self.snow.start()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self.snow.stop()
