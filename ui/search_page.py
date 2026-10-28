"""Search hianime (what can actually be streamed) as you type."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QStackedLayout, QVBoxLayout, QWidget

from .cards import Card, CardGrid
from .context import AppContext
from .widgets import empty_state

DEBOUNCE_MS = 350


class SearchPage(QWidget):
    openItem = Signal(object)  # SearchResult
    setupRequested = Signal()

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Page")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        title = QLabel("Search", objectName="SectionTitle")
        self.box = QLineEdit(objectName="SearchBox", placeholderText="Search for a show…  (⌘F)")
        self.box.setClearButtonEnabled(True)
        self.status = QLabel("", objectName="Muted")

        self.grid = CardGrid(ctx.images)
        self.grid.cardActivated.connect(lambda card: self.openItem.emit(card.payload))
        self.empty = empty_state("Find anything on hianime: titles in English or Japanese both work.")
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
        top.setSpacing(14)
        top.addWidget(title)
        top.addWidget(self.box)
        top.addWidget(self.status)
        col.addLayout(top)
        col.addWidget(self.results, 1)

        self._debounce = QTimer(self, singleShot=True, interval=DEBOUNCE_MS)
        self._debounce.timeout.connect(self._search)
        self.box.textChanged.connect(lambda _t: self._debounce.start())
        self.box.returnPressed.connect(self._search)
        self._last_query = ""

    def focus_search(self) -> None:
        self.box.setFocus()
        self.box.selectAll()

    def _search(self) -> None:
        self._debounce.stop()
        query = self.box.text().strip()
        if query == self._last_query:
            return
        self._last_query = query
        if len(query) < 2:
            self.status.setText("")
            self.stack.setCurrentWidget(self.empty)
            self.empty.setText("Find anything on hianime: titles in English or Japanese both work.")
            return
        self.status.setText(f"Searching for “{query}”…")
        self.stack.setCurrentWidget(self.grid)
        self.grid.cards.set_loading(12)
        self.ctx.runner.submit(self.ctx.catalog.hianime.search, query,
                               on_done=lambda results, q=query: self._show(q, results),
                               on_error=self._error, group="search")

    def _show(self, query: str, results) -> None:
        if not results:
            self.status.setText("")
            self.empty.setText(f"No results for “{query}”. Try the Japanese title or fewer words.")
            self.stack.setCurrentWidget(self.empty)
            return
        self.status.setText(f"{len(results)} results for “{query}”")
        self.grid.cards.set_cards([
            Card(key=f"show:{r.anime_id}", title=r.title, cover=r.poster, payload=r) for r in results
        ])
        self.stack.setCurrentWidget(self.grid)

    def _error(self, message: str) -> None:
        self._last_query = ""  # allow retrying the same text
        self.status.setText("")
        if "VPN" in message:
            self.empty.setText(f"{message}<br><br><a href='#setup' style='color:#FF8559'>Check the connection</a>")
        else:
            self.empty.setText(f"Search failed: {message}")
        self.stack.setCurrentWidget(self.empty)
