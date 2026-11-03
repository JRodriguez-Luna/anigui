"""Search as you type. Plain searches ask hianime (what can actually be streamed);
with filters on, AniList does the filtering and browsing, and a click finds the show on hianime."""

from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QStackedLayout, QToolButton, QVBoxLayout, QWidget,
)

from core.anilist import GENRES

from .mature import decorate_all, hiding, visible
from .cards import Card, CardGrid, media_card
from .context import AppContext
from .widgets import Combo, empty_state

DEBOUNCE_MS = 350
FIRST_YEAR = 1970
SEASONS = [("Any season", None), ("Winter", "WINTER"), ("Spring", "SPRING"), ("Summer", "SUMMER"), ("Fall", "FALL")]
FORMATS = [("Any format", None), ("TV", "TV"), ("Movie", "MOVIE"), ("OVA", "OVA"), ("ONA", "ONA"),
           ("Special", "SPECIAL"), ("TV Short", "TV_SHORT")]
STATUSES = [("Any status", None), ("Airing", "RELEASING"), ("Finished", "FINISHED")]
SORTS = [("Best match", None), ("Most popular", "POPULARITY_DESC"), ("Top rated", "SCORE_DESC"),
         ("Trending", "TRENDING_DESC"), ("Newest", "START_DATE_DESC")]
HINT = "Find anything on hianime: titles in English or Japanese both work. Or pick filters to browse."


@dataclass
class Filters:
    genres: list[str] = field(default_factory=list)
    year: int | None = None
    season: str | None = None
    format: str | None = None
    status: str | None = None
    sort: str | None = None

    @property
    def active(self) -> bool:
        return bool(self.genres or self.year or self.season or self.format or self.status or self.sort)

    def describe(self) -> str:
        bits = [", ".join(self.genres) if self.genres else None,
                next((label for label, v in SEASONS if v == self.season and v), None),
                str(self.year) if self.year else None,
                next((label for label, v in FORMATS if v == self.format and v), None),
                next((label for label, v in STATUSES if v == self.status and v), None)]
        return " · ".join(b for b in bits if b)


class FilterBar(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.genre_btn = QToolButton(objectName="FilterButton", cursor=Qt.CursorShape.PointingHandCursor)
        self.genre_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.genre_menu = QMenu(self.genre_btn)
        self.genre_actions = []
        for genre in GENRES:
            action = self.genre_menu.addAction(genre)
            action.setCheckable(True)
            action.toggled.connect(self._genres_changed)
            self.genre_actions.append(action)
        self.genre_btn.setMenu(self.genre_menu)

        def combo(options):
            box = Combo(cursor=Qt.CursorShape.PointingHandCursor, objectName="FilterCombo")
            for label, value in options:
                box.addItem(label, value)
            box.currentIndexChanged.connect(lambda _i: self._changed())
            return box

        this_year = dt.date.today().year + 1
        self.year = combo([("Any year", None)] + [(str(y), y) for y in range(this_year, FIRST_YEAR - 1, -1)])
        self.season = combo(SEASONS)
        self.format = combo(FORMATS)
        self.status = combo(STATUSES)
        self.sort = combo(SORTS)
        self.clear_btn = QPushButton("Clear filters", objectName="RowAction", cursor=Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for w in (self.genre_btn, self.year, self.season, self.format, self.status):
            row.addWidget(w)
        row.addSpacing(10)
        row.addWidget(QLabel("Sort", objectName="Muted"))
        row.addWidget(self.sort)
        row.addWidget(self.clear_btn)
        row.addStretch(1)
        self._quiet = False
        self._update_labels()

    def filters(self) -> Filters:
        return Filters(
            genres=[a.text() for a in self.genre_actions if a.isChecked()],
            year=self.year.currentData(), season=self.season.currentData(), format=self.format.currentData(),
            status=self.status.currentData(), sort=self.sort.currentData(),
        )

    def set_genres(self, genres: list[str]) -> None:
        self._quiet = True
        for a in self.genre_actions:
            a.setChecked(a.text() in genres)
        self._quiet = False
        self._changed()

    def clear(self) -> None:
        self._quiet = True
        for a in self.genre_actions:
            a.setChecked(False)
        for box in (self.year, self.season, self.format, self.status, self.sort):
            box.setCurrentIndex(0)
        self._quiet = False
        self._changed()

    def _genres_changed(self, _on: bool) -> None:
        self._changed()

    def _changed(self) -> None:
        if self._quiet:
            return
        self._update_labels()
        self.changed.emit()

    def _update_labels(self) -> None:
        chosen = [a.text() for a in self.genre_actions if a.isChecked()]
        self.genre_btn.setText("Any genre" if not chosen else chosen[0] if len(chosen) == 1
                               else f"{len(chosen)} genres")
        self.genre_btn.setProperty("active", bool(chosen))
        self.genre_btn.style().unpolish(self.genre_btn)
        self.genre_btn.style().polish(self.genre_btn)
        self.season.setEnabled(self.year.currentData() is not None)
        self.clear_btn.setVisible(self.filters().active)


class SearchPage(QWidget):
    openItem = Signal(object)  # SearchResult, or Media when filtering
    setupRequested = Signal()

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Page")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        title = QLabel("Search", objectName="SectionTitle")
        self.box = QLineEdit(objectName="SearchBox", placeholderText="Search for a show…  (⌘F)")
        self.box.setClearButtonEnabled(True)
        self.filter_bar = FilterBar()
        self.filter_bar.changed.connect(self._search)
        self.status = QLabel("", objectName="Muted")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.hidden_note = QLabel("", objectName="HiddenNote")
        self.hidden_note.setTextFormat(Qt.TextFormat.RichText)   # only our own text and link
        self.hidden_note.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.hidden_note.linkActivated.connect(lambda _link: self._show_hidden())
        self.hidden_note.setVisible(False)

        self.grid = CardGrid(ctx.images)
        self.grid.cardActivated.connect(lambda card: self.openItem.emit(card.payload))
        self.empty = empty_state(HINT)
        self.empty.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.empty.linkActivated.connect(lambda _link: self.setupRequested.emit())
        self.results = QWidget()
        self.stack = QStackedLayout(self.results)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.grid)

        col = QVBoxLayout(self)
        col.setContentsMargins(34, 36, 30, 0)
        col.setSpacing(14)
        top = QVBoxLayout()
        top.setContentsMargins(10, 0, 10, 0)
        top.setSpacing(12)
        top.addWidget(title)
        top.addWidget(self.box)
        top.addWidget(self.filter_bar)
        top.addWidget(self.status)
        top.addWidget(self.hidden_note)
        col.addLayout(top)
        col.addWidget(self.results, 1)

        self._debounce = QTimer(self, singleShot=True, interval=DEBOUNCE_MS)
        self._debounce.timeout.connect(self._search)
        self.box.textChanged.connect(lambda _t: self._debounce.start())
        self.box.returnPressed.connect(self._search)
        self._last_key: tuple | None = None

    def focus_search(self) -> None:
        self.box.setFocus()
        self.box.selectAll()

    def _search(self) -> None:
        self._debounce.stop()
        query = self.box.text().strip()
        filters = self.filter_bar.filters()
        key = (query, repr(filters))
        if key == self._last_key:
            return
        self._last_key = key
        if filters.active:
            self._browse(query, filters)
            return
        if len(query) < 2:
            self.status.setText("")
            self.stack.setCurrentWidget(self.empty)
            self.empty.setText(HINT)
            return
        self.status.setText(f"Searching for “{query}”…")
        self.stack.setCurrentWidget(self.grid)
        self.grid.cards.set_loading(12)
        self.ctx.runner.submit(self.ctx.catalog.search_rated, query,
                               on_done=lambda results, q=query: self._show(q, results),
                               on_error=self._error, group="search")

    def _browse(self, query: str, f: Filters) -> None:
        what = f.describe() or "Everything"
        self.status.setText(f"Finding {what}{f' matching “{query}”' if query else ''}…")
        self.stack.setCurrentWidget(self.grid)
        self.grid.cards.set_loading(12)
        self.ctx.runner.submit(
            self.ctx.catalog.anilist.browse, search=query or None, genres=f.genres, year=f.year,
            season=f.season, formats=[f.format] if f.format else None, status=f.status, sort=f.sort,
            on_done=lambda items, q=query, w=what: self._show_browse(q, w, items),
            on_error=self._error, group="search",
        )

    def _show_browse(self, query: str, what: str, items) -> None:
        self._last_browse = (query, what, items)
        items, hidden = visible(self.ctx, items)
        self._set_hidden(hidden)
        if not items:
            self.status.setText("")
            self.empty.setText("Nothing matches these filters. Try fewer of them.")
            self.stack.setCurrentWidget(self.empty)
            return
        self.status.setText(f"{len(items)} show{'s' if len(items) != 1 else ''} · {what}{f' · “{query}”' if query else ''}  "
                            "(from AniList; a few may not be on hianime)")
        self.grid.cards.set_cards(decorate_all(self.ctx, [media_card(m) for m in items]))
        self.stack.setCurrentWidget(self.grid)

    def _show(self, query: str, results) -> None:
        self._last_text = (query, results)
        rated = list(results)
        if hiding(self.ctx):
            results = [r for r in rated if not self.ctx.catalog.is_mature(r)]
        hidden = len(rated) - len(results)
        self._set_hidden(hidden)
        if not results:
            self.status.setText("")
            self.empty.setText(html.escape(f"Every result for “{query}” is 18+, and your setting hides those."
                                           if hidden else
                                           f"No results for “{query}”. Try the Japanese title or fewer words."))
            self.stack.setCurrentWidget(self.empty)
            return
        self.status.setText(f"{len(results)} result{'' if len(results) == 1 else 's'} for “{query}”")
        self.grid.cards.set_cards(decorate_all(self.ctx, [
            Card(key=f"show:{r.anime_id}", title=r.title, cover=r.poster, payload=r) for r in results
        ]))
        self.stack.setCurrentWidget(self.grid)

    def _set_hidden(self, count: int) -> None:
        if count:
            self.hidden_note.setText(f"{count} result{'s' if count != 1 else ''} hidden by your 18+ setting · "
                                     "<a href='#show' style='color:#FF8559'>Show them</a>")
        self.hidden_note.setVisible(bool(count))

    def _show_hidden(self) -> None:
        self.ctx.set_pref("hide_mature", False)

    def apply_content_filter(self) -> None:
        """Hide 18+ shows changed: redo the results on screen."""
        if self.filter_bar.filters().active and getattr(self, "_last_browse", None):
            self._show_browse(*self._last_browse)
        elif getattr(self, "_last_text", None):
            self._show(*self._last_text)

    def _error(self, message: str) -> None:
        self._last_key = None  # allow retrying the same search
        self.status.setText("")
        if "VPN" in message:
            self.empty.setText(f"{html.escape(message)}<br><br>"
                               "<a href='#setup' style='color:#FF8559'>Check the connection</a>")
        else:
            self.empty.setText(html.escape(f"Search failed: {message}"))
        self.stack.setCurrentWidget(self.empty)
