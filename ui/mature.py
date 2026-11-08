"""18+ shows in the UI: what to hide, what to blur, and the "Show anyway?" window.

Hide 18+ shows (Settings → Content, on by default) keeps 18+ shows out of everything
AniGUI suggests: Home, Search, Calendar, Related. Shows you picked yourself (My List,
Continue Watching) stay, with their posters blurred. Opening one asks first, unless you
said not to ask again for that show.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from core.anilist import Media

from .cards import Card
from .context import AppContext
from .widgets import PosterWidget


def hiding(ctx: AppContext) -> bool:
    return bool(ctx.pref("hide_mature"))


def flags_for(ctx: AppContext, item) -> tuple[bool, tuple[str, ...], bool, int | None]:
    """(mature, notes, allowed, anilist_id) for a Media, a Show, or anything with an anime_id."""
    if isinstance(item, Media):
        saved = ctx.store.maturity(item.anilist_id)
        m = item.maturity
        return m.mature, m.notes, bool(saved and saved[2]), item.anilist_id
    anilist_id = getattr(item, "anilist_id", None)
    anime_id = item[0] if isinstance(item, tuple) else getattr(item, "anime_id", None)
    if anilist_id is None and anime_id:
        anilist_id = getattr(ctx.catalog, "_mature_by_anime", {}).get(anime_id)
    if anilist_id is None and anime_id:
        show = ctx.store.get_show(anime_id)
        anilist_id = show.anilist_id if show else None
    saved = ctx.store.maturity(anilist_id)
    if not saved:
        return False, (), False, anilist_id
    return saved[0], saved[1], saved[2], anilist_id


def status_known(ctx: AppContext, item) -> bool:
    """Do we already know whether this is 18+? (A Media always says; a saved show only once
    it has been looked up.)"""
    if isinstance(item, Media):
        return True
    _m, _n, _a, anilist_id = flags_for(ctx, item)
    return ctx.store.maturity(anilist_id) is not None


def visible(ctx: AppContext, medias: Iterable[Media], suggest: bool = True) -> tuple[list[Media], int]:
    """The shows to suggest, and how many were left out by Hide 18+ shows. Suggestions also
    leave out shows you said you're not interested in (2.0); search (suggest=False) doesn't."""
    medias = list(medias)
    if suggest:
        skip = ctx.store.not_interested_ids()
        if skip:
            medias = [m for m in medias if getattr(m, "anilist_id", None) not in skip]
    if not hiding(ctx):
        return medias, 0
    kept = [m for m in medias if not m.maturity.mature]
    return kept, len(medias) - len(kept)


def decorate(ctx: AppContext, card: Card) -> Card:
    """Add the 18+ badge, and blur the poster of a hidden-but-yours show."""
    if card.payload is None or card.is_skeleton:
        return card
    mature, _notes, allowed, _id = flags_for(ctx, card.payload)
    if not mature:
        return card
    return replace(card, mature=True, blur=hiding(ctx) and not allowed)


def decorate_all(ctx: AppContext, cards: Iterable[Card]) -> list[Card]:
    return [decorate(ctx, c) for c in cards]


class MatureDialog(QDialog):
    """'Contains mature content. Show anyway?' with Don't ask again for this show."""

    def __init__(self, ctx: AppContext, title: str, notes: tuple[str, ...], cover: str | None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MatureDialog")
        self.setWindowTitle("Mature content")
        self.setModal(True)
        self.setFixedWidth(460)

        poster = PosterWidget(ctx.images, 84, 126)
        poster.blur = True
        poster.set_cover(cover, label=title)

        badge = QLabel("18+", objectName="MatureBadge")
        kicker = QLabel("Mature content", objectName="Muted")
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(badge)
        top.addWidget(kicker)
        top.addStretch(1)
        name = QLabel(title, objectName="MatureTitle", wordWrap=True)
        name.setTextFormat(Qt.TextFormat.PlainText)
        why = QLabel("This show is marked 18+. It's hidden because Hide 18+ shows is on.", wordWrap=True,
                     objectName="MatureText")
        notes_row = QHBoxLayout()
        notes_row.setSpacing(6)
        for note in notes:
            pill = QLabel(note, objectName="ContentPill")
            pill.setTextFormat(Qt.TextFormat.PlainText)
            notes_row.addWidget(pill)
        notes_row.addStretch(1)

        info = QVBoxLayout()
        info.setSpacing(6)
        info.addLayout(top)
        info.addWidget(name)
        info.addWidget(why)
        info.addLayout(notes_row)
        info.addStretch(1)

        head = QHBoxLayout()
        head.setSpacing(16)
        head.addWidget(poster, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(info, 1)

        self.dont_ask = QCheckBox("Don't ask again for this show", cursor=Qt.CursorShape.PointingHandCursor)
        hint = QLabel("Change this in Settings → Content", objectName="Muted")
        back = QPushButton("Go back", cursor=Qt.CursorShape.PointingHandCursor)
        show = QPushButton("Show anyway", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.reject)
        show.clicked.connect(self.accept)
        back.setDefault(True)   # Return / Esc both stay on the safe side

        buttons = QHBoxLayout()
        buttons.addWidget(hint)
        buttons.addStretch(1)
        buttons.addWidget(back)
        buttons.addWidget(show)

        col = QVBoxLayout(self)
        col.setContentsMargins(20, 20, 20, 16)
        col.setSpacing(14)
        col.addLayout(head)
        col.addWidget(self.dont_ask)
        col.addLayout(buttons)


def confirm_open(ctx: AppContext, item, parent: QWidget | None = None, ask=None) -> bool:
    """True if `item` may be opened. Asks first for a hidden 18+ show. `ask` replaces the
    dialog in tests: ask(title, notes) -> (open: bool, dont_ask_again: bool)."""
    if not hiding(ctx):
        return True
    mature, notes, allowed, anilist_id = flags_for(ctx, item)
    if not mature or allowed:
        return True
    title = getattr(item, "display_title", None) or getattr(item, "title", "") or "This show"
    if isinstance(item, tuple):
        title = item[1]
    if ask is None:
        cover = getattr(item, "cover", None) or getattr(item, "poster", None)
        dlg = MatureDialog(ctx, title, notes, cover, parent)
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        result = (ok, dlg.dont_ask.isChecked())
    else:
        result = ask(title, notes)
    ok, dont_ask = result
    if ok and dont_ask and anilist_id:
        ctx.store.allow_mature(anilist_id)
    return ok
