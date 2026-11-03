"""Home: hero spotlight, Continue Watching, Trending, This Season, My List."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QMenu, QMessageBox, QScrollArea, QVBoxLayout, QWidget

from core import holiday
from core.anilist import current_season
from core.store import ContinueItem, NewEpisodes, Show

from .mature import decorate_all, visible
from .cards import Card, CardRow, media_card
from .context import AppContext
from . import theme
from .hero import HeroBanner
from .holiday import HolidayBanner, SnowLayer

MAX_COVER_LOOKUPS = 12


def continue_card(item: ContinueItem) -> Card:
    last = item.last
    if last.completed:
        subtitle, progress = f"Watched episode {last.episode}", None
    elif last.duration:
        subtitle, progress = f"Episode {last.episode} · {last.fraction:.0%}", last.fraction
    else:
        subtitle, progress = f"Started episode {last.episode}", 0.04
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
        self.trending_row = CardRow("Trending Now", ctx.images)
        self.season_row = CardRow(f"{season.title()} {year}", ctx.images)
        self.library_row = CardRow("My List", ctx.images)
        self.xmas_row = CardRow("Christmas anime ❄", ctx.images)     # while the holiday theme is on
        self.rows = [self.new_row, self.continue_row, self.xmas_row, self.trending_row, self.season_row,
                     self.library_row]

        self.holiday_banner = HolidayBanner()
        self.holiday_banner.turnOn.connect(lambda: self.holidayAnswered.emit(True))
        self.holiday_banner.wait.connect(lambda: self.holidayAnswered.emit(False))
        self.hero_snow: SnowLayer | None = None
        self._xmas = None

        rows = QVBoxLayout()
        rows.setContentsMargins(44, 0, 44, 40)
        rows.setSpacing(34)
        rows.addWidget(self.holiday_banner)
        for row in self.rows:
            row.cardActivated.connect(lambda card: self.openItem.emit(card.payload))
            rows.addWidget(row)
        rows.addStretch(1)

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
        self.continue_row.set_cards(decorate_all(self.ctx, [continue_card(i) for i in items]))
        library = self.ctx.store.library()
        self.library_row.set_cards(decorate_all(self.ctx, [show_card(s, new_by_id.get(s.anime_id))
                                                           for s in library]))
        self._check_maturity([n.show for n in fresh] + [i.show for i in items] + list(library))
        self._lookup_missing_covers(items)

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

    def set_holiday(self, on: bool, today=None) -> None:
        """Snow on the banner and the Christmas shelf while the theme is on; November's
        'theme is ready' banner once a year before it starts."""
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

    def apply_content_filter(self) -> None:
        """Hide 18+ shows changed: redo the rows from what's already loaded."""
        if self._xmas is not None and theme.HOLIDAY:
            self._on_xmas(self._xmas)
        if getattr(self, "_trending", None) is not None:
            self._on_trending(self._trending)
        if getattr(self, "_season", None) is not None:
            self._on_season(self._season)
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
