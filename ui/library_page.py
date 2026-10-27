"""My List: shows the user saved."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStackedLayout, QVBoxLayout, QWidget

from .cards import CardGrid
from .context import AppContext
from .home_page import show_card
from .widgets import empty_state


class LibraryPage(QWidget):
    openItem = Signal(object)  # Show

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Page")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.count = QLabel("", objectName="SectionCount")
        header = QHBoxLayout()
        header.setContentsMargins(10, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(QLabel("My List", objectName="SectionTitle"))
        header.addWidget(self.count)
        header.addStretch(1)

        self.grid = CardGrid(ctx.images)
        self.grid.cardActivated.connect(lambda card: self.openItem.emit(card.payload))
        self.empty = empty_state("Nothing saved yet. Open any show and press “+ My List”.")
        body = QWidget()
        self.stack = QStackedLayout(body)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.grid)

        col = QVBoxLayout(self)
        col.setContentsMargins(34, 36, 30, 0)
        col.setSpacing(16)
        col.addLayout(header)
        col.addWidget(body, 1)

    def refresh(self) -> None:
        shows = self.ctx.store.library()
        self.count.setText(str(len(shows)) if shows else "")
        self.grid.cards.set_cards([show_card(s) for s in shows])
        self.stack.setCurrentWidget(self.grid if shows else self.empty)
        for show in shows:
            if not show.poster:
                self.ctx.runner.submit(self.ctx.catalog.cover_for, show.anime_id, show.title,
                                       on_done=lambda url, aid=show.anime_id: url and self.grid.cards.update_card(f"show:{aid}", cover=url))
