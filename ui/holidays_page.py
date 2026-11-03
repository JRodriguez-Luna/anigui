"""The 🎄 Holidays page (in the sidebar while the holiday theme is on): a countdown, the
advent calendar, the 12 Days of Anime challenge with badges, and the Christmas episodes of
shows you watch."""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core import holiday
from core.anilist import Media

from . import festive, theme
from .cards import Card, CardRow
from .context import AppContext
from .mature import decorate_all, visible


class CaneBar(QWidget):
    """The 12 Days progress bar: candy-cane stripes."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.fraction = 0.0
        self.setFixedHeight(10)

    def set_fraction(self, f: float) -> None:
        self.fraction = max(0.0, min(1.0, f))
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.SURFACE_2))
        p.drawRoundedRect(r, 5, 5)
        if self.fraction:
            p.save()
            from PySide6.QtGui import QPainterPath
            clip = QPainterPath()
            clip.addRoundedRect(r, 5, 5)
            p.setClipPath(clip)
            was = theme.HOLIDAY
            theme.HOLIDAY = True                 # always stripes here
            festive.progress_bar(p, r, self.fraction, theme.ACCENT)
            theme.HOLIDAY = was
            p.restore()
        p.end()


class BadgeView(QWidget):
    """One badge: a round medal with its emoji, its name under it. Greyed until earned."""

    def __init__(self, badge: holiday.Badge, parent=None) -> None:
        super().__init__(parent)
        self.badge = badge
        self.setFixedSize(84, 86)
        self.setToolTip(f"{badge.name}: {badge.hint}" + ("  ✓" if badge.earned else ""))
        self.setAccessibleName(f"{badge.name}, {'earned' if badge.earned else 'not yet'}")

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        b = self.badge
        c = QPointF(self.width() / 2, 28)
        if b.earned:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#2A1518"))
            p.drawEllipse(c, 25, 25)
            from PySide6.QtGui import QPen
            p.setPen(QPen(QColor(festive.CANE_RED), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, 25, 25)
        else:
            from PySide6.QtGui import QPen
            pen = QPen(QColor("#3A3A4C"), 2, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(QColor(theme.SURFACE_2))
            p.drawEllipse(c, 25, 25)
            p.setOpacity(0.35)
        p.setFont(theme.font(22))
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(c.x() - 25, c.y() - 25, 50, 50), Qt.AlignmentFlag.AlignCenter, b.emoji)
        p.setOpacity(1.0)
        p.setFont(theme.font(11, QFont.Weight.DemiBold if b.earned else QFont.Weight.Normal))
        p.setPen(QColor(theme.TEXT if b.earned else theme.FAINT))
        p.drawText(QRectF(0, 58, self.width(), 26), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
                   | Qt.TextFlag.TextWordWrap, b.name)
        p.end()


class HolidaysPage(QScrollArea):
    playEpisode = Signal(object, str)     # Media, episode number
    openItem = Signal(object)

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Page")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.media: dict[int, Media] = {}
        self.today: dt.date | None = None        # tests pin the date

        self.title = QLabel("Holidays at AniGUI", objectName="HolidaysTitle")
        self.countdown = QLabel("", objectName="HolidaysCountdown")

        # advent calendar
        self.doors: list[QPushButton] = []
        grid = QGridLayout()
        grid.setSpacing(8)
        for day in range(1, 25):
            door = QPushButton(str(day), objectName="AdventDoor", cursor=Qt.CursorShape.PointingHandCursor)
            door.setFixedHeight(46)
            door.clicked.connect(lambda _c=False, d=day: self.open_door(d))
            grid.addWidget(door, (day - 1) // 12, (day - 1) % 12)
            self.doors.append(door)
        self.pick = QLabel("", objectName="AdventPick", wordWrap=True)
        self.pick.setTextFormat(Qt.TextFormat.RichText)
        self.watch = QPushButton("▶  Watch", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        self.watch.clicked.connect(self._watch_pick)
        self.watch.setVisible(False)
        self._picked: holiday.XmasEpisode | None = None
        pick_row = QHBoxLayout()
        pick_row.addWidget(self.pick, 1)
        pick_row.addWidget(self.watch)
        pick_box = QFrame(objectName="AdventPickBox")
        pick_box.setLayout(pick_row)
        pick_row.setContentsMargins(14, 10, 10, 10)

        # 12 Days of Anime
        self.bar = CaneBar()
        self.bar_text = QLabel("", objectName="Muted")
        bar_row = QHBoxLayout()
        bar_row.setSpacing(12)
        bar_row.addWidget(self.bar, 1)
        bar_row.addWidget(self.bar_text)
        self.badges_row = QHBoxLayout()
        self.badges_row.setSpacing(8)
        self.badges_row.addStretch(1)

        # Christmas episodes in your shows
        self.yours = CardRow("Christmas episodes in your shows", ctx.images)
        self.yours.cardActivated.connect(lambda card: self.playEpisode.emit(card.payload[0], card.payload[1]))
        self.yours.setVisible(False)

        col = QVBoxLayout()
        col.setContentsMargins(44, 34, 44, 40)
        col.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(self.title)
        head.addWidget(self.countdown, 0, Qt.AlignmentFlag.AlignBottom)
        head.addStretch(1)
        col.addLayout(head)
        col.addSpacing(10)
        col.addWidget(QLabel("Advent calendar", objectName="SectionTitle"))
        col.addWidget(QLabel("A Christmas episode behind every door, December 1 to 24. Missed one? It stays open.",
                             objectName="Muted"))
        col.addLayout(grid)
        col.addWidget(pick_box)
        col.addSpacing(18)
        col.addWidget(QLabel("12 Days of Anime", objectName="SectionTitle"))
        self.challenge_note = QLabel("", objectName="Muted", wordWrap=True)
        col.addWidget(self.challenge_note)
        col.addLayout(bar_row)
        col.addLayout(self.badges_row)
        col.addSpacing(18)
        col.addWidget(self.yours)
        col.addStretch(1)
        body = QWidget(objectName="PageBody")
        body.setLayout(col)
        self.setWidget(body)

    # -- data -------------------------------------------------------------------------------

    def _today(self) -> dt.date:
        return self.today or dt.date.today()

    def _opened(self) -> set[int]:
        raw = str(self.ctx.pref(f"advent_{holiday.season_year(self._today())}", "") or "")
        return {int(x) for x in raw.split(",") if x.isdigit()}

    def refresh(self) -> None:
        today = self._today()
        self.countdown.setText(festive.countdown_text(today))
        self._refresh_doors()
        self._refresh_challenge()
        if not self.media and holiday.CHRISTMAS_EPISODES:
            ids = sorted({e.anilist_id for e in holiday.CHRISTMAS_EPISODES})
            self.ctx.runner.submit(self.ctx.catalog.anilist.airing, ids, on_done=self._got_media,
                                   group="holidays-media")
        else:
            self._refresh_yours()

    def _got_media(self, found: dict[int, Media]) -> None:
        self.media = dict(found)
        self._refresh_yours()

    def _refresh_doors(self) -> None:
        can = holiday.advent_open_until(self._today())
        opened = self._opened()
        for day, door in enumerate(self.doors, start=1):
            state = "open" if day in opened else ("today" if day == can and day <= 24 and self._today().month == 12
                                                  else ("closed" if day <= can else "locked"))
            door.setText("★" if day in opened else str(day))
            door.setProperty("state", state)
            door.style().unpolish(door)
            door.style().polish(door)
        if not self._picked:
            self.pick.setText("Doors open December 1." if can == 0 else "Open a door for a Christmas episode.")

    def open_door(self, day: int) -> None:
        can = holiday.advent_open_until(self._today())
        if day > can:
            self.pick.setText(f"Door {day} opens on December {day}. No peeking!")
            self.watch.setVisible(False)
            self._picked = None
            return
        opened = self._opened() | {day}
        self.ctx.set_pref(f"advent_{holiday.season_year(self._today())}", ",".join(str(d) for d in sorted(opened)))
        pick = holiday.advent_pick(day)
        self._picked = pick
        if pick is None:
            self.pick.setText("Nothing behind this door yet.")
            self.watch.setVisible(False)
        else:
            self.pick.setText(f"<b>Door {day}:</b> {_esc(pick.show)} · Episode {_esc(pick.episode)}"
                              f"<span style='color:{theme.MUTED}'> · “{_esc(pick.title)}”</span>")
            self.watch.setVisible(True)
        self._refresh_doors()

    def _watch_pick(self) -> None:
        pick = self._picked
        if pick is None:
            return
        media = self.media.get(pick.anilist_id)
        if media is None:
            self.ctx.runner.submit(self.ctx.catalog.anilist.media, pick.anilist_id,
                                   on_done=lambda m, e=pick.episode: m and self.playEpisode.emit(m, e))
        else:
            self.playEpisode.emit(media, pick.episode)

    def _refresh_challenge(self) -> None:
        store = self.ctx.store
        progress = store.all_progress()
        days = {row[0] for row in store.watch_log()}
        keys: set[tuple[str, str]] = set()
        for e in holiday.CHRISTMAS_EPISODES:
            show = store.find_by_anilist(e.anilist_id)
            if show:
                keys.add((show.anime_id, e.episode))
        first: dict[str, float] = {}
        for p in progress:
            first[p.anime_id] = min(first.get(p.anime_id, p.updated_at), p.updated_at)
        count, badges = holiday.challenge(progress, days, keys, first, self._today())
        self.bar.set_fraction(count / holiday.CHALLENGE_GOAL)
        start, end = holiday.challenge_window(holiday.season_year(self._today()))
        self.bar_text.setText(f"{count} of {holiday.CHALLENGE_GOAL} episodes · Dec {start.day} to {end.day}")
        before = self._today() < start
        self.challenge_note.setText(
            f"Watch {holiday.CHALLENGE_GOAL} episodes between December 14 and Christmas Day"
            + (" (it starts December 14). " if before else ". ")
            + "Badges come from what you watch all season.")
        while self.badges_row.count() > 1:
            item = self.badges_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, b in enumerate(badges):
            self.badges_row.insertWidget(i, BadgeView(b))
        self.badges = badges

    def _refresh_yours(self) -> None:
        store = self.ctx.store
        cards = []
        for e in holiday.CHRISTMAS_EPISODES:
            show = store.find_by_anilist(e.anilist_id)
            media = self.media.get(e.anilist_id)
            if not show or media is None:
                continue
            done = store.get_progress(show.anime_id, e.episode)
            cards.append(Card(key=f"xmas:{e.anilist_id}:{e.episode}", title=e.show,
                              subtitle=f"Ep {e.episode} · {e.title}", cover=media.cover, color=media.cover_color,
                              badge=f"EP {e.episode}", progress=1.0 if done and done.completed else None,
                              payload=(media, e.episode)))
        shown = [c for c in cards if c.payload[0] in visible(self.ctx, [c.payload[0]])[0]]
        self.yours.set_cards(decorate_all(self.ctx, shown))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()


def _esc(text: str) -> str:
    import html
    return html.escape(text or "")
