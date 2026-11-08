"""Show details: backdrop header, actions, sub/dub + quality, and the episode grid."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core import holiday
from core.anilist import Media
from core.hianime import Episode
from core.seasons import Series
from core.store import episode_key

from .cards import CardRow, media_card
from . import theme
from .content_notes import ContentLine
from .library import ListsButton, YourNotes
from .festive import BowPop
from .theater import Theater, nice_date
from .motion import fade_in
from .mature import confirm_open, decorate_all, hiding, visible
from .context import AppContext
from .episodes import (PER_PAGE, EpisodeGrid, EpisodeItem, EpisodePager, coming_soon, find_episode, has_title,
                       page_ranges)
from .hero import Backdrop, airing_note, media_meta, truncate
from .playback import PlaybackController
from .seasons import UPCOMING, SeasonsRow, SeasonState, UpNextCard
from .widgets import Combo, PosterWidget, WrapLabel

QUALITIES = [("Best", "best"), ("1080p", "1080"), ("720p", "720"), ("480p", "480")]


class StickyBar(QWidget):
    """Pinned to the top of the show page once its header has scrolled away:
    Back, a tiny poster, the title, where you are, and Play."""

    def __init__(self, images, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("StickyBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.back = QPushButton("‹  Back", objectName="Back", cursor=Qt.CursorShape.PointingHandCursor)
        self.poster = PosterWidget(images, 26, 38)
        self.title = QLabel("", objectName="StickyTitle")
        self.where = QLabel("", objectName="Muted")
        for label in (self.title, self.where):
            label.setTextFormat(Qt.TextFormat.PlainText)
        self.play = QPushButton("▶  Play", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(self.title)
        text.addWidget(self.where)
        row = QHBoxLayout(self)
        row.setContentsMargins(44, 10, 44, 10)
        row.setSpacing(14)
        row.addWidget(self.back)
        row.addWidget(self.poster)
        row.addLayout(text, 1)
        row.addWidget(self.play)
        self.setFixedHeight(62)
        self.hide()


class DetailPage(QScrollArea):
    backRequested = Signal()
    openItem = Signal(object)  # Media from the Related / You might also like rows
    openNext = Signal(object)  # Media: Up next's "Start Season 3" (opens and plays)
    libraryChanged = Signal()
    toast = Signal(str, bool)  # message, is_error
    bound = Signal(str)        # now showing this hianime id

    def __init__(self, ctx: AppContext, playback: PlaybackController, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.playback = playback
        self.setObjectName("Page")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.gen = 0
        self.anime_id: str | None = None
        self.show_title = ""               # hianime title; what ani-cli searches for
        self.media: Media | None = None
        self.episodes: list[Episode] = []
        self.play_target: str | None = None
        self.autoplay: bool | str = False   # True: Up Next; an episode number: that one
        self._related_for: int | None = None
        self.pending_mature_checked = False   # set by the window: did opening already check 18+?
        self.mature_checked = False
        self.fillers = None                # core.fillers.FillerInfo for this show
        self._fillers_for = None
        self.page: int | None = None       # None = pick the page with Up Next
        self.jumped_to: str | None = None
        self.stills: dict[str, str] = {}
        self._stills_asked: set[tuple] = set()
        self.current_item = None           # what was opened (Media or Show), for Back between shows

        # Header
        self.header = Backdrop(ctx.images)
        self.header.dim = 0.25
        self.header.setMinimumHeight(430)
        self.back = QPushButton("‹  Back", objectName="Back", cursor=Qt.CursorShape.PointingHandCursor)
        self.back.clicked.connect(self.backRequested)
        self.poster = PosterWidget(ctx.images)
        self.kicker = QLabel("", objectName="Kicker")
        self.title = QLabel("", objectName="DetailTitle", wordWrap=True)
        self.meta = QLabel("", objectName="Meta", wordWrap=True)
        self.airing = QLabel("", objectName="Kicker")
        self.filler_note = QLabel("", objectName="FillerNote")
        self.filler_note.setVisible(False)
        self.mature_badge = QLabel("18+", objectName="MatureBadge")
        self.mature_badge.setVisible(False)
        self.content_row = ContentLine()   # Content: tags with hover meters, and the ⓘ explainer
        self.content_row.setVisible(False)
        self.synopsis = WrapLabel("", 720, objectName="Synopsis")
        for label in (self.kicker, self.title, self.meta, self.airing, self.filler_note, self.synopsis):
            label.setTextFormat(Qt.TextFormat.PlainText)   # text from AniList / hianime
        self.synopsis.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.play_btn = QPushButton("▶  Play", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        self.play_btn.clicked.connect(self._play_clicked)
        self.rewatch_btn = QPushButton("Stop rewatching", objectName="LinkButton", cursor=Qt.CursorShape.PointingHandCursor)
        self.rewatch_btn.setToolTip("Go back to where you were before (your watched episodes never changed)")
        self.rewatch_btn.clicked.connect(self._stop_rewatch)
        self.rewatch_btn.setVisible(False)
        self.list_btn = QPushButton("+  Save", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.list_btn.clicked.connect(self._toggle_library)
        self.lists_btn = ListsButton(ctx.store)           # your own lists (2.0)
        self.lists_btn.changed.connect(self.libraryChanged)
        self.bow = BowPop(self)
        self.sub_btn = QPushButton("Sub", objectName="Toggle", checkable=True, cursor=Qt.CursorShape.PointingHandCursor)
        self.dub_btn = QPushButton("Dub", objectName="Toggle", checkable=True, cursor=Qt.CursorShape.PointingHandCursor)
        self.mode = QButtonGroup(self)
        self.mode.addButton(self.sub_btn)
        self.mode.addButton(self.dub_btn)
        (self.dub_btn if ctx.pref("dub", False) else self.sub_btn).setChecked(True)
        self.dub_btn.toggled.connect(lambda on: ctx.set_pref("dub", on))
        self.quality = Combo(cursor=Qt.CursorShape.PointingHandCursor)
        for label, value in QUALITIES:
            self.quality.addItem(label, value)
        saved = str(ctx.pref("quality", "best"))
        self.quality.setCurrentIndex(max(0, self.quality.findData(saved)))
        self.quality.currentIndexChanged.connect(lambda _i: ctx.set_pref("quality", self.quality.currentData()))
        self.quality.setToolTip("Stream quality (falls back to best if unavailable)")
        ctx.events.changed.connect(self._pref_changed)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addWidget(self.play_btn)
        actions.addWidget(self.rewatch_btn)
        actions.addWidget(self.list_btn)
        actions.addWidget(self.lists_btn)
        actions.addSpacing(14)
        actions.addWidget(self.sub_btn)
        actions.addWidget(self.dub_btn)
        actions.addWidget(self.quality)
        actions.addStretch(1)

        info = QVBoxLayout()
        info.setSpacing(9)
        info.addStretch(1)
        info.addWidget(self.kicker)
        info.addWidget(self.title)
        meta_row = QHBoxLayout()
        meta_row.setSpacing(10)
        meta_row.addWidget(self.mature_badge)
        meta_row.addWidget(self.meta, 1)
        info.addLayout(meta_row)
        info.addWidget(self.airing)
        info.addWidget(self.filler_note)
        info.addWidget(self.content_row)
        info.addSpacing(2)
        info.addWidget(self.synopsis)
        info.addSpacing(10)
        info.addLayout(actions)

        top = QHBoxLayout()
        top.setSpacing(30)
        top.addWidget(self.poster, 0, Qt.AlignmentFlag.AlignBottom)
        top.addLayout(info, 1)

        head = QVBoxLayout(self.header)
        head.setContentsMargins(44, 22, 44, 26)
        head.addWidget(self.back, 0, Qt.AlignmentFlag.AlignLeft)
        head.addStretch(1)
        head.addLayout(top)

        # Episodes
        self.ep_title = QLabel("Episodes", objectName="SectionTitle")
        self.ep_count = QLabel("", objectName="SectionCount")
        self.status = QLabel("", objectName="Muted")
        ep_head = QHBoxLayout()
        ep_head.setContentsMargins(5, 0, 5, 0)
        ep_head.setSpacing(10)
        ep_head.addWidget(self.ep_title)
        ep_head.addWidget(self.ep_count)
        ep_head.addStretch(1)
        ep_head.addWidget(self.status)
        self.pager = EpisodePager()
        self.pager.pageChosen.connect(self._go_page)
        self.pager.jumpRequested.connect(self._jump)
        self.pager.setVisible(False)
        self.pager.hide_fillers.setChecked(bool(ctx.pref("hide_fillers")))
        self.pager.skip_fillers.setChecked(bool(ctx.pref("skip_fillers")))
        self.pager.hide_fillers.toggled.connect(lambda on: ctx.set_pref("hide_fillers", on))
        self.pager.skip_fillers.toggled.connect(lambda on: ctx.set_pref("skip_fillers", on))
        self.grid = EpisodeGrid(ctx.images)
        self.grid.episodeClicked.connect(self.play)
        self.grid.markRequested.connect(self._mark)
        self.message = QLabel("", objectName="EmptyState", wordWrap=True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.message.setContentsMargins(5, 0, 5, 0)

        # Seasons of the series (AniList prequels/sequels), and Up next after the last episode
        self.seasons_row = SeasonsRow(ctx.images)
        self.seasons_row.setContentsMargins(5, 0, 5, 0)
        self.seasons_row.openMedia.connect(self.openItem)
        self.up_next = UpNextCard(ctx.images)
        self.up_next.start.connect(lambda media: self.openNext.emit(media))
        self.series: Series | None = None

        episodes = QVBoxLayout()
        episodes.setContentsMargins(39, 10, 39, 40)
        episodes.setSpacing(12)
        self.yours = YourNotes(ctx.store)                 # your rating, tags and note (2.0)
        self.yours.setVisible(False)
        episodes.addWidget(self.yours)
        episodes.addSpacing(10)
        episodes.addWidget(self.seasons_row)
        episodes.addSpacing(8)
        # The episode grid (it steps aside while the built-in player's list is showing)
        self.episodes_box = QWidget()
        box = QVBoxLayout(self.episodes_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)
        box.addLayout(ep_head)
        box.addWidget(self.message)
        box.addWidget(self.pager)
        box.addWidget(self.grid)
        box.addWidget(self.up_next)
        episodes.addWidget(self.episodes_box)

        # More like this (AniList)
        self.related_row = CardRow("Related", ctx.images)
        self.recs_row = CardRow("You might also like", ctx.images)
        for row in (self.related_row, self.recs_row):
            row.setContentsMargins(5, 0, 5, 0)
            row.cardActivated.connect(lambda card: self.openItem.emit(card.payload))
            row.cardMenuRequested.connect(self._suggestion_menu)
            row.setVisible(False)
            episodes.addSpacing(22)
            episodes.addWidget(row)
        episodes.addStretch(1)

        # The built-in player plays here (the video floats over theater.slot)
        self.theater = Theater(ctx.images, QUALITIES)
        self.theater.episodeClicked.connect(self.play)
        self.theater.listToggled.connect(self._toggle_library)
        self.theater.rail.markRequested.connect(self._mark)
        self.theater.rail.fillersToggled.connect(lambda key, on: ctx.set_pref(key, on))
        self.theater.dubChanged.connect(self._theater_dub)
        self.theater.qualityChanged.connect(self._theater_quality)
        self.theater.openOutside.connect(self._open_outside)
        self.theater.setVisible(False)
        self.ep_details: dict[str, dict] = {}
        self._details_for = None

        body = QWidget(objectName="PageBody")
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self.theater)
        col.addWidget(self.header)
        col.addLayout(episodes, 1)
        self.setWidget(body)

        self.sticky = StickyBar(ctx.images, self)
        self._bar_room = False
        self._adjusting = False
        self.sticky.back.clicked.connect(self.backRequested)
        self.sticky.play.clicked.connect(self._sticky_play)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._update_sticky())

        playback.busy.connect(self._on_busy)
        playback.started.connect(self._on_started)
        playback.failed.connect(self._on_failed)
        playback.progressSaved.connect(self._on_progress)
        playback.episodeChanged.connect(lambda aid, _ep: aid == self.anime_id and self._refresh_episode_states())
        playback.sessionEnded.connect(lambda: self._refresh_episode_states())

    # -- opening ------------------------------------------------------------------------

    def open_media(self, media: Media, autoplay: bool | str = False) -> None:
        """From an AniList card: find it on hianime first."""
        self._reset(autoplay)
        self.current_item = media
        self._show_media(media)
        self._set_status("Checking availability…")
        gen = self.gen
        self.ctx.runner.submit(
            self.ctx.catalog.find_streamable, media,
            on_done=lambda result: self._on_found(gen, result),
            on_error=lambda msg: self._on_load_error(gen, msg), group="detail-find",
        )

    def open_show(self, anime_id: str, title: str, poster: str | None = None, autoplay: bool | str = False) -> None:
        """From search, history or My List: we already know the hianime id."""
        self._reset(autoplay)
        self.current_item = (anime_id, title, poster)
        self.title.setText(title)
        self.poster.set_cover(poster, label=title)
        self.header.set_image(None, poster)
        gen = self.gen
        self._bind_show(anime_id, title, poster)
        self.ctx.runner.submit(
            self.ctx.catalog.enrich, anime_id, title, poster,
            on_done=lambda media: gen == self.gen and media and self._show_media(media, keep_poster=bool(poster)),
            group="detail-enrich",
        )

    def _reset(self, autoplay: bool | str) -> None:
        self.gen += 1
        self.anime_id, self.media, self.episodes, self.play_target = None, None, [], None
        self.autoplay = autoplay
        for w in (self.kicker, self.meta, self.airing, self.synopsis, self.message, self.ep_count):
            w.setText("")
        self._show_content(None)
        self._related = None
        self.airing.setVisible(False)
        self.message.setVisible(False)
        self.grid.model_.set_items([])
        self.grid.set_tile_color(None)
        self.page, self.jumped_to, self.stills, self._stills_asked = None, None, {}, set()
        self.mature_checked, self.pending_mature_checked = self.pending_mature_checked, False
        self.fillers, self._fillers_for = None, None
        self.filler_note.setVisible(False)
        self.pager.setVisible(False)
        self.pager.jump.clear()
        self.pager.set_error("")
        self._related_for = None
        for row in (self.related_row, self.recs_row):
            row.set_cards([])
        self.series, self._seasons_for = None, None
        self.seasons_row.clear()
        self.up_next.show_for(None)
        self.play_btn.setEnabled(False)
        self.play_btn.setText("▶  Play")
        self.list_btn.setEnabled(False)
        self.yours.load(None)
        self.yours.setVisible(False)
        self.lists_btn.set_show(None)
        self.verticalScrollBar().setValue(0)
        self.ep_details, self._details_for = {}, None
        self.set_theater(False)

    def _show_media(self, media: Media, keep_poster: bool = False) -> None:
        self.media = media
        self.kicker.setText((media.status or "").replace("_", " ").upper())
        self.title.setText(media.display_title)
        self.meta.setText(media_meta(media))
        note = airing_note(media)
        self.airing.setText(note.upper() if note else "")
        self.airing.setVisible(bool(note))
        self.synopsis.setText(truncate(media.description, 520))
        if not keep_poster or not self.poster.url:
            self.poster.set_cover(media.cover, media.cover_color, media.display_title)
        self.header.set_image(media.banner, media.cover, media.cover_color)
        self.grid.set_tile_color(media.cover_color, media.banner or media.cover)
        self.ctx.catalog.remember_maturity(media)
        self._show_content(media)
        self._late_mature_check(media)
        if self.episodes:
            self._refresh_episode_states()   # Coming soon needs the airing info
        self._load_related(media)
        self._load_seasons(media)
        self._load_stills()
        self._load_fillers()

    # -- sticky bar ---------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.theater.slot.set_room(self.height())      # (not the viewport: the bar's strip changes it)
        self._update_sticky()

    def _sticky_play(self) -> None:
        if self.theater_on:
            self.verticalScrollBar().setValue(0)        # back to the video (it grows back)
        elif self.play_target:
            self.play(self.play_target)

    def _set_bar_room(self, on: bool) -> None:
        """The bar gets its own strip above the page instead of floating over it: nothing on
        top of the page lets the Mac reuse what's already drawn when you scroll (2.0). The
        scroll position shifts by the same amount, so nothing on the page moves."""
        if on == self._bar_room:
            return
        self._bar_room = on
        h = self.sticky.height()
        sb = self.verticalScrollBar()
        v = sb.value()
        self._adjusting = True
        try:
            self.setViewportMargins(0, h if on else 0, 0, 0)
            sb.setValue(v + h if on else max(0, v - h))
        finally:
            self._adjusting = False

    def _update_sticky(self) -> None:
        """Show the bar once the big header (and its Back button) is out of view."""
        if self._adjusting:
            return
        bar = self.sticky
        room = bar.height() if self._bar_room else 0
        top = self.verticalScrollBar().value() - room          # what's at the top of the window
        if self.theater_on:
            # Watching: once the video has scrolled away (it's in the corner now), the bar
            # keeps Back in reach and takes you back to the video
            slot = self.theater.slot
            scrolled_past = top > slot.geometry().bottom() * 0.65
        else:
            scrolled_past = top > self.header.height() - bar.height()
        self._set_bar_room(scrolled_past)
        vp = self.viewport().geometry()
        bar.setGeometry(vp.x(), vp.y() - (bar.height() if self._bar_room else 0), vp.width(), bar.height())
        if scrolled_past:
            bar.title.setText(self.title.text())
            bar.poster.set_cover(self.poster.url, self.poster.color, self.title.text())
            bar.poster.blur = self.poster.blur
            if self.theater_on:
                playing = self.playback.now_playing
                ep = playing[1] if playing and playing[0] == self.anime_id else ""
                name = self.theater.ep_title.text()
                bar.where.setText(f"▶ Playing episode {ep}" + (f" · {name}" if name and name != f"Episode {ep}" else ""))
                bar.play.setText("⤒  Back to the video")
                bar.play.setEnabled(True)
            else:
                bar.play.setText(self._short_play_text())
                bar.play.setEnabled(self.play_btn.isEnabled())
                bar.where.setText(self._where_text())
            bar.raise_()
            if bar.isHidden():
                fade_in(bar, 160)
        else:
            bar.setVisible(False)

    def _short_play_text(self) -> str:
        text = self.play_btn.text().split("  ·  ")[0]
        return text.replace("Episode ", "")

    def _where_text(self) -> str:
        bits = []
        if self.episodes and len(self.episodes) > PER_PAGE and self.page is not None:
            first, last, label = page_ranges([e.number for e in self.episodes])[self.page]
            bits.append(f"Episodes {label}")
        if self.play_target:
            bits.append(f"Up next: {self.play_target}")
        return " · ".join(bits)

    def _show_content(self, media: Media | None) -> None:
        """18+ badge and the Content line (nudity, gore…) from AniList's tags."""
        m = media.maturity if media else None
        self.mature_badge.setVisible(bool(m and m.mature))
        self.content_row.set_maturity(m)

    def _late_mature_check(self, media: Media) -> None:
        """A saved show nobody had checked turned out to be 18+ only now that its details
        loaded: ask the same question opening it would have asked."""
        if self.mature_checked:
            return
        self.mature_checked = True
        if not media.maturity.mature:
            return
        ask = getattr(self.window(), "mature_ask", None)
        gen = self.gen

        def check() -> None:
            if gen == self.gen and not confirm_open(self.ctx, media, self, ask=ask):
                self.backRequested.emit()

        QTimer.singleShot(0, check)   # after this page has painted

    def apply_content_filter(self) -> None:
        """Hide 18+ shows changed: the Related rows follow it."""
        if getattr(self, "_related", None):
            self._show_related(*self._related)

    def _load_related(self, media: Media) -> None:
        if getattr(self, "_related_for", None) == media.anilist_id:
            return
        self._related_for = media.anilist_id
        gen = self.gen
        self.ctx.runner.submit(self.ctx.catalog.anilist.related, media.anilist_id,
                               on_done=lambda result: gen == self.gen and self._show_related(*result),
                               group="detail-related")

    # -- seasons ------------------------------------------------------------------------

    def _load_seasons(self, media: Media) -> None:
        if getattr(self, "_seasons_for", None) == media.anilist_id:
            return
        self._seasons_for = media.anilist_id
        gen = self.gen
        self.ctx.runner.submit(self.ctx.catalog.series, media,
                               on_done=lambda series: gen == self.gen and self._show_series(series),
                               group="detail-seasons")

    def _show_series(self, series: Series) -> None:
        self.series = series
        self._refresh_seasons()
        if self._related is not None:
            self._show_related(*self._related)       # its sequels and prequels are in Seasons now

    def _refresh_seasons(self) -> None:
        """Season cards and Up next, from what you've watched (cheap: no network)."""
        series, media = self.series, self.media
        if series is None or media is None:
            return
        hide = hiding(self.ctx)
        states: dict[int, SeasonState] = {}
        for s in series.seasons:
            m = s.media
            show = self.ctx.store.find_by_anilist(m.anilist_id)
            if m.anilist_id == media.anilist_id and self.anime_id:
                show = self.ctx.store.get_show(self.anime_id) or show
            watched = 0
            if show:
                watched = sum(1 for p in self.ctx.store.show_progress(show.anime_id).values() if p.completed)
            states[m.anilist_id] = SeasonState(watched, m.episodes, m.anilist_id == media.anilist_id,
                                               hide and m.maturity.mature)
        hidden = {m.anilist_id for m in series.extras if hide and m.maturity.mature}
        self.seasons_row.set_series(series, states, hidden)
        current = series.find(media.anilist_id)
        nxt = series.after(media.anilist_id)
        done = current is not None and states[media.anilist_id].done and (current.media.status or "") == "FINISHED"
        ready = nxt is not None and (nxt.media.status or "") not in UPCOMING
        self.up_next.show_for(nxt if done and ready and not (hide and nxt.media.maturity.mature) else None)

    def _show_related(self, related, recs) -> None:
        self._related = (related, recs)
        hide = hiding(self.ctx)
        in_seasons: set[int] = set()
        if self.series is not None and self.series.worth_showing:
            in_seasons = {s.media.anilist_id for s in self.series.seasons} | {m.anilist_id for m in self.series.extras}
        cards = []
        for r in related:
            if hide and r.media.maturity.mature:
                continue
            if r.media.anilist_id in in_seasons:
                continue
            card = media_card(r.media)
            cards.append(replace(card, badge=r.label.upper()))
        self.related_row.set_cards(decorate_all(self.ctx, cards))
        recs, _hidden = visible(self.ctx, recs)
        self.recs_row.set_cards(decorate_all(self.ctx, [media_card(m) for m in recs]))

    def _on_found(self, gen: int, result) -> None:
        if gen != self.gen:
            return
        if result is None:
            self._set_status("")
            self._show_message("This show isn't on hianime yet, or its title there is too different to match. "
                               "Try Search with another title.")
            return
        poster = result.poster or (self.media.cover if self.media else None)
        self._bind_show(result.anime_id, result.title, poster)

    def _bind_show(self, anime_id: str, title: str, poster: str | None) -> None:
        self.anime_id, self.show_title = anime_id, title
        self.ctx.store.upsert_show(anime_id, title, poster)
        self.list_btn.setEnabled(True)
        self._refresh_library_button()
        self._set_status("Loading episodes…")
        self.bound.emit(anime_id)
        gen = self.gen
        self.ctx.runner.submit(
            self.ctx.catalog.episodes_for, anime_id, title,
            on_done=lambda result: self._on_episodes(gen, *result),
            on_error=lambda msg: self._on_load_error(gen, msg), group="detail-episodes",
        )

    def _on_episodes(self, gen: int, anime_id: str, title: str, episodes: list[Episode]) -> None:
        if gen != self.gen:
            return
        if anime_id != self.anime_id:  # stale id was repaired; progress moved with it
            self.anime_id, self.show_title = anime_id, title
            self._refresh_library_button()
            self.libraryChanged.emit()  # Home's Continue Watching should show the new id
        self.episodes = episodes
        self._set_status("")
        if episodes:  # opening a show clears its "new episodes" badge
            had_new = any(n.show.anime_id == anime_id for n in self.ctx.store.new_episodes())
            newest = max(episodes, key=lambda e: episode_key(e.number)).number
            self.ctx.store.set_latest(anime_id, newest, seen=True)
            self.ctx.store.mark_episodes_seen(anime_id)
            if had_new:
                self.libraryChanged.emit()
        if not episodes:
            self._show_message("No episodes listed yet.")
            return
        self.ep_count.setText(f"{len(episodes):,}")
        self._refresh_episode_states()
        self._load_stills()
        self._load_fillers()
        if isinstance(self.autoplay, str) and any(ep.number == self.autoplay for ep in episodes):
            number, self.autoplay = self.autoplay, False
            self.play(number)
        elif self.autoplay and self.play_target:
            self.autoplay = False
            self.play(self.play_target)

    def _on_load_error(self, gen: int, message: str) -> None:
        if gen == self.gen:
            self._set_status("")
            self._show_message(f"Couldn't load this show: {message}")

    # -- state --------------------------------------------------------------------------

    def _refresh_episode_states(self) -> None:
        if not self.anime_id or not self.episodes:
            return
        progress = self.ctx.store.show_progress(self.anime_id)
        numbers = [ep.number for ep in self.episodes]
        self.refresh_theater()
        fillers = self.fillers
        skippable = fillers.skippable(numbers) if fillers else set()
        skip = skippable if self.ctx.pref("skip_fillers") else set()
        target, kind = self.ctx.catalog.resume_episode(self.anime_id, self.episodes, skip=skip)
        rw = self.ctx.store.rewatch(self.anime_id)          # Rewatch mode (2.0): your place this time round
        if rw:
            target = next((e for e in self.episodes if e.number == rw[0]), target)
            p = progress.get(target.number) if target else None
            kind = "rewatching_resume" if (p and not p.completed and p.position > 30) else "rewatching"
        self.rewatch_btn.setVisible(bool(rw))
        self.play_target = target.number if target else None
        self._up_next_number = target.number if target else None
        busy = self.playback.active
        playing = self.playback.now_playing
        pages = page_ranges(numbers)
        if self.page is None:  # first time: open on the page with Up Next
            at = numbers.index(target.number) if target and target.number in numbers else 0
            self.page = at // PER_PAGE
        self.page = max(0, min(self.page, len(pages) - 1))
        first, last, _label = pages[self.page]
        self.pager.configure(paged=len(pages) > 1, fillers=bool(skippable))
        if len(pages) > 1:
            self.pager.set_pages([label for _a, _b, label in pages], self.page)
        hide = bool(skippable) and self.ctx.pref("hide_fillers")
        xmas = holiday.christmas_episodes_for(self.media.anilist_id if self.media else None)
        items = []
        for ep in self.episodes[first:last]:
            p = progress.get(ep.number)
            state = "watched" if p and p.completed else ("progress" if p else "new")
            shield = self._shielded(ep.number, p, playing[1] if playing and playing[0] == self.anime_id else None)
            item = EpisodeItem(
                shield=shield,
                number=ep.number, title=None if shield else ep.title, state=state, fraction=p.fraction if p else 0.0,
                up_next=bool(target and kind in ("next", "resume", "rewatching", "rewatching_resume")
                             and ep.number == target.number),
                busy=None,
                playing=bool(playing and playing == (self.anime_id, ep.number)),
                still=self.stills.get(ep.number),
                hit=ep.number == self.jumped_to,
                kind=fillers.kind(ep.number) if fillers else None,
                christmas=ep.number in xmas,
            )
            if hide and item.kind and not (item.up_next or item.playing or item.hit):
                continue   # Hide fillers (but never the episode you're on or just jumped to)
            items.append(item)
        if self.page == len(pages) - 1:
            soon = self._coming_soon(numbers)
            if soon:
                items.append(soon)
        self.grid.model_.set_items(items)
        if busy and busy[0] == self.anime_id:
            self.grid.model_.set_busy(busy[1], "Starting…")
        labels = {"play": "▶  Play Episode {}", "resume": "▶  Resume Episode {}",
                  "next": "▶  Play Episode {}", "rewatch": "↺  Watch Again",
                  "rewatching": "↺  Rewatch Episode {}", "rewatching_resume": "↺  Resume Episode {}"}
        if kind == "rewatching_resume":
            kind_for_time = "resume"
        else:
            kind_for_time = kind
        text = labels[kind].format(target.number if target else "")
        resume_at = (self.playback.resume_position(self.anime_id, target.number)
                     if target and kind_for_time == "resume" else None)
        if resume_at:
            mins, secs = divmod(int(resume_at), 60)
            text += f"  ·  {mins}:{secs:02d}"
        self.play_btn.setText(text)
        self.play_btn.setEnabled(target is not None)
        self._update_sticky()
        self._refresh_seasons()

    def _shielded(self, number: str, p, playing: str | None) -> bool:
        """Spoiler shield: episodes past where you are keep their picture blurred and their
        title hidden (the one you're on, and anything watched, show normally)."""
        if not self.ctx.pref("spoiler_shield") or (p and p.completed) or number == playing:
            return False
        if p is not None:                          # partway through
            return False
        return number != getattr(self, "_up_next_number", None)

    def _coming_soon(self, numbers: list[str]) -> EpisodeItem | None:
        """The next episode of an airing show, if it's the one right after the last listed."""
        m = self.media
        if not m or not m.next_episode or not m.next_airing_at or str(m.next_episode) in numbers:
            return None
        try:
            last = max(int(float(n)) for n in numbers)
        except ValueError:
            return None
        if m.next_episode != last + 1:
            return None
        return coming_soon(m.next_episode, m.next_airing_at)

    # -- pages, jump, stills ------------------------------------------------------------

    def _go_page(self, page: int) -> None:
        self.page, self.jumped_to = page, None
        self.pager.set_error("")
        self._refresh_episode_states()
        self._load_stills()
        self._load_fillers()

    def _jump(self, text: str) -> None:
        numbers = [ep.number for ep in self.episodes]
        at = find_episode(numbers, text)
        if at is None:
            self.pager.set_error(f"No episode {text.strip()}")
            return
        self.page, self.jumped_to = at // PER_PAGE, numbers[at]
        self.pager.set_error("")
        self._refresh_episode_states()
        self._load_stills()
        self._load_fillers()
        QTimer.singleShot(0, lambda n=numbers[at]: self._scroll_to(n))

    def _scroll_to(self, number: str) -> None:
        row = self.grid.model_.row_of(number)
        if row is None:
            return
        rect = self.grid.visualRect(self.grid.model_.index(row))
        middle = self.grid.mapTo(self.widget(), rect.center()).y()
        self.verticalScrollBar().setValue(middle - self.viewport().height() // 2)

    def _load_stills(self) -> None:
        """Ask for this page's episode stills (once per show and page)."""
        stills = getattr(self.ctx, "stills", None)
        if stills is None or not self.media or not self.episodes or self.page is None:
            return
        key = (self.anime_id, self.media.anilist_id, self.page)
        if key in self._stills_asked:
            return
        self._stills_asked.add(key)
        first = self.page * PER_PAGE
        wanted = [(ep.number, ep.title) for ep in self.episodes[first:first + PER_PAGE]]
        media, gen = self.media, self.gen
        self.ctx.runner.submit(
            stills.for_episodes, media.anilist_id, media.mal_id, wanted,
            on_done=lambda found: gen == self.gen and self._on_stills(found),
            group=f"detail-stills-{self.page}",
        )

    def _load_fillers(self) -> None:
        """Which episodes are filler (Anime Filler List), once per show."""
        guide = getattr(self.ctx, "fillers", None)
        if guide is None or not self.media or not self.episodes:
            return
        key = (self.anime_id, self.media.anilist_id)
        if self._fillers_for == key:
            return
        self._fillers_for = key
        gen, titles = self.gen, [*self.media.all_titles, self.show_title]
        self.ctx.runner.submit(guide.for_titles, titles,
                               on_done=lambda info: gen == self.gen and self._on_fillers(info),
                               group="detail-fillers")

    def _on_fillers(self, info) -> None:
        self.fillers = info
        note = info.summary([ep.number for ep in self.episodes])
        self.filler_note.setText(note or "")
        self.filler_note.setVisible(bool(note))
        self._refresh_episode_states()

    def _on_stills(self, found: dict[str, str]) -> None:
        self.stills.update(found)
        self.grid.model_.set_stills(found)

    def _refresh_library_button(self) -> None:
        show = self.ctx.store.get_show(self.anime_id) if self.anime_id else None
        saved = bool(show and show.in_library)
        self.list_btn.setText("✓  Saved" if saved else "+  Save")
        self.theater.list_btn.setText(self.list_btn.text())
        self.lists_btn.set_show(self.anime_id)
        if self.yours.anime_id != self.anime_id:
            self.yours.load(self.anime_id)
        self.yours.setVisible(self.anime_id is not None)

    def _toggle_library(self) -> None:
        if not self.anime_id:
            return
        show = self.ctx.store.get_show(self.anime_id)
        adding = not (show and show.in_library)
        self.ctx.store.set_in_library(self.anime_id, adding)
        self._refresh_library_button()
        self.libraryChanged.emit()
        if adding and theme.HOLIDAY:
            self.toast.emit("🎁 Saved", False)
            btn = self.list_btn
            self.bow.pop(QPointF(btn.mapTo(self, btn.rect().center())))

    def _show_message(self, text: str) -> None:
        self.message.setText(text)
        self.message.setVisible(True)

    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    # -- playback -----------------------------------------------------------------------

    def play(self, episode: str) -> None:
        if not self.anime_id:
            return
        self.playback.play(self.anime_id, self.show_title, episode)

    def _on_busy(self, anime_id: str, episode: str, text: str) -> None:
        if anime_id == self.anime_id:
            self.grid.model_.set_busy(episode, text)
            self._set_status(f"Episode {episode}: {text}")

    def _on_started(self, anime_id: str, episode: str, kind: str) -> None:
        if anime_id == self.anime_id:
            self.grid.model_.set_busy(None)
            self._set_status("")
            self._refresh_episode_states()
        if kind != "anigui":
            self.toast.emit(f"Playing episode {episode} in {'IINA' if kind == 'iina' else 'mpv'}", False)

    def _on_failed(self, anime_id: str, episode: str, message: str) -> None:
        if anime_id == self.anime_id:
            self.grid.model_.set_busy(None)
            self._set_status("")
        self.toast.emit(f"Couldn't play episode {episode}: {message}", True)

    def _on_progress(self, anime_id: str, episode: str) -> None:
        if anime_id != self.anime_id:
            return
        p = self.ctx.store.get_progress(anime_id, episode)
        if p is None:
            return
        state = "watched" if p.completed else "progress"
        self.grid.model_.update_progress(episode, state, p.fraction, playing=True)
        rw = self.ctx.store.rewatch(anime_id)
        if p.completed and rw and rw[0] == episode:           # on to the next one this time round
            numbers = [e.number for e in self.episodes]
            i = numbers.index(episode) if episode in numbers else -1
            self.ctx.store.advance_rewatch(anime_id, numbers[i + 1] if 0 <= i < len(numbers) - 1 else None)

    def _suggestion_menu(self, card, pos) -> None:
        media = card.payload
        if not isinstance(media, Media):
            return
        menu = QMenu(self)
        menu.addAction("Not interested").triggered.connect(lambda: self._not_interested(media))
        menu.exec(pos)

    def _not_interested(self, media: Media) -> None:
        self.ctx.store.set_not_interested(media.anilist_id, media.display_title, True)
        self.apply_content_filter()
        self.libraryChanged.emit()          # (Home drops it too)
        self.toast.emit(f"You won't see {media.display_title} in suggestions.", False)

    def _play_clicked(self) -> None:
        if not self.play_target:
            return
        if self.play_btn.text().startswith("↺  Watch Again") and self.anime_id:
            self.ctx.store.start_rewatch(self.anime_id, self.play_target)     # Rewatch mode (2.0)
        self.play(self.play_target)

    def _stop_rewatch(self) -> None:
        if self.anime_id:
            self.ctx.store.stop_rewatch(self.anime_id)
            self._refresh_episode_states()
            self.libraryChanged.emit()

    def _mark(self, episode: str, action: str) -> None:
        if not self.anime_id:
            return
        if action == "rewatch":
            self.ctx.store.start_rewatch(self.anime_id, episode)
            self._refresh_episode_states()
            self.libraryChanged.emit()
            return
        if action == "upto":
            for ep in self.episodes:
                self.ctx.store.mark_watched(self.anime_id, ep.number, True)
                if ep.number == episode:
                    break
        else:
            self.ctx.store.mark_watched(self.anime_id, episode, action == "watched")
        self._refresh_episode_states()
        self.libraryChanged.emit()

    def _pref_changed(self, key: str, _value) -> None:
        """Keep the Sub/Dub, quality and filler controls in step with Settings."""
        if key in ("hide_fillers", "skip_fillers"):
            switch = self.pager.hide_fillers if key == "hide_fillers" else self.pager.skip_fillers
            switch.blockSignals(True)
            switch.setChecked(bool(self.ctx.pref(key)))
            switch.blockSignals(False)
            switch.update()
            self._refresh_episode_states()
            return
        if key == "dub":
            btn = self.dub_btn if self.ctx.pref("dub") else self.sub_btn
            if not btn.isChecked():
                btn.setChecked(True)
        elif key == "quality":
            i = max(0, self.quality.findData(str(self.ctx.pref("quality"))))
            if i != self.quality.currentIndex():
                self.quality.setCurrentIndex(i)

    # -- the built-in player's theater -----------------------------------------------------

    @property
    def theater_on(self) -> bool:
        return not self.theater.isHidden()

    def set_theater(self, on: bool) -> None:
        """Show the video slot and episode list in place of the big header (or put the header back)."""
        if on == self.theater_on:
            if on:
                self.refresh_theater()
            return
        self.theater.setVisible(on)
        self.header.setVisible(not on)
        self.episodes_box.setVisible(not on)       # the list beside the video has them
        if on:
            self.refresh_theater()
            self.verticalScrollBar().setValue(0)
        self._update_sticky()

    def refresh_theater(self) -> None:
        if not self.theater_on:
            return
        t = self.theater
        playing = self.playback.now_playing
        current = playing[1] if playing and playing[0] == self.anime_id else None
        progress = self.ctx.store.show_progress(self.anime_id) if self.anime_id else {}
        xmas = holiday.christmas_episodes_for(self.media.anilist_id if self.media else None)
        fillers = self.fillers
        items = []
        for ep in self.episodes:
            p = progress.get(ep.number)
            named = has_title(EpisodeItem(number=ep.number, title=ep.title))
            info = self.ep_details.get(ep.number) or {}
            shield = self._shielded(ep.number, p, current)
            items.append({"number": ep.number, "title": ep.title if (named and not shield) else "",
                          "still": self.stills.get(ep.number), "shield": shield,
                          "watched": bool(p and p.completed), "playing": ep.number == current,
                          "christmas": ep.number in xmas, "kind": fillers.kind(ep.number) if fillers else None,
                          "date": nice_date(info.get("date"))})
        t.rail.filler_prefs = {"hide_fillers": bool(self.ctx.pref("hide_fillers")),
                               "skip_fillers": bool(self.ctx.pref("skip_fillers"))}
        season = self.series.find(self.media.anilist_id) if (self.series and self.media) else None
        t.set_episodes(items, season.label if season else "Episodes", has_fillers=bool(fillers and fillers.kinds))

        # the episode
        ep = next((e for e in self.episodes if e.number == current), None)
        info = self.ep_details.get(current or "") or {}
        named = ep is not None and has_title(EpisodeItem(number=ep.number, title=ep.title))
        t.ep_title.setText(ep.title if named else (f"Episode {current}" if current else ""))
        bits = [f"Episode {current}"] if current else []
        if info.get("date"):
            bits.append(nice_date(info["date"]))
        if info.get("minutes"):
            bits.append(f"{info['minutes']} min")
        t.ep_meta.setText("  ·  ".join(bits))
        t.set_choices(bool(self.ctx.pref("dub", False)), str(self.ctx.pref("quality", "best")))
        door = None
        if theme.HOLIDAY and self.media and current:
            door = next((d for d in range(1, 25) if (pick := holiday.advent_pick(d))
                         and pick.anilist_id == self.media.anilist_id and pick.episode == current), None)
        t.door_chip.setText(f"🎁 Door {door} · Advent" if door else "")
        t.door_chip.setVisible(bool(door))
        day = None
        if theme.HOLIDAY:
            import datetime as _dt
            today = _dt.date.today()
            start, end = holiday.challenge_window(holiday.season_year(today))
            if start <= today <= end:
                day = (today - start).days + 1
        t.day_chip.setText(f"Day {day} of 12 ⭐" if day else "")
        t.day_chip.setVisible(bool(day))

        # the show
        m = self.media
        t.show_title.setText(m.display_title if m else self.title.text())
        t.show_meta.setText(media_meta(m) if m else "")
        t.poster.set_cover(self.poster.url, self.poster.color, self.title.text())
        summary = info.get("synopsis") or (m.description if m else "")
        if summary != t._summary_full:
            t.set_summary(summary)
        show = self.ctx.store.get_show(self.anime_id) if self.anime_id else None
        t.list_btn.setText("✓  Saved" if show and show.in_library else "+  Save")
        on = theme.HOLIDAY
        t.set_decor(on and bool(self.ctx.pref("player_lights", True)), on and bool(self.ctx.pref("player_snow", True)))
        self._load_details()

    def _load_details(self) -> None:
        """Air dates and summaries for the list and the card (Kitsu; once per show)."""
        stills = getattr(self.ctx, "stills", None)
        m = self.media
        if stills is None or m is None or not m.mal_id or not self.episodes or self._details_for == m.anilist_id:
            return
        self._details_for = m.anilist_id
        gen = self.gen
        numbers = [e.number for e in self.episodes][:120]
        self.ctx.runner.submit(stills.details, m.mal_id, numbers,
                               on_done=lambda found: gen == self.gen and self._got_details(found),
                               on_error=lambda _m: None, group="detail-ep-details")

    def _got_details(self, found: dict) -> None:
        self.ep_details = dict(found or {})
        self.refresh_theater()

    def _theater_dub(self, dub: bool) -> None:
        self.ctx.set_pref("dub", dub)
        (self.dub_btn if dub else self.sub_btn).setChecked(True)
        self._replay_current()

    def _theater_quality(self, quality: str) -> None:
        self.ctx.set_pref("quality", quality)
        self.quality.setCurrentIndex(max(0, self.quality.findData(quality)))
        self._replay_current()

    def _replay_current(self) -> None:
        """Sub/Dub or quality changed mid-episode: load it again, where you were."""
        playing = self.playback.now_playing
        if playing and playing[0] == self.anime_id:
            if self.playback.session is not None:
                self.playback.session.save()
            self.play(playing[1])

    def _open_outside(self, kind: str) -> None:
        playing = self.playback.now_playing
        if not playing or playing[0] != self.anime_id or not self.anime_id:
            return
        self.playback.play(self.anime_id, self.show_title, playing[1], player=kind)

    def refresh_if_showing(self) -> None:
        self._refresh_episode_states()
        self._refresh_library_button()
