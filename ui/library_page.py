"""My Library (2.0): everything that's yours, and each of your lists.

Overview tabs: All shows · Timeline · Ratings · Tags. A list shows its shows; right-click one
to take it out of the list. Saved is the old My List.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QModelIndex, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QListView, QMenu, QPushButton, QStackedLayout,
                               QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from core.store import SAVED, Moment, Show, stars

from . import theme
from .cards import CardGrid
from .context import AppContext
from .downloads import DownloadsView
from .home_page import show_card
from .library import list_label
from .mature import decorate_all
from .widgets import empty_state

ROLE = Qt.ItemDataRole.UserRole + 1


def day_label(day: str, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    d = dt.date.fromisoformat(day)
    if d == today:
        return "Today"
    if d == today - dt.timedelta(days=1):
        return "Yesterday"
    if (today - d).days < 7:
        return d.strftime("%A")
    return d.strftime("%B %-d") if d.year == today.year else d.strftime("%B %-d, %Y")


def moment_text(m: Moment) -> str:
    if m.kind == "watched":
        eps = m.detail.split(", ")
        what = f"episode {eps[0]}" if len(eps) == 1 else (
            f"episodes {eps[0]}–{eps[-1]}" if len(eps) > 3 else f"episodes {', '.join(eps)}")
        return f"Watched {what}"
    if m.kind == "saved":
        return "Saved it"
    if m.kind == "listed":
        return f"Added to {m.detail}"
    if m.kind == "rewatch":
        return "Started rewatching it" + (f" (time {int(m.detail) + 1})" if m.detail.isdigit() and int(m.detail) > 1 else "")
    if m.kind == "rated":
        return f"Rated it {stars(int(m.detail))}" if m.detail.isdigit() else "Rated it"
    return m.kind


class TimelineDelegate(QStyledItemDelegate):
    DAY_H = 44
    ROW_H = 66

    def __init__(self, images, parent=None) -> None:
        super().__init__(parent)
        self.images = images

    def sizeHint(self, option, index) -> QSize:
        kind, _ = index.data(ROLE)
        return QSize(option.rect.width(), self.DAY_H if kind == "day" else self.ROW_H)

    def paint(self, p: QPainter, option, index) -> None:
        kind, value = index.data(ROLE)
        r = QRectF(option.rect)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if kind == "day":
            p.setPen(QColor(theme.TEXT))
            p.setFont(theme.font(15, QFont.Weight.Bold))
            p.drawText(r.adjusted(4, 12, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, value)
            p.restore()
            return
        m: Moment = value
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if hover:
            path = QPainterPath()
            path.addRoundedRect(r.adjusted(0, 2, -4, -2), 10, 10)
            p.fillPath(path, QColor(255, 255, 255, 14))
        thumb = QRectF(r.left() + 10, r.top() + 7, 37, 52)
        pm = self.images.pixmap(m.poster, int(thumb.width()), int(thumb.height())) if m.poster else None
        clip = QPainterPath()
        clip.addRoundedRect(thumb, 5, 5)
        p.setClipPath(clip)
        if pm is not None:
            p.drawPixmap(thumb.toRect(), pm)
        else:
            p.fillRect(thumb, QColor(theme.SURFACE_2))
        p.setClipping(False)
        dot = {"watched": theme.ACCENT, "saved": "#E0405C", "listed": "#5B9BF0", "rated": "#F5C04A", "rewatch": "#43B87A"}.get(m.kind, theme.MUTED)
        x = thumb.right() + 16
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(14, QFont.Weight.DemiBold))
        p.drawText(QRectF(x, r.top() + 12, r.width() - x - 90, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(m.title, Qt.TextElideMode.ElideRight, int(r.width() - x - 90)))
        p.setBrush(QColor(dot))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(x, r.top() + 41, 7, 7))
        p.setPen(QColor(theme.MUTED))
        p.setFont(theme.font(13, QFont.Weight.Medium))
        p.drawText(QRectF(x + 14, r.top() + 34, r.width() - x - 104, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   moment_text(m))
        p.setPen(QColor(theme.FAINT))
        p.setFont(theme.font(12, QFont.Weight.Medium))
        when = dt.datetime.fromtimestamp(m.at).strftime("%-I:%M %p")
        p.drawText(QRectF(r.right() - 90, r.top(), 80, r.height()), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, when)
        p.restore()


class TimelineView(QListView):
    openShow = Signal(str)      # anime_id

    def __init__(self, images, parent=None) -> None:
        super().__init__(parent)
        self.model_ = QStandardItemModel(self)
        self.setModel(self.model_)
        self.setItemDelegate(TimelineDelegate(images, self))
        self.setMouseTracking(True)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setObjectName("Timeline")
        self.clicked.connect(self._clicked)
        images.loaded.connect(lambda _u: self.viewport().update())

    def set_moments(self, moments: list[Moment]) -> None:
        self.model_.clear()
        day = None
        for m in moments:
            if m.day != day:
                day = m.day
                item = QStandardItem()
                item.setData(("day", day_label(day)), ROLE)
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.model_.appendRow(item)
            item = QStandardItem()
            item.setData(("moment", m), ROLE)
            self.model_.appendRow(item)

    def _clicked(self, index: QModelIndex) -> None:
        kind, value = index.data(ROLE)
        if kind == "moment":
            self.openShow.emit(value.anime_id)


class MomentDelegate(QStyledItemDelegate):
    W, H, TEXT = 256, 144, 46

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pix: dict[str, QPixmap | None] = {}

    def sizeHint(self, option, index) -> QSize:
        return QSize(self.W + 20, self.H + self.TEXT + 18)

    def _picture(self, path: str):
        if path not in self._pix:
            pm = QPixmap(path) if path and Path(path).is_file() else None
            self._pix[path] = pm.scaled(self.W * 2, self.H * 2, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                        Qt.TransformationMode.SmoothTransformation) if pm and not pm.isNull() else None
        return self._pix[path]

    def paint(self, p: QPainter, option, index) -> None:
        m = index.data(ROLE)
        r = QRectF(option.rect).adjusted(10, 6, -10, -6)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pic = QRectF(r.left(), r.top() - (3 if hover else 0), self.W, self.H)
        clip = QPainterPath()
        clip.addRoundedRect(pic, 10, 10)
        p.setClipPath(clip)
        pm = self._picture(m.image)
        if pm is not None:
            src = QRectF(0, 0, pm.width(), pm.height())
            p.drawPixmap(pic, pm, src)
        else:
            p.fillRect(pic, QColor(theme.SURFACE_2))
            p.setPen(QColor(theme.MUTED))
            p.setFont(theme.font(13, QFont.Weight.DemiBold))
            p.drawText(pic, Qt.AlignmentFlag.AlignCenter, "✨")
        p.setClipping(False)
        mins, secs = divmod(int(m.position), 60)
        chip = QRectF(pic.right() - 62, pic.bottom() - 30, 54, 22)
        p.setBrush(QColor(0, 0, 0, 170))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(chip, 6, 6)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(theme.font(11, QFont.Weight.Bold))
        p.drawText(chip, Qt.AlignmentFlag.AlignCenter, f"{mins}:{secs:02d}")
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(13, QFont.Weight.DemiBold))
        p.drawText(QRectF(pic.left(), pic.bottom() + 8, self.W, 18), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(f"{m.title} · Ep {m.episode}", Qt.TextElideMode.ElideRight, self.W))
        p.setPen(QColor(theme.MUTED))
        p.setFont(theme.font(12, QFont.Weight.Medium))
        p.drawText(QRectF(pic.left(), pic.bottom() + 27, self.W, 18), Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(m.note or dt.datetime.fromtimestamp(m.at).strftime("%b %-d"),
                                              Qt.TextElideMode.ElideRight, self.W))
        p.restore()


class MomentsView(QListView):
    openMoment = Signal(object)
    changed = Signal()

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.model_ = QStandardItemModel(self)
        self.setModel(self.model_)
        self.setItemDelegate(MomentDelegate(self))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setObjectName("Timeline")
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda i: self.openMoment.emit(i.data(ROLE)))

    def set_moments(self, moments) -> None:
        self.model_.clear()
        for m in moments:
            item = QStandardItem()
            item.setData(m, ROLE)
            self.model_.appendRow(item)

    def contextMenuEvent(self, e) -> None:
        index = self.indexAt(e.pos())
        if not index.isValid():
            return
        m = index.data(ROLE)
        menu = QMenu(self)
        menu.addAction("Add a note…").triggered.connect(lambda: self._note(m))
        menu.addAction("Delete this moment").triggered.connect(lambda: self._delete(m))
        menu.exec(e.globalPos())

    def _note(self, m) -> None:
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Moment", "A note for this moment:", text=m.note)
        if ok:
            self.store.set_moment_note(m.moment_id, text)
            self.changed.emit()

    def _delete(self, m) -> None:
        path = self.store.delete_moment(m.moment_id)
        if path:
            Path(path).unlink(missing_ok=True)
        self.changed.emit()


class LibraryPage(QWidget):
    openItem = Signal(object)        # Show
    listsChanged = Signal()          # a list was renamed, emptied or deleted
    listMenu = Signal(int, QPoint)   # the ⋯ on a list's page

    TABS = (("all", "All shows"), ("timeline", "Timeline"), ("moments", "Moments"), ("ratings", "Ratings"),
            ("tags", "Tags"), ("downloads", "Downloads"))
    openMoment = Signal(object)      # Moment_
    playDownload = Signal(str, str, str)   # anime_id, title, episode

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Page")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.list_id: int | None = None          # None: the overview
        self.tab = "all"
        self.tag: str | None = None
        self.hidden = lambda: set()               # shows only in locked lists (main window sets this)

        self.title = QLabel("My Library", objectName="LibraryTitle")
        self.count = QLabel("", objectName="SectionCount")
        self.subtitle = QLabel("Everything here stays on this Mac.", objectName="LibrarySub")
        self.more = QPushButton("⋯", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.more.setFixedWidth(44)
        self.more.setToolTip("Rename, move, lock or delete this list")
        self.more.clicked.connect(lambda: self.list_id is not None and self.listMenu.emit(
            self.list_id, self.more.mapToGlobal(QPoint(0, self.more.height()))))
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(self.title)
        header.addWidget(self.count, 0, Qt.AlignmentFlag.AlignBottom)
        header.addStretch(1)
        header.addWidget(self.more)

        self.tabs = QButtonGroup(self)
        self.tab_btns: dict[str, QPushButton] = {}
        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(6)
        for key, label in self.TABS:
            b = QPushButton(label, objectName="Toggle", checkable=True, cursor=Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=key: self.set_tab(k))
            self.tabs.addButton(b)
            self.tab_btns[key] = b
            tabs_row.addWidget(b)
        tabs_row.addStretch(1)
        self.tab_bar = QWidget()
        self.tab_bar.setLayout(tabs_row)
        tabs_row.setContentsMargins(0, 0, 0, 0)

        self.tag_bar = QWidget()
        self.tag_row = QHBoxLayout(self.tag_bar)
        self.tag_row.setContentsMargins(0, 0, 0, 0)
        self.tag_row.setSpacing(6)

        self.grid = CardGrid(ctx.images)
        self.grid.cardActivated.connect(lambda card: self.openItem.emit(card.payload))
        self.grid.cardMenuRequested.connect(self._card_menu)
        self.timeline = TimelineView(ctx.images)
        self.timeline.openShow.connect(self._open_id)
        self.moments = MomentsView(ctx.store)
        self.moments.openMoment.connect(self.openMoment)
        self.moments.changed.connect(self.refresh)
        self.downloads = DownloadsView(ctx, ctx.downloads) if ctx.downloads is not None else None
        if self.downloads is not None:
            self.downloads.play.connect(self.playDownload)
        self.empty = empty_state("")
        body = QWidget()
        self.stack = QStackedLayout(body)
        for w in (self.empty, self.grid, self.timeline, self.moments, self.downloads):
            if w is None:
                continue
            self.stack.addWidget(w)

        col = QVBoxLayout(self)
        col.setContentsMargins(34, 36, 30, 0)
        col.setSpacing(14)
        col.addLayout(header)
        col.addWidget(self.subtitle)
        col.addWidget(self.tab_bar)
        col.addWidget(self.tag_bar)
        col.addWidget(body, 1)
        self.tab_btns["all"].setChecked(True)

    # -- what's showing -----------------------------------------------------------------------

    def show_overview(self, tab: str | None = None) -> None:
        self.list_id = None
        if tab:
            self.tab = tab
        self.refresh()

    def show_list(self, list_id: int) -> None:
        self.list_id = list_id
        self.refresh()

    def set_tab(self, tab: str) -> None:
        self.tab = tab
        self.tag = None
        self.refresh()

    def refresh(self) -> None:
        store = self.ctx.store
        overview = self.list_id is None
        sl = None if overview else store.get_list(self.list_id)
        if not overview and sl is None:            # (deleted)
            self.list_id, overview = None, True
        self.more.setVisible(not overview)
        self.tab_bar.setVisible(overview)
        self.tag_bar.setVisible(overview and self.tab == "tags")
        self.tab_btns[self.tab].setChecked(True)
        if not overview:
            self.title.setText(list_label(sl))
            self.subtitle.setText("Your old My List. Save shows from any show page." if sl.list_id == SAVED
                                  else "Right-click a show to take it out of this list.")
            shows = store.list_shows(sl.list_id)
            self._grid(shows, "Nothing here yet. On any show page, use “Lists” to add it."
                       if sl.list_id != SAVED else "Nothing saved yet. Open any show and press “+ Save”.")
            return
        self.title.setText("My Library")
        self.subtitle.setText("Everything here stays on this Mac. Nothing about it is sent anywhere.")
        hide = self.hidden()
        if self.tab == "timeline":
            moments = [m for m in store.timeline() if m.anime_id not in hide]
            self.count.setText("")
            self.timeline.set_moments(moments)
            if moments:
                self.stack.setCurrentWidget(self.timeline)
            else:
                self.empty.setText("Your timeline fills in as you watch, save, list and rate shows.")
                self.stack.setCurrentWidget(self.empty)
        elif self.tab == "moments":
            moments = [m for m in store.moments() if m.anime_id not in hide]
            self.count.setText(str(len(moments)) if moments else "")
            self.moments.set_moments(moments)
            if moments:
                self.stack.setCurrentWidget(self.moments)
            else:
                self.empty.setText("Press B (or ⌘S) while an episode plays to keep that frame. "
                                   "Your moments show up here; click one to watch from that second.")
                self.stack.setCurrentWidget(self.empty)
        elif self.tab == "downloads":
            self.refresh_downloads()
        elif self.tab == "ratings":
            rated = [(s, r) for s, r in store.rated() if s.anime_id not in hide]
            cards = [replace(show_card(s), subtitle=stars(r)) for s, r in rated]
            self._grid_cards(cards, [s for s, _ in rated], "Rate shows on their page (under Yours) and they'll line up here, best first.")
        elif self.tab == "tags":
            self._tags(hide)
        else:
            self._grid([s for s in store.library_all() if s.anime_id not in hide], "Save a show, add one to a list, or rate one, and it shows up here.")

    def refresh_downloads(self) -> None:
        if self.downloads is None:
            self.empty.setText("Downloads aren't available here.")
            self.stack.setCurrentWidget(self.empty)
            return
        n = self.downloads.refresh()
        saved = self.ctx.store.downloads()
        self.count.setText(str(len(saved)) if saved else "")
        if n:
            self.subtitle.setText("Episodes saved on this Mac play with no internet. Right-click one for more.")
            self.stack.setCurrentWidget(self.downloads)
        else:
            self.empty.setText("Right-click any episode and choose Download to watch it with no internet "
                               "(on a plane, say). Saved episodes show up here.")
            self.stack.setCurrentWidget(self.empty)

    def _tags(self, hide: set[str]) -> None:
        while self.tag_row.count():
            w = self.tag_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        tags = self.ctx.store.all_tags()
        if tags and (self.tag is None or self.tag.lower() not in (t.lower() for t, _ in tags)):
            self.tag = tags[0][0]
        group = QButtonGroup(self.tag_bar)
        for name, n in tags:
            b = QPushButton(f"{name}  {n}", objectName="TagFilter", checkable=True, cursor=Qt.CursorShape.PointingHandCursor)
            b.setChecked(name == self.tag)
            b.clicked.connect(lambda _c=False, t=name: (setattr(self, "tag", t), self.refresh()))
            group.addButton(b)
            self.tag_row.addWidget(b)
        self.tag_row.addStretch(1)
        shows = [s for s in self.ctx.store.tagged(self.tag) if s.anime_id not in hide] if self.tag else []
        self._grid(shows, "Tag shows on their page (under Yours): “cozy”, “rewatch”, “with friends”…")

    def _grid(self, shows: list[Show], empty: str) -> None:
        self._grid_cards([show_card(s) for s in shows], shows, empty)

    def _grid_cards(self, cards, shows: list[Show], empty: str) -> None:
        self.count.setText(str(len(cards)) if cards else "")
        self.grid.cards.set_cards(decorate_all(self.ctx, cards))
        self.empty.setText(empty)
        self.stack.setCurrentWidget(self.grid if cards else self.empty)
        todo = self.ctx.catalog.claim_maturity(shows)
        if todo:
            self.ctx.runner.submit(self.ctx.catalog.backfill_maturity, todo,
                                   on_done=lambda found: found and self.ctx.events.changed.emit("maturity_found", found),
                                   group="library-maturity")
        for show in shows:
            if not show.poster:
                self.ctx.runner.submit(self.ctx.catalog.cover_for, show.anime_id, show.title,
                                       on_done=lambda url, aid=show.anime_id: url and self.grid.cards.update_card(f"show:{aid}", cover=url))

    # -- actions --------------------------------------------------------------------------------

    def _open_id(self, anime_id: str) -> None:
        show = self.ctx.store.get_show(anime_id)
        if show:
            self.openItem.emit(show)

    def _card_menu(self, card, pos: QPoint) -> None:
        show = card.payload
        if self.list_id is None or not isinstance(show, Show):
            return
        sl = self.ctx.store.get_list(self.list_id)
        menu = QMenu(self)
        menu.addAction(f"Remove from {sl.name}").triggered.connect(lambda: self._remove(show))
        menu.exec(pos)

    def _remove(self, show: Show) -> None:
        self.ctx.store.remove_from_list(self.list_id, show.anime_id)
        self.refresh()
        self.listsChanged.emit()
