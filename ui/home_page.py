"""Home: hero spotlight, Continue Watching, Trending, This Season, My List."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QMenu, QMessageBox, QScrollArea, QVBoxLayout, QWidget

from core.anilist import current_season
from core.store import ContinueItem, Show

from .cards import Card, CardRow, media_card
from .context import AppContext
from .hero import HeroBanner

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


def show_card(show: Show) -> Card:
    return Card(key=f"show:{show.anime_id}", title=show.title, cover=show.poster, payload=show)


class HomePage(QScrollArea):
    openItem = Signal(object)   # Media | Show
    playItem = Signal(object)   # Media (open details and start playing)
    historyChanged = Signal()

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
        self.continue_row = CardRow("Continue Watching", ctx.images)
        self.clear_btn = self.continue_row.add_action("Clear", "Clear your watch history")
        self.clear_btn.clicked.connect(self.confirm_clear_history)
        self.continue_row.cardMenuRequested.connect(self._continue_menu)
        self.trending_row = CardRow("Trending Now", ctx.images)
        self.season_row = CardRow(f"{season.title()} {year}", ctx.images)
        self.library_row = CardRow("My List", ctx.images)
        self.rows = [self.continue_row, self.trending_row, self.season_row, self.library_row]

        rows = QVBoxLayout()
        rows.setContentsMargins(44, 0, 44, 40)
        rows.setSpacing(34)
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

        self.continue_row.setVisible(False)
        self.library_row.setVisible(False)

    # -- data ---------------------------------------------------------------------------

    def load_remote(self) -> None:
        self.trending_row.set_loading()
        self.season_row.set_loading()
        self.hero.set_loading()
        self.ctx.runner.submit(self.ctx.catalog.anilist.trending, per_page=24,
                               on_done=self._on_trending, on_error=lambda msg: self._on_error(self.trending_row, msg),
                               group="home-trending")
        self.ctx.runner.submit(self.ctx.catalog.anilist.season, per_page=24,
                               on_done=lambda items: self.season_row.set_cards([media_card(m) for m in items]),
                               on_error=lambda msg: self._on_error(self.season_row, msg),
                               group="home-season")

    def refresh_local(self) -> None:
        items = self.ctx.store.continue_watching(limit=20)
        self.continue_row.set_cards([continue_card(i) for i in items])
        self.library_row.set_cards([show_card(s) for s in self.ctx.store.library()])
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
        self.trending_row.set_cards([media_card(m) for m in items])
        self.hero.set_items(items)

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
        for row in (self.continue_row, self.library_row):
            row.model().update_card(f"show:{anime_id}", cover=url)
