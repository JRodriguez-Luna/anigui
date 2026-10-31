"""Calendar: this week's episodes, a column per day, in local time."""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from core import calendar as cal

from .context import AppContext
from .widgets import PosterWidget

STATE_TEXT = {cal.AVAILABLE: "WATCH NOW", cal.PENDING: "Coming soon", cal.AIRED: "Aired"}


def time_text(when: dt.datetime) -> str:
    return when.strftime("%-I:%M %p")


class EntryCard(QFrame):
    clicked = Signal(object)                 # Entry
    menuRequested = Signal(object, QPoint)   # Entry, global position

    def __init__(self, entry: cal.Entry, images, parent=None) -> None:
        super().__init__(parent, objectName="CalEntry")
        self.entry = entry
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("mine", entry.in_library)
        poster = PosterWidget(images, 40, 58)
        poster.set_cover(entry.media.cover, entry.media.cover_color)
        ep = QLabel(f"EP {entry.episode}", objectName="CalEp")
        at = QLabel(time_text(entry.when), objectName="CalMeta")
        when = QVBoxLayout()
        when.setSpacing(1)
        when.addWidget(ep)
        when.addWidget(at)
        when.addStretch(1)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(poster, 0, Qt.AlignmentFlag.AlignTop)
        top.addLayout(when, 1)

        title = QLabel(entry.title, objectName="CalTitle", wordWrap=True)
        col = QVBoxLayout(self)
        col.setContentsMargins(8, 8, 8, 8)
        col.setSpacing(6)
        col.addLayout(top)
        col.addWidget(title)
        badge_text = STATE_TEXT.get(entry.state)
        if badge_text:
            badge = QLabel(badge_text, objectName="CalBadge")
            badge.setProperty("state", entry.state)
            col.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)
        self.setToolTip(f"{entry.title}\nEpisode {entry.episode} · {entry.when:%A} {time_text(entry.when)}")

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.entry)

    def contextMenuEvent(self, event) -> None:
        self.menuRequested.emit(self.entry, event.globalPos())


class CalendarPage(QScrollArea):
    openItem = Signal(object)        # Show (known hianime id) or Media
    libraryChanged = Signal()
    toast = Signal(str, bool)

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Page")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.offset = 0
        self.week: cal.Week | None = None

        title = QLabel("Calendar", objectName="SectionTitle")
        self.mine_btn = QPushButton("My shows", objectName="Toggle", checkable=True, checked=True,
                                    cursor=Qt.CursorShape.PointingHandCursor)
        self.all_btn = QPushButton("All airing", objectName="Toggle", checkable=True,
                                   cursor=Qt.CursorShape.PointingHandCursor)
        group = QButtonGroup(self)
        group.addButton(self.mine_btn)
        group.addButton(self.all_btn)
        self.mine_btn.toggled.connect(lambda _on: self.refresh())
        self.prev_btn = QPushButton("‹", objectName="Arrow", cursor=Qt.CursorShape.PointingHandCursor)
        self.next_btn = QPushButton("›", objectName="Arrow", cursor=Qt.CursorShape.PointingHandCursor)
        self.today_btn = QPushButton("This week", objectName="RowAction", cursor=Qt.CursorShape.PointingHandCursor)
        self.prev_btn.clicked.connect(lambda: self.go_week(self.offset - 1))
        self.next_btn.clicked.connect(lambda: self.go_week(self.offset + 1))
        self.today_btn.clicked.connect(lambda: self.go_week(0))
        self.range = QLabel("", objectName="CalRange")

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(title)
        head.addSpacing(14)
        head.addWidget(self.mine_btn)
        head.addWidget(self.all_btn)
        head.addStretch(1)
        head.addWidget(self.today_btn)
        head.addWidget(self.prev_btn)
        head.addWidget(self.range)
        head.addWidget(self.next_btn)

        self.status = QLabel("", objectName="Muted", wordWrap=True)
        self.note = QLabel("Times are the original broadcast in Japan, shown in your time zone. hianime usually "
                           "has the sub a few hours later; dubs come later.", objectName="SettingsNote", wordWrap=True)

        self.grid = QHBoxLayout()
        self.grid.setSpacing(10)
        self.columns: list[QVBoxLayout] = []
        self.headers: list[QLabel] = []
        self.day_frames: list[QFrame] = []
        for _ in range(7):
            frame = QFrame(objectName="CalDay")
            # Equal columns whatever they hold
            frame.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            frame.setMinimumWidth(128)
            col = QVBoxLayout(frame)
            col.setContentsMargins(8, 10, 8, 10)
            col.setSpacing(8)
            header = QLabel("", objectName="CalDayTitle")
            col.addWidget(header)
            col.addStretch(1)
            self.columns.append(col)
            self.headers.append(header)
            self.day_frames.append(frame)
            self.grid.addWidget(frame, 1)

        body = QWidget(objectName="PageBody")
        outer = QVBoxLayout(body)
        outer.setContentsMargins(44, 36, 44, 40)
        outer.setSpacing(12)
        outer.addLayout(head)
        outer.addWidget(self.status)
        outer.addLayout(self.grid)
        outer.addWidget(self.note)
        outer.addStretch(1)
        self.setWidget(body)

    # -- data ---------------------------------------------------------------------------

    @property
    def mine(self) -> bool:
        return self.mine_btn.isChecked()

    def go_week(self, offset: int) -> None:
        self.offset = offset
        self.refresh()

    def refresh(self) -> None:
        monday = cal.week_start(offset=self.offset)
        self._set_range(monday)
        self.status.setText("Loading the schedule…")
        self.ctx.runner.submit(cal.build, self.ctx.store, self.ctx.catalog, mine=self.mine,
                               scope=str(self.ctx.pref("alerts_scope")), monday=monday,
                               on_done=self._show, on_error=self._error, group="calendar")

    def _set_range(self, monday: dt.date) -> None:
        sunday = monday + dt.timedelta(days=6)
        end = f"{sunday:%b} {sunday.day}" if sunday.month != monday.month else str(sunday.day)
        self.range.setText(f"{monday:%b} {monday.day} – {end}")
        self.today_btn.setVisible(self.offset != 0)

    def _show(self, week: cal.Week) -> None:
        if week.monday != cal.week_start(offset=self.offset):
            return  # an older request
        self.week = week
        today = dt.date.today()
        for i, (col, header, frame) in enumerate(zip(self.columns, self.headers, self.day_frames)):
            day = week.monday + dt.timedelta(days=i)
            header.setText("Today" if day == today else f"{day:%a} {day.day}")
            frame.setProperty("today", day == today)
            frame.style().unpolish(frame)
            frame.style().polish(frame)
            while col.count() > 2:          # keep the header and the stretch
                item = col.takeAt(1)
                if item.widget():
                    item.widget().deleteLater()
            entries = week.days[i]
            if not entries:
                none = QLabel("—", objectName="CalEmpty")
                col.insertWidget(1, none)
            for k, entry in enumerate(entries):
                card = EntryCard(entry, self.ctx.images)
                card.clicked.connect(self._open)
                card.menuRequested.connect(self._menu)
                col.insertWidget(1 + k, card)
        if week.count:
            what = "from your shows" if self.mine else "airing"
            self.status.setText(f"{week.count} episode{'s' if week.count != 1 else ''} {what} this week."
                                if self.offset == 0 else f"{week.count} episode{'s' if week.count != 1 else ''} {what}.")
        elif self.mine:
            self.status.setText("Nothing from My List airs this week. Add airing shows to My List, or switch to "
                                "All airing to find some.")
        else:
            self.status.setText("No schedule for this week yet.")

    def _error(self, message: str) -> None:
        self.status.setText(f"Couldn't load the schedule: {message}")

    # -- actions --------------------------------------------------------------------------

    def _open(self, entry: cal.Entry) -> None:
        show = self.ctx.store.get_show(entry.anime_id) if entry.anime_id else None
        self.openItem.emit(show or entry.media)

    def _menu(self, entry: cal.Entry, pos: QPoint) -> None:
        menu = QMenu(self)
        if entry.in_library:
            menu.addAction("Remove from My List").triggered.connect(lambda: self._set_library(entry, False))
        else:
            menu.addAction("Add to My List").triggered.connect(lambda: self._set_library(entry, True))
        menu.addAction("Open Show").triggered.connect(lambda: self._open(entry))
        menu.exec(pos)

    def _set_library(self, entry: cal.Entry, add: bool) -> None:
        def work():
            anime_id = entry.anime_id
            if anime_id is None:  # only on AniList so far: find it on hianime first
                found = self.ctx.catalog.find_streamable(entry.media)
                if found is None:
                    return None
                anime_id = found.anime_id
            self.ctx.store.set_in_library(anime_id, add)
            return anime_id

        def done(anime_id):
            if anime_id is None:
                self.toast.emit(f"{entry.title} isn't on hianime yet, so it can't be added.", True)
                return
            self.toast.emit(f"{'Added' if add else 'Removed'} {entry.title} {'to' if add else 'from'} My List", False)
            self.libraryChanged.emit()
            self.refresh()

        self.ctx.runner.submit(work, on_done=done, on_error=lambda msg: self.toast.emit(msg, True))
