"""The show page's episode grid: still cards, filler badges, pages for long shows, Jump to episode."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIntValidator, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractButton, QHBoxLayout, QLabel, QLineEdit, QListView, QMenu, QPushButton, QSizePolicy, QStyle,
    QStyledItemDelegate, QWidget,
)

from . import theme
from .images import ImageLoader

EP_ROLE = Qt.ItemDataRole.UserRole + 2
PER_PAGE = 100          # shows with more episodes than this get page tabs
FILLER_BG, FILLER_TEXT = "#E9B44C", "#2B1D04"
RECAP_BG, RECAP_TEXT = "#4A4A58", "#E4E4EC"


@dataclass(frozen=True)
class EpisodeItem:
    number: str
    title: str | None
    state: str = "new"        # new | progress | watched
    fraction: float = 0.0
    busy: str | None = None   # status text while resolving
    up_next: bool = False
    playing: bool = False
    still: str | None = None  # thumbnail URL, if one was found
    hit: bool = False         # just jumped to
    kind: str | None = None   # "filler" | "recap" (Anime Filler List), None = story episode
    upcoming: str | None = None  # "Thu 9:30 PM · in 3d 4h": the next episode, not out yet


class EpisodeModel(QAbstractListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.items: list[EpisodeItem] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        if role == EP_ROLE:
            return item
        if role == Qt.ItemDataRole.ToolTipRole:
            note = {"filler": " (filler)", "recap": " (recap)"}.get(item.kind or "", "")
            return f"Episode {item.number}" + (f": {item.title}" if has_title(item) else "") + note
        return None

    def set_items(self, items: list[EpisodeItem]) -> None:
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def row_of(self, number: str) -> int | None:
        return next((row for row, item in enumerate(self.items) if item.number == number), None)

    def _change(self, row: int, **changes) -> None:
        self.items[row] = replace(self.items[row], **changes)
        self.dataChanged.emit(self.index(row), self.index(row))

    def update_progress(self, number: str, state: str, fraction: float, playing: bool | None = None) -> None:
        row = self.row_of(number)
        if row is not None:
            changes = {"state": state, "fraction": fraction}
            if playing is not None:
                changes["playing"] = playing
            self._change(row, **changes)

    def set_busy(self, number: str | None, text: str | None = None) -> None:
        for row, item in enumerate(self.items):
            busy = text if item.number == number else None
            if item.busy != busy:
                self._change(row, busy=busy)

    def set_stills(self, stills: dict[str, str]) -> None:
        for row, item in enumerate(self.items):
            url = stills.get(item.number)
            if url and url != item.still:
                self._change(row, still=url)


def coming_soon(number: int, airing_at: int, now: float | None = None) -> EpisodeItem | None:
    """The faded 'Coming soon' card for the next episode of an airing show."""
    import datetime as dt
    import time

    left = airing_at - (time.time() if now is None else now)
    if left <= 0:
        return None
    when = dt.datetime.fromtimestamp(airing_at)
    hour = when.strftime("%I:%M %p").lstrip("0")
    days, rest = divmod(int(left), 86400)
    hours, minutes = rest // 3600, rest % 3600 // 60
    soon = f"in {days}d {hours}h" if days else (f"in {hours}h {minutes}m" if hours else f"in {max(1, minutes)}m")
    return EpisodeItem(number=str(number), title="Coming soon", upcoming=f"{when:%a} {hour} · {soon}")


def has_title(item: EpisodeItem) -> bool:
    t = (item.title or "").strip()
    return bool(t) and t.lower() != f"episode {item.number}".lower()


def page_ranges(numbers: list[str], per_page: int = PER_PAGE) -> list[tuple[int, int, str]]:
    """(start index, end index, label) for each page, e.g. (100, 200, '101–200')."""
    pages = []
    for start in range(0, len(numbers), per_page):
        end = min(len(numbers), start + per_page)
        pages.append((start, end, f"{numbers[start]}–{numbers[end - 1]}"))
    return pages


def visible_tabs(count: int, current: int) -> list[int | None]:
    """Which page tabs to show (None = '…'): the first four, the last, and the current ±1."""
    shown: list[int | None] = []
    for i in range(count):
        if i < 4 or i == count - 1 or abs(i - current) <= 1:
            shown.append(i)
        elif shown and shown[-1] is not None:
            shown.append(None)
    return shown


def find_episode(numbers: list[str], text: str) -> int | None:
    """Index of the episode the user typed ('7', '007' and '7.0' all find '7')."""
    text = text.strip()
    if text in numbers:
        return numbers.index(text)
    try:
        value = float(text)
    except ValueError:
        return None
    for i, n in enumerate(numbers):
        try:
            if float(n) == value:
                return i
        except ValueError:
            continue
    return None


class EpisodeDelegate(QStyledItemDelegate):
    MIN_W, MAX_W = 200, 280   # cards stretch between these to fill each row
    W = MIN_W
    TEXT_H = 48
    RADIUS = 10

    def __init__(self, images: ImageLoader | None, parent=None) -> None:
        super().__init__(parent)
        self.images = images
        self.tile_color = QColor(theme.SURFACE_2)   # the show's color, for episodes without a still
        self.tile_art: str | None = None              # the show's banner, behind the number on those
        self.small = theme.font(11, QFont.Weight.Bold)
        self.title = theme.font(13)
        self.big = theme.font(34, QFont.Weight.Black)
        self.set_width(self.MIN_W)

    def set_width(self, w: int) -> bool:
        w = max(self.MIN_W, min(self.MAX_W, int(w)))
        changed = w != getattr(self, "W", None) or not hasattr(self, "H")
        self.W = w
        self.STILL_H = round(w * 9 / 16)
        self.H = self.STILL_H + self.TEXT_H
        return changed

    def sizeHint(self, option, index) -> QSize:
        return QSize(self.W, self.H)

    def paint(self, p: QPainter, option, index) -> None:
        item: EpisodeItem = index.data(EP_ROLE)
        if item is None:
            return
        r = QRectF(option.rect.x(), option.rect.y(), self.W, self.H).adjusted(1, 1, -1, -1)
        if item.upcoming:
            self._paint_upcoming(p, r, item)
            return
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        watched = item.state == "watched"
        lit = item.up_next or item.playing or bool(item.busy)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        card = QPainterPath()
        card.addRoundedRect(r, self.RADIUS, self.RADIUS)
        p.fillPath(card, QColor(theme.SURFACE_2 if hover else theme.SURFACE))
        p.setClipPath(card)

        # Still (or the numbered tile)
        still = QRectF(r.left(), r.top(), r.width(), self.STILL_H - 1)
        if watched and not item.playing:
            p.setOpacity(0.42)
        elif item.kind and not (item.playing or item.up_next):
            p.setOpacity(0.8)      # fillers step back a little so story episodes stand out
        pm = self.images.pixmap(item.still, self.W - 2, self.STILL_H - 1) if (self.images and item.still) else None
        if pm is not None:
            p.drawPixmap(still.toRect(), pm)
        else:
            self._tile(p, still, item.number)
        p.setOpacity(1.0)

        if item.state == "progress" or (item.playing and item.fraction > 0):
            bar = QRectF(still.left(), still.bottom() - 3, still.width(), 3)
            p.fillRect(bar, QColor(255, 255, 255, 60))
            p.fillRect(QRectF(bar.left(), bar.top(), bar.width() * max(0.04, min(1.0, item.fraction)), 3),
                       QColor(theme.ACCENT))

        if item.kind in ("filler", "recap"):
            self._kind_badge(p, still, item.kind)

        if hover and not item.busy:
            p.fillRect(still, QColor(0, 0, 0, 90))
            self._play_button(p, still.center())

        # Text
        inner = QRectF(r.left() + 11, still.bottom() + 7, r.width() - 22, self.TEXT_H - 12)
        if item.playing:
            label, color = f"▶ NOW PLAYING · EP {item.number}", theme.ACCENT
        elif item.up_next:
            label, color = f"UP NEXT · EP {item.number}", theme.ACCENT
        elif watched:
            label, color = f"✓ EP {item.number}", theme.GOOD
        else:
            label, color = f"EP {item.number}", theme.MUTED
        p.setFont(self.small)
        p.setPen(QColor(color))
        p.drawText(QRectF(inner.left(), inner.top(), inner.width(), 15), Qt.AlignmentFlag.AlignLeft, label)

        text = item.busy or (item.title if has_title(item) else "")
        if text:
            p.setFont(self.title)
            p.setPen(QColor(theme.ACCENT if item.busy else (theme.MUTED if watched else theme.TEXT)))
            text = p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(inner.width()))
            p.drawText(QRectF(inner.left(), inner.top() + 16, inner.width(), 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        p.setClipping(False)

        # Border
        if lit or item.hit or hover:
            pen = QPen(QColor(theme.ACCENT if lit else (theme.TEXT if item.hit else theme.FAINT)), 2 if (lit or item.hit) else 1)
        else:
            pen = QPen(QColor(theme.BORDER), 1)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        inset = pen.widthF() / 2
        p.drawRoundedRect(r.adjusted(inset, inset, -inset, -inset), self.RADIUS, self.RADIUS)
        p.restore()

    def _tile(self, p: QPainter, rect: QRectF, number: str) -> None:
        """No still for this episode: the show's banner, darkened, with the episode number."""
        base = QColor(self.tile_color)
        art = self.images.pixmap(self.tile_art, self.W - 2, self.STILL_H - 1) if (self.images and self.tile_art) else None
        if art is not None:
            p.drawPixmap(rect.toRect(), art)
            p.fillRect(rect, QColor(8, 8, 12, 165))
            p.setPen(QColor(255, 255, 255, 235))
        else:
            p.fillRect(rect, base.darker(260))
            p.setPen(base.lighter(150) if base.lightness() < 140 else base)
        p.setFont(self.big)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, number)

    def _paint_upcoming(self, p: QPainter, r: QRectF, item: EpisodeItem) -> None:
        """A faded card with a dashed border: the next episode and when it airs."""
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QPainterPath()
        card.addRoundedRect(r, self.RADIUS, self.RADIUS)
        p.fillPath(card, QColor(theme.BG))
        p.setClipPath(card)
        still = QRectF(r.left(), r.top(), r.width(), self.STILL_H - 1)
        p.setOpacity(0.35)
        self._tile(p, still, item.number)
        p.setOpacity(1.0)
        p.setFont(self.small)
        p.setPen(QColor(theme.ACCENT_HOVER))
        pill_text = "COMING SOON"
        w = p.fontMetrics().horizontalAdvance(pill_text) + 14
        pill = QRectF(still.center().x() - w / 2, still.bottom() - 30, w, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(10, 10, 15, 200))
        p.drawRoundedRect(pill, 6, 6)
        p.setPen(QColor(theme.ACCENT_HOVER))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, pill_text)
        inner = QRectF(r.left() + 11, still.bottom() + 7, r.width() - 22, self.TEXT_H - 12)
        p.setPen(QColor(theme.FAINT))
        p.drawText(QRectF(inner.left(), inner.top(), inner.width(), 15), Qt.AlignmentFlag.AlignLeft, f"EP {item.number}")
        p.setFont(self.title)
        p.setPen(QColor(theme.MUTED))
        text = p.fontMetrics().elidedText(item.upcoming or "", Qt.TextElideMode.ElideRight, int(inner.width()))
        p.drawText(QRectF(inner.left(), inner.top() + 16, inner.width(), 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        p.setClipping(False)
        p.setPen(QPen(QColor(theme.FAINT), 1, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), self.RADIUS, self.RADIUS)
        p.restore()

    def _kind_badge(self, p: QPainter, still: QRectF, kind: str) -> None:
        text = kind.upper()
        bg, fg = (FILLER_BG, FILLER_TEXT) if kind == "filler" else (RECAP_BG, RECAP_TEXT)
        p.setFont(self.small)
        w = p.fontMetrics().horizontalAdvance(text) + 12
        pill = QRectF(still.left() + 8, still.top() + 8, w, 19)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(bg))
        p.drawRoundedRect(pill, 5, 5)
        p.setPen(QColor(fg))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def _play_button(p: QPainter, center: QPointF) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        p.drawEllipse(center, 20, 20)
        p.setBrush(QColor("#FFFFFF"))
        x, y = center.x() + 2, center.y()
        p.drawPolygon(QPolygonF([QPointF(x - 6, y - 8), QPointF(x - 6, y + 8), QPointF(x + 8, y)]))


class EpisodeGrid(QListView):
    """Wrapping grid that grows to fit its content, so the whole page scrolls as one."""

    episodeClicked = Signal(str)
    markRequested = Signal(str, str)  # episode, "watched" | "unwatched" | "upto"
    SPACING = 6

    def __init__(self, images: ImageLoader | None = None, parent=None) -> None:
        super().__init__(parent)
        self.model_ = EpisodeModel(self)
        self.setModel(self.model_)
        self.delegate = EpisodeDelegate(images, self)
        self.setItemDelegate(self.delegate)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(self.SPACING)
        self.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._clicked)
        self.model_.modelReset.connect(self._fit)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        if images is not None:
            images.loaded.connect(lambda _url: self.viewport().update())

    def _clicked(self, idx) -> None:
        item: EpisodeItem = idx.data(EP_ROLE)
        if item is not None and not item.upcoming:   # Coming soon isn't playable yet
            self.episodeClicked.emit(item.number)

    def set_tile_color(self, color: str | None, art: str | None = None) -> None:
        self.delegate.tile_color = QColor(color) if color and QColor(color).isValid() else QColor(theme.SURFACE_2)
        self.delegate.tile_art = art
        self.viewport().update()

    def _menu(self, pos) -> None:
        index = self.indexAt(pos)
        if not index.isValid():
            return
        item: EpisodeItem = index.data(EP_ROLE)
        if item.upcoming:
            return
        menu = QMenu(self)
        if item.state == "watched":
            menu.addAction("Mark as unwatched", lambda: self.markRequested.emit(item.number, "unwatched"))
        else:
            menu.addAction("Mark as watched", lambda: self.markRequested.emit(item.number, "watched"))
        menu.addAction(f"Mark episodes up to {item.number} as watched", lambda: self.markRequested.emit(item.number, "upto"))
        menu.exec(self.viewport().mapToGlobal(pos))

    def wheelEvent(self, event) -> None:
        event.ignore()  # the page scrolls, not the grid

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        """Stretch the cards so each row fills the width, then grow to fit every row."""
        d, gap = self.delegate, 2 * self.SPACING
        avail = self.viewport().width() - gap
        per_row = max(1, (avail + gap) // (d.MIN_W + gap))
        if d.set_width((avail + gap) // per_row - gap - 1):
            self.scheduleDelayedItemsLayout()
        per_row = max(1, (avail + gap) // (d.W + gap))
        rows = math.ceil(len(self.model_.items) / per_row) if self.model_.items else 0
        self.setFixedHeight(rows * (d.H + gap) + 4)


class Switch(QAbstractButton):
    """A pill with a small on/off track and a label, like the toggles in the concept."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.font_ = theme.font(12, QFont.Weight.DemiBold)
        self.setFont(self.font_)

    def sizeHint(self) -> QSize:
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 58, 30)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hover = self.underMouse()
        p.setPen(QPen(QColor(theme.FAINT if (hover or self.hasFocus()) else theme.BORDER), 1))
        p.setBrush(QColor(theme.SURFACE))
        p.drawRoundedRect(r, 7, 7)
        track = QRectF(r.left() + 10, r.center().y() - 7.5, 26, 15)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.ACCENT if self.isChecked() else "#3A3A48"))
        p.drawRoundedRect(track, 7.5, 7.5)
        p.setBrush(QColor(theme.TEXT))
        knob_x = track.right() - 7.5 if self.isChecked() else track.left() + 7.5
        p.drawEllipse(QPointF(knob_x, track.center().y()), 5.5, 5.5)
        p.setPen(QColor(theme.TEXT if (hover or self.isChecked()) else theme.MUTED))
        p.setFont(self.font_)
        p.drawText(QRectF(track.right() + 8, r.top(), r.width(), r.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
        p.end()


class EpisodePager(QWidget):
    """Above the grid: page tabs (1–100 · 101–200 · …) and Jump to episode for long shows,
    and the Hide fillers / Skip fillers switches for shows with fillers."""

    pageChosen = Signal(int)
    jumpRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.tabs = QHBoxLayout()
        self.tabs.setSpacing(6)
        self.jump = QLineEdit(placeholderText="Jump to episode", objectName="JumpBox")
        self.jump.setValidator(QIntValidator(1, 99999, self.jump))
        self.jump.setFixedWidth(150)
        self.jump.setClearButtonEnabled(True)
        self.jump.returnPressed.connect(lambda: self.jump.text().strip() and self.jumpRequested.emit(self.jump.text()))
        self.jump.textEdited.connect(lambda _t: self.set_error(""))
        self.error = QLabel("", objectName="JumpError")
        self.hide_fillers = Switch("Hide fillers")
        self.hide_fillers.setToolTip("Leave filler episodes out of this list")
        self.skip_fillers = Switch("Skip fillers")
        self.skip_fillers.setToolTip("Up Next and auto-play jump over filler episodes "
                                     "(also in Settings → Playback)")
        row = QHBoxLayout(self)
        row.setContentsMargins(5, 0, 5, 0)
        row.setSpacing(10)
        row.addLayout(self.tabs)
        row.addStretch(1)
        row.addWidget(self.error)
        row.addWidget(self.hide_fillers)
        row.addWidget(self.skip_fillers)
        row.addWidget(self.jump)
        self.buttons: dict[int, QPushButton] = {}

    def configure(self, paged: bool, fillers: bool) -> None:
        """Show only what applies: tabs and jump for long shows, switches for shows with fillers."""
        self.jump.setVisible(paged)
        self.error.setVisible(paged)
        self.hide_fillers.setVisible(fillers)
        self.skip_fillers.setVisible(fillers)
        if not paged:
            self.set_pages([], 0)
        self.setVisible(paged or fillers)

    def set_pages(self, labels: list[str], current: int) -> None:
        while self.tabs.count():
            w = self.tabs.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.buttons = {}
        for i in visible_tabs(len(labels), current):
            if i is None:
                gap = QLabel("…", objectName="Muted")
                self.tabs.addWidget(gap)
                continue
            btn = QPushButton(labels[i], objectName="PageTab", checkable=True,
                              cursor=Qt.CursorShape.PointingHandCursor)
            btn.setChecked(i == current)
            btn.clicked.connect(lambda _c=False, i=i: self.pageChosen.emit(i))
            self.tabs.addWidget(btn)
            self.buttons[i] = btn

    def set_error(self, text: str) -> None:
        self.error.setText(text)
