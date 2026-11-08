"""Home: hero spotlight, Continue Watching, Trending, This Season, My List."""

from __future__ import annotations

import random

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QMenu, QMessageBox, QScrollArea, QVBoxLayout, QWidget

from core import holiday, recommend
from core.anilist import Media, current_season
from core.store import ContinueItem, NewEpisodes, Show

from .mature import decorate_all, flags_for, hiding, visible
from .cards import Card, CardRow, media_card
from .context import AppContext
from . import theme
from .hero import HeroBanner
from .festive import Sleigh
from .holiday import HolidayBanner, SnowLayer

MAX_COVER_LOOKUPS = 12


def continue_card(item: ContinueItem, rewatching: bool = False) -> Card:
    last = item.last
    if last.completed:
        subtitle, progress = f"Watched episode {last.episode}", None
    elif last.duration:
        subtitle, progress = f"Episode {last.episode} · {last.fraction:.0%}", last.fraction
    else:
        subtitle, progress = f"Started episode {last.episode}", 0.04
    if rewatching:
        subtitle = "Rewatching · " + subtitle
    return Card(key=f"show:{item.show.anime_id}", title=item.show.title, subtitle=subtitle,
                cover=item.show.poster, progress=progress, badge=f"EP {last.episode}", payload=item.show)


def show_card(show: Show, new: NewEpisodes | None = None) -> Card:
    return Card(key=f"show:{show.anime_id}", title=show.title, cover=show.poster, payload=show,
                badge=f"NEW · EP {new.latest}" if new else None,
                subtitle=("New episode" if new.count == 1 else f"{new.count} new episodes") if new else "")


def new_card(item: NewEpisodes) -> Card:
    from .alerts import describe

    return Card(key=f"show:{item.show.anime_id}", title=item.show.title, subtitle=describe(item),
                cover=item.show.poster, badge=f"NEW · EP {item.latest}", payload=item.show)


class HomePage(QScrollArea):
    openItem = Signal(object)   # Media | Show
    playItem = Signal(object)   # Media (open details and start playing)
    historyChanged = Signal()
    holidayAnswered = Signal(bool)   # November's banner: Turn on now (True) / Wait (False)
    surprise = Signal(object, object)  # Show, episode (None: wherever you're up to)

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Page")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._cover_lookups: set[str] = set()

        body = QWidget(objectName="PageBody")
        self.hero = HeroBanner(ctx.images)
        self.hero.infoRequested.connect(self.openItem)
        self.hero.playRequested.connect(self.playItem)

        season, year = current_season()
        self.new_row = CardRow("New Episodes", ctx.images)
        self.continue_row = CardRow("Continue Watching", ctx.images)
        self.clear_btn = self.continue_row.add_action("Clear", "Clear your watch history")
        self.clear_btn.clicked.connect(self.confirm_clear_history)
        self.continue_row.cardMenuRequested.connect(self._continue_menu)
        self.notInterested = None              # (set below) a suggestion you don't want
        self.surprise_btn = self.continue_row.add_action("🎁 Surprise me", "Play something from a show you're watching or saved")
        self.surprise_btn.setObjectName("SurpriseButton")
        self.surprise_btn.clicked.connect(self.surprise_me)
        self.surprise_btn.setVisible(False)
        self.trending_row = CardRow("Trending Now", ctx.images)
        self.season_row = CardRow(f"{season.title()} {year}", ctx.images)
        self.library_row = CardRow("Saved", ctx.images)
        self.xmas_row = CardRow("Christmas anime ❄", ctx.images)     # while the holiday theme is on
        # "Because you watched …": filled once your history is in (refresh_local)
        self.because_rows = [CardRow("", ctx.images) for _ in range(recommend.MAX_ROWS)]
        self._because: list[recommend.BecauseRow] = []
        self._because_key = None
        self.rows = [self.new_row, self.continue_row, self.xmas_row, self.trending_row, self.season_row,
                     *self.because_rows, self.library_row]

        self.holiday_banner = HolidayBanner()
        self.holiday_banner.turnOn.connect(lambda: self.holidayAnswered.emit(True))
        self.holiday_banner.wait.connect(lambda: self.holidayAnswered.emit(False))
        self.hero_snow: SnowLayer | None = None
        self.sleigh = Sleigh(self.hero)
        self._xmas = None

        rows = QVBoxLayout()
        rows.setContentsMargins(44, 0, 44, 40)
        rows.setSpacing(0)
        rows.addWidget(self.holiday_banner)
        for row in self.rows:
            row.cardActivated.connect(lambda card: self.openItem.emit(card.payload))
            if row is not self.continue_row:
                row.cardMenuRequested.connect(self._suggestion_menu)
        # Make it yours (2.0): each row sits in a holder, so you can hide rows and change their
        # order without touching when a row shows itself (empty rows still hide)
        self.holders: dict[str, QWidget] = {}
        self.list_rows: dict[int, CardRow] = {}
        for key, members in (("new", [self.new_row]), ("continue", [self.continue_row]), ("xmas", [self.xmas_row]),
                             ("trending", [self.trending_row]), ("season", [self.season_row]),
                             ("because", self.because_rows), ("saved", [self.library_row])):
            self.holders[key] = self._holder(members)
        self.rows_box = rows
        for holder in self.holders.values():
            rows.addWidget(holder)
        rows.addStretch(1)

        self.greeting = QLabel("", self.hero, objectName="Greeting")    # "Good evening, Chuy"
        self.greeting.setTextFormat(Qt.TextFormat.PlainText)
        self.greeting.move(44, 26)
        self.greeting.hide()

        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        col.addWidget(self.hero)
        col.addLayout(rows)
        self.setWidget(body)

        self.new_row.setVisible(False)
        self.continue_row.setVisible(False)
        self.library_row.setVisible(False)
        self.xmas_row.setVisible(False)
        for row in self.because_rows:
            row.setVisible(False)

    # -- data ---------------------------------------------------------------------------

    def load_remote(self) -> None:
        self.trending_row.set_loading()
        self.season_row.set_loading()
        self.hero.set_loading()
        self.ctx.runner.submit(self.ctx.catalog.anilist.trending, per_page=24,
                               on_done=self._on_trending, on_error=lambda msg: self._on_error(self.trending_row, msg),
                               group="home-trending")
        self.ctx.runner.submit(self.ctx.catalog.anilist.season, per_page=24,
                               on_done=self._on_season,
                               on_error=lambda msg: self._on_error(self.season_row, msg),
                               group="home-season")

    def refresh_local(self) -> None:
        fresh = self.ctx.store.new_episodes() if self.ctx.pref("alerts") else []
        new_by_id = {n.show.anime_id: n for n in fresh}
        self.new_row.set_cards(decorate_all(self.ctx, [new_card(n) for n in fresh]))
        items = self.ctx.store.continue_watching(limit=20)
        store = self.ctx.store
        self.continue_row.set_cards(decorate_all(self.ctx, [continue_card(i, bool(store.rewatch(i.show.anime_id)))
                                                            for i in items]))
        library = self.ctx.store.library()
        self.library_row.set_cards(decorate_all(self.ctx, [show_card(s, new_by_id.get(s.anime_id))
                                                           for s in library]))
        self._check_maturity([n.show for n in fresh] + [i.show for i in items] + list(library))
        self._lookup_missing_covers(items)
        self._load_because(items, library)
        self.apply_rows()
        self.update_greeting()

    # -- make it yours (2.0) ----------------------------------------------------------------

    def _holder(self, members) -> QWidget:
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 34)
        col.setSpacing(34)
        for row in members:
            col.addWidget(row)
        return holder

    def apply_rows(self) -> None:
        """Home's rows in your order, the ones you switched off hidden, and your lists you
        picked as rows of their own."""
        from .yours import parse_rows

        store = self.ctx.store
        lists = {sl.list_id: sl for sl in store.lists()}
        order = parse_rows(self.ctx.pref("home_rows"))
        wanted_lists = {int(k[5:]) for k, on in order if k.startswith("list:") and on and k[5:].isdigit()}
        for lid in list(self.list_rows):
            if lid not in wanted_lists or lid not in lists or lists[lid].locked:
                self.holders.pop(f"list:{lid}").deleteLater()
                del self.list_rows[lid]
        for lid in wanted_lists:
            sl = lists.get(lid)
            if sl is None or sl.locked:            # (locked lists never show on Home)
                continue
            row = self.list_rows.get(lid)
            if row is None:
                row = CardRow("", self.ctx.images)
                row.cardActivated.connect(lambda card: self.openItem.emit(card.payload))
                self.list_rows[lid] = row
                self.holders[f"list:{lid}"] = self._holder([row])
            row.title.setText(f"{sl.emoji}  {sl.name}" if sl.emoji else sl.name)
            shows = store.list_shows(lid)
            row.set_cards(decorate_all(self.ctx, [show_card(s) for s in shows]))
            row.setVisible(bool(shows))
        box = self.rows_box
        for holder in self.holders.values():
            box.removeWidget(holder)
        at = 1                                     # (after the holiday banner)
        placed = set()
        for key, on in order:
            holder = self.holders.get(key)
            if holder is None:
                continue
            box.insertWidget(at, holder)
            holder.setVisible(on)
            placed.add(key)
            at += 1
        for key, holder in self.holders.items():  # anything not in your order: at the end
            if key not in placed:
                box.insertWidget(at, holder)
                holder.setVisible(True)
                at += 1

    def update_greeting(self) -> None:
        from .yours import greeting

        text = greeting(str(self.ctx.pref("your_name") or ""), holiday=theme.HOLIDAY)
        self.greeting.setText(text)
        self.greeting.adjustSize()
        self.greeting.setVisible(bool(text))
        self.greeting.raise_()

    # -- because you watched ---------------------------------------------------------------

    def _load_because(self, items, library) -> None:
        """Only when what you've watched or saved changed (not on every progress save)."""
        key = (tuple(sorted((i.show.anime_id, i.show.anilist_id or 0) for i in items)),
               tuple(sorted((s.anime_id, s.anilist_id or 0) for s in library)))
        if key == self._because_key:
            return
        self._because_key = key
        self.ctx.runner.submit(recommend.because_rows, self.ctx.store, self.ctx.catalog.anilist.related,
                               on_done=self._on_because, on_error=lambda _m: None, group="home-because")

    def _on_because(self, rows) -> None:
        self._because = list(rows or [])
        filled = 0
        for data in self._because:
            picks = visible(self.ctx, data.picks)[0]
            if len(picks) < recommend.MIN_CARDS or filled >= len(self.because_rows):
                continue
            row = self.because_rows[filled]
            row.title.setText(f"Because you watched {data.title}")
            row.set_cards(decorate_all(self.ctx, [media_card(m) for m in picks]))
            row.setVisible(True)
            filled += 1
        for row in self.because_rows[filled:]:
            row.setVisible(False)

    # -- history ------------------------------------------------------------------------

    def _continue_menu(self, card: Card, pos: QPoint) -> None:
        menu = QMenu(self)
        show = card.payload
        menu.addAction("Remove from Continue Watching").triggered.connect(lambda: self.remove_from_history(show))
        menu.addAction("Clear All Watch History…").triggered.connect(
            lambda: QTimer.singleShot(0, self.confirm_clear_history))  # after the menu has closed
        menu.exec(pos)

    def remove_from_history(self, show: Show) -> None:
        self.ctx.store.forget_show_progress(show.anime_id)
        self.refresh_local()
        self.historyChanged.emit()
        self._toast(f"Removed {show.title} from Continue Watching")

    def confirm_clear_history(self) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Clear watch history")
        box.setText("<b>Clear your watch history?</b>")
        box.setInformativeText("This empties Continue Watching and removes every resume point and watched mark. "
                               "My List stays as it is. This can't be undone.")
        clear = box.addButton("Clear History", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is clear:
            self.clear_history()

    def clear_history(self) -> None:
        self.ctx.store.clear_history()
        self.refresh_local()
        self.historyChanged.emit()
        self._toast("Watch history cleared")

    def _toast(self, text: str) -> None:
        window = self.window()
        if hasattr(window, "toast"):
            window.toast.show_message(text)

    def _on_trending(self, items) -> None:
        self._trending = items
        shown, _hidden = visible(self.ctx, items)
        self.trending_row.set_cards(decorate_all(self.ctx, [media_card(m) for m in shown]))
        self.hero.set_items(shown)

    def _on_season(self, items) -> None:
        self._season = items
        shown, _hidden = visible(self.ctx, items)
        self.season_row.set_cards(decorate_all(self.ctx, [media_card(m) for m in shown]))

    def _check_maturity(self, shows) -> None:
        """Saved shows from before 18+ existed get checked now, not when first opened."""
        todo = self.ctx.catalog.claim_maturity(shows)
        if not todo:
            return
        self.ctx.runner.submit(self.ctx.catalog.backfill_maturity, todo,
                               on_done=self._maturity_found, group="home-maturity")

    def _maturity_found(self, found: int) -> None:
        # Tell every page (My List may be showing the same shows), not just this one.
        if found:
            self.ctx.events.changed.emit("maturity_found", found)

    # -- holiday theme --------------------------------------------------------------------

    def surprise_choices(self) -> list[Show]:
        """Shows you're watching or saved, minus 18+ ones while Hide 18+ shows is on (unless
        you said to show that one anyway)."""
        shows: dict[str, Show] = {}
        for item in self.ctx.store.continue_watching(limit=40):
            shows[item.show.anime_id] = item.show
        for show in self.ctx.store.library():
            shows.setdefault(show.anime_id, show)

        def ok(show: Show) -> bool:
            mature, _notes, allowed, _id = flags_for(self.ctx, show)
            return not (mature and hiding(self.ctx) and not allowed)

        return [s for s in shows.values() if ok(s)]

    def surprise_me(self) -> Show | None:
        choices = self.surprise_choices()
        if not choices:
            self._toast("Save a show or start one, and I'll pick something for you 🎁")
            return None
        show = random.choice(choices)
        self.surprise.emit(show, None)
        return show

    def set_holiday(self, on: bool, today=None) -> None:
        """Snow on the banner and the Christmas shelf while the theme is on; November's
        'theme is ready' banner once a year before it starts."""
        self.surprise_btn.setVisible(on)
        if on:
            if self.hero_snow is None:
                self.hero_snow = SnowLayer(self.hero, settle=True)
                self.verticalScrollBar().valueChanged.connect(lambda _v: self.hero_snow.melt())
            self.hero_snow.start()
            if self._xmas is None:
                self.xmas_row.set_loading()
                self.xmas_row.setVisible(True)
                ids = list(holiday.CHRISTMAS_IDS)

                def fetch(anilist=self.ctx.catalog.anilist):
                    found = anilist.airing(ids)
                    return [found[i] for i in ids if i in found]      # in the hand-picked order

                self.ctx.runner.submit(fetch, on_done=self._on_xmas,
                                       on_error=lambda _m: self.xmas_row.setVisible(False), group="home-xmas")
            else:
                self._on_xmas(self._xmas)
        else:
            if self.hero_snow is not None:
                self.hero_snow.stop()
            self.xmas_row.setVisible(False)
        offer = holiday.offer_early(str(self.ctx.pref("holiday_theme", "auto")),
                                    str(self.ctx.pref("holiday_banner_seen", "")), today)
        if offer and self.holiday_banner.isHidden():
            self.holiday_banner.appear()
        elif not offer and not self.holiday_banner.isHidden() and self.holiday_banner.on_btn.isEnabled():
            self.holiday_banner.setVisible(False)

    def _on_xmas(self, items) -> None:
        self._xmas = items
        shown, _hidden = visible(self.ctx, items)
        self.xmas_row.set_cards(decorate_all(self.ctx, [media_card(m) for m in shown]))
        self.xmas_row.setVisible(bool(shown) and theme.HOLIDAY)

    def _suggestion_menu(self, card, pos) -> None:
        """Right-click a suggestion: Not interested (2.0)."""
        media = card.payload
        if not isinstance(media, Media):
            return
        menu = QMenu(self)
        menu.addAction("Not interested").triggered.connect(lambda: self.not_interested(media))
        menu.exec(pos)

    def not_interested(self, media: Media) -> None:
        self.ctx.store.set_not_interested(media.anilist_id, media.display_title, True)
        self.apply_content_filter()
        window = self.window()
        if hasattr(window, "toast"):
            window.toast.show_message(f"You won't see {media.display_title} in suggestions. "
                                      "(Settings → Content brings it back.)")

    def apply_content_filter(self) -> None:
        """Hide 18+ shows changed: redo the rows from what's already loaded."""
        if self._xmas is not None and theme.HOLIDAY:
            self._on_xmas(self._xmas)
        if getattr(self, "_trending", None) is not None:
            self._on_trending(self._trending)
        if getattr(self, "_season", None) is not None:
            self._on_season(self._season)
        self._on_because(self._because)
        self.refresh_local()

    def _on_error(self, row: CardRow, message: str) -> None:
        row.set_cards([], hide_when_empty=True)
        window = self.window()
        if hasattr(window, "toast"):
            window.toast.show_message(f"Couldn't load {row.title.text()}: {message}", error=True)

    def _lookup_missing_covers(self, items: list[ContinueItem]) -> None:
        todo = [i.show for i in items if not i.show.poster and i.show.anime_id not in self._cover_lookups]
        for show in todo[:MAX_COVER_LOOKUPS]:
            self._cover_lookups.add(show.anime_id)
            self.ctx.runner.submit(
                self.ctx.catalog.cover_for, show.anime_id, show.title,
                on_done=lambda url, aid=show.anime_id: url and self._set_cover(aid, url),
            )

    def _set_cover(self, anime_id: str, url: str) -> None:
        for row in (self.new_row, self.continue_row, self.library_row):
            row.model().update_card(f"show:{anime_id}", cover=url)
