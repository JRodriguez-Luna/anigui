"""Show details: backdrop header, actions, sub/dub + quality, and the episode grid."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QHBoxLayout, QLabel, QListView, QMenu, QPushButton, QScrollArea,
    QSizePolicy, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from core.anilist import Media
from core.hianime import Episode
from core.store import episode_key

from . import theme
from .cards import CardRow, media_card
from .context import AppContext
from .hero import Backdrop, airing_note, media_meta, truncate
from .playback import PlaybackController
from .widgets import PosterWidget

QUALITIES = [("Best", "best"), ("1080p", "1080"), ("720p", "720"), ("480p", "480")]
EP_ROLE = Qt.ItemDataRole.UserRole + 2


@dataclass(frozen=True)
class EpisodeItem:
    number: str
    title: str | None
    state: str = "new"        # new | progress | watched
    fraction: float = 0.0
    busy: str | None = None   # status text while resolving
    up_next: bool = False
    playing: bool = False


class EpisodeModel(QAbstractListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.items: list[EpisodeItem] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        if role == EP_ROLE:
            return item
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"Episode {item.number}" + (f": {item.title}" if item.title else "")
        return None

    def set_items(self, items: list[EpisodeItem]) -> None:
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def update_progress(self, number: str, state: str, fraction: float, playing: bool | None = None) -> None:
        for row, item in enumerate(self.items):
            if item.number == number:
                changes = {"state": state, "fraction": fraction}
                if playing is not None:
                    changes["playing"] = playing
                self.items[row] = replace(item, **changes)
                self.dataChanged.emit(self.index(row), self.index(row))
                return

    def set_busy(self, number: str | None, text: str | None = None) -> None:
        for row, item in enumerate(self.items):
            busy = text if item.number == number else None
            if item.busy != busy:
                self.items[row] = replace(item, busy=busy)
                self.dataChanged.emit(self.index(row), self.index(row))


class EpisodeDelegate(QStyledItemDelegate):
    W, H = 150, 78

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.small = theme.font(10, QFont.Weight.Bold)
        self.number = theme.font(22, QFont.Weight.Black)
        self.title = theme.font(12)

    def sizeHint(self, option, index) -> QSize:
        return QSize(self.W, self.H)

    def paint(self, p: QPainter, option, index) -> None:
        item: EpisodeItem = index.data(EP_ROLE)
        r = QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        watched = item.state == "watched"
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        lit = hover or item.busy or item.playing
        p.setPen(QPen(QColor(theme.ACCENT) if lit else QColor(theme.BORDER), 1.5 if lit else 1))
        p.setBrush(QColor(theme.SURFACE_2 if hover else theme.SURFACE))
        p.drawRoundedRect(r, 8, 8)

        inner = r.adjusted(12, 8, -12, -8)
        p.setFont(self.small)
        label = "▶ NOW PLAYING" if item.playing else ("UP NEXT" if item.up_next else "EPISODE")
        p.setPen(QColor(theme.ACCENT if (item.up_next or item.playing) else theme.FAINT))
        p.drawText(QRectF(inner.left(), inner.top(), inner.width(), 14), Qt.AlignmentFlag.AlignLeft, label)
        if watched and not item.playing:
            p.setPen(QColor(theme.GOOD))
            p.drawText(QRectF(inner.left(), inner.top(), inner.width(), 14), Qt.AlignmentFlag.AlignRight, "✓ WATCHED")

        p.setFont(self.number)
        p.setPen(QColor(theme.FAINT if watched else theme.TEXT))
        p.drawText(QRectF(inner.left(), inner.top() + 13, inner.width(), 28),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, item.number)

        p.setFont(self.title)
        p.setPen(QColor(theme.ACCENT if item.busy else theme.MUTED))
        text = item.busy or item.title or ""
        if text and text.strip().lower() != f"episode {item.number}".lower():
            text = p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(inner.width()))
            p.drawText(QRectF(inner.left(), inner.bottom() - 16, inner.width(), 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

        if item.state == "progress":
            bar = QRectF(r.left() + 1, r.bottom() - 4, r.width() - 2, 3)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawRect(bar)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRect(QRectF(bar.left(), bar.top(), bar.width() * max(0.05, item.fraction), 3))
        p.restore()


class EpisodeGrid(QListView):
    """Wrapping grid that grows to fit its content, so the whole page scrolls as one."""

    episodeClicked = Signal(str)
    markRequested = Signal(str, str)  # episode, "watched" | "unwatched" | "upto"
    SPACING = 5

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model_ = EpisodeModel(self)
        self.setModel(self.model_)
        self.setItemDelegate(EpisodeDelegate(self))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(self.SPACING)
        self.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda idx: self.episodeClicked.emit(idx.data(EP_ROLE).number))
        self.model_.modelReset.connect(self._fit)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos) -> None:
        index = self.indexAt(pos)
        if not index.isValid():
            return
        item: EpisodeItem = index.data(EP_ROLE)
        menu = QMenu(self)
        if item.state == "watched":
            menu.addAction("Mark as unwatched", lambda: self.markRequested.emit(item.number, "unwatched"))
        else:
            menu.addAction("Mark as watched", lambda: self.markRequested.emit(item.number, "watched"))
        menu.addAction(f"Mark episodes 1–{item.number} as watched", lambda: self.markRequested.emit(item.number, "upto"))
        menu.exec(self.viewport().mapToGlobal(pos))

    def wheelEvent(self, event) -> None:
        event.ignore()  # the page scrolls, not the grid

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        cell_w = EpisodeDelegate.W + 2 * self.SPACING
        cell_h = EpisodeDelegate.H + 2 * self.SPACING
        per_row = max(1, self.viewport().width() // cell_w)
        rows = math.ceil(len(self.model_.items) / per_row) if self.model_.items else 0
        self.setFixedHeight(rows * cell_h + 4)


class DetailPage(QScrollArea):
    backRequested = Signal()
    openItem = Signal(object)  # Media from the Related / You might also like rows
    libraryChanged = Signal()
    toast = Signal(str, bool)  # message, is_error

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
        self.autoplay = False
        self._related_for: int | None = None
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
        self.synopsis = QLabel("", objectName="Synopsis", wordWrap=True)
        self.synopsis.setMaximumWidth(720)
        self.synopsis.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.play_btn = QPushButton("▶  Play", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        self.play_btn.clicked.connect(lambda: self.play_target and self.play(self.play_target))
        self.list_btn = QPushButton("+  My List", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.list_btn.clicked.connect(self._toggle_library)
        self.sub_btn = QPushButton("Sub", objectName="Toggle", checkable=True, cursor=Qt.CursorShape.PointingHandCursor)
        self.dub_btn = QPushButton("Dub", objectName="Toggle", checkable=True, cursor=Qt.CursorShape.PointingHandCursor)
        self.mode = QButtonGroup(self)
        self.mode.addButton(self.sub_btn)
        self.mode.addButton(self.dub_btn)
        (self.dub_btn if ctx.pref("dub", False) else self.sub_btn).setChecked(True)
        self.dub_btn.toggled.connect(lambda on: ctx.set_pref("dub", on))
        self.quality = QComboBox(cursor=Qt.CursorShape.PointingHandCursor)
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
        actions.addWidget(self.list_btn)
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
        info.addWidget(self.meta)
        info.addWidget(self.airing)
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
        self.grid = EpisodeGrid()
        self.grid.episodeClicked.connect(self.play)
        self.grid.markRequested.connect(self._mark)
        self.message = QLabel("", objectName="EmptyState", wordWrap=True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.message.setContentsMargins(5, 0, 5, 0)

        episodes = QVBoxLayout()
        episodes.setContentsMargins(39, 10, 39, 40)
        episodes.setSpacing(12)
        episodes.addLayout(ep_head)
        episodes.addWidget(self.message)
        episodes.addWidget(self.grid)

        # More like this (AniList)
        self.related_row = CardRow("Related", ctx.images)
        self.recs_row = CardRow("You might also like", ctx.images)
        for row in (self.related_row, self.recs_row):
            row.setContentsMargins(5, 0, 5, 0)
            row.cardActivated.connect(lambda card: self.openItem.emit(card.payload))
            row.setVisible(False)
            episodes.addSpacing(22)
            episodes.addWidget(row)
        episodes.addStretch(1)

        body = QWidget(objectName="PageBody")
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self.header)
        col.addLayout(episodes, 1)
        self.setWidget(body)

        playback.busy.connect(self._on_busy)
        playback.started.connect(self._on_started)
        playback.failed.connect(self._on_failed)
        playback.progressSaved.connect(self._on_progress)
        playback.episodeChanged.connect(lambda aid, _ep: aid == self.anime_id and self._refresh_episode_states())
        playback.sessionEnded.connect(lambda: self._refresh_episode_states())

    # -- opening ------------------------------------------------------------------------

    def open_media(self, media: Media, autoplay: bool = False) -> None:
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

    def open_show(self, anime_id: str, title: str, poster: str | None = None, autoplay: bool = False) -> None:
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

    def _reset(self, autoplay: bool) -> None:
        self.gen += 1
        self.anime_id, self.media, self.episodes, self.play_target = None, None, [], None
        self.autoplay = autoplay
        for w in (self.kicker, self.meta, self.airing, self.synopsis, self.message, self.ep_count):
            w.setText("")
        self.airing.setVisible(False)
        self.message.setVisible(False)
        self.grid.model_.set_items([])
        self._related_for = None
        for row in (self.related_row, self.recs_row):
            row.set_cards([])
        self.play_btn.setEnabled(False)
        self.play_btn.setText("▶  Play")
        self.list_btn.setEnabled(False)
        self.verticalScrollBar().setValue(0)

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
        self._load_related(media)

    def _load_related(self, media: Media) -> None:
        if getattr(self, "_related_for", None) == media.anilist_id:
            return
        self._related_for = media.anilist_id
        gen = self.gen
        self.ctx.runner.submit(self.ctx.catalog.anilist.related, media.anilist_id,
                               on_done=lambda result: gen == self.gen and self._show_related(*result),
                               group="detail-related")

    def _show_related(self, related, recs) -> None:
        cards = []
        for r in related:
            card = media_card(r.media)
            cards.append(replace(card, badge=r.label.upper()))
        self.related_row.set_cards(cards)
        self.recs_row.set_cards([media_card(m) for m in recs])

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
        self.ep_count.setText(str(len(episodes)))
        self._refresh_episode_states()
        if self.autoplay and self.play_target:
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
        target, kind = self.ctx.catalog.resume_episode(self.anime_id, self.episodes)
        self.play_target = target.number if target else None
        busy = self.playback.active
        playing = self.playback.now_playing
        items = []
        for ep in self.episodes:
            p = progress.get(ep.number)
            state = "watched" if p and p.completed else ("progress" if p else "new")
            items.append(EpisodeItem(
                number=ep.number, title=ep.title, state=state, fraction=p.fraction if p else 0.0,
                up_next=bool(target and kind in ("next", "resume") and ep.number == target.number),
                busy=None,
                playing=bool(playing and playing == (self.anime_id, ep.number)),
            ))
        self.grid.model_.set_items(items)
        if busy and busy[0] == self.anime_id:
            self.grid.model_.set_busy(busy[1], "Starting…")
        labels = {"play": "▶  Play Episode {}", "resume": "▶  Resume Episode {}",
                  "next": "▶  Play Episode {}", "rewatch": "↺  Watch Again"}
        text = labels[kind].format(target.number if target else "")
        resume_at = self.playback.resume_position(self.anime_id, target.number) if target and kind == "resume" else None
        if resume_at:
            mins, secs = divmod(int(resume_at), 60)
            text += f"  ·  {mins}:{secs:02d}"
        self.play_btn.setText(text)
        self.play_btn.setEnabled(target is not None)

    def _refresh_library_button(self) -> None:
        show = self.ctx.store.get_show(self.anime_id) if self.anime_id else None
        saved = bool(show and show.in_library)
        self.list_btn.setText("✓  In My List" if saved else "+  My List")

    def _toggle_library(self) -> None:
        if not self.anime_id:
            return
        show = self.ctx.store.get_show(self.anime_id)
        self.ctx.store.set_in_library(self.anime_id, not (show and show.in_library))
        self._refresh_library_button()
        self.libraryChanged.emit()

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

    def _mark(self, episode: str, action: str) -> None:
        if not self.anime_id:
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
        """Keep the Sub/Dub and quality controls in step with Settings."""
        if key == "dub":
            btn = self.dub_btn if self.ctx.pref("dub") else self.sub_btn
            if not btn.isChecked():
                btn.setChecked(True)
        elif key == "quality":
            i = max(0, self.quality.findData(str(self.ctx.pref("quality"))))
            if i != self.quality.currentIndex():
                self.quality.setCurrentIndex(i)

    def refresh_if_showing(self) -> None:
        self._refresh_episode_states()
        self._refresh_library_button()
