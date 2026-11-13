"""Window shell: sidebar navigation, page stack with Back history, toasts, startup checks."""

from __future__ import annotations

import datetime as dt
import html

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMessageBox, QButtonGroup, QHBoxLayout, QInputDialog, QLabel, QMenu, QMainWindow, QPushButton, QScrollArea, QStackedWidget,
    QVBoxLayout, QWidget,
)

from core import holiday
from core.anilist import Media
from core import __version__
from core.setup import parse_version
from core import self_update, setup, updates
from core.player import Player
from core.store import SAVED
from core import wrapped

from .alerts import AlertsController, describe
from .mature import confirm_open, flags_for, status_known
from .context import AppContext
from .detail_page import DetailPage
from .home_page import HomePage
from .icons import nav_icon
from . import theme
from .cinema import Ambient
from .fps import FrameMeter
from .wrapped_page import WrappedPage, wrapped_year
from .your_data import DataTools
from .yours import tinted_icon
from .lock import Gate, LockScreen
from .privacy_page import PrivacyPage
from .library import LibraryNav, ask_new_list
from .festive import ChristmasCard, CountdownChip, Fireworks, Flurry, SidebarLights, first_name, greeting_lines
from .motion import reduce_motion, reset_quiet, set_quiet
from .holiday import Brand, holiday_icon
from .holidays_page import HolidaysPage
from .holiday import is_on as holiday_on
from .motion import crossfade
from .library_page import LibraryPage
from .playback import PlaybackController
from .downloads import DownloadManager
from .now_playing import NowPlayingBridge
from .player_view import PlayerHost, available as player_available
from .search_page import SearchPage
from .settings_dialog import SettingsDialog
from .calendar_page import CalendarPage
from .stats_page import StatsPage
from .update_dialog import UpdateDialog
from .setup_dialog import SetupDialog
from .whats_new import WhatsNewDialog
from .widgets import Toast



class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("AniGUI")
        self.resize(1320, 860)
        self.setMinimumSize(980, 640)

        self.playback = PlaybackController(ctx, self)
        ctx.downloads = DownloadManager(ctx, self.playback.resolver, self)      # Downloads (2.0)
        self.alerts = AlertsController(ctx, self)
        self.home = HomePage(ctx)
        self.search = SearchPage(ctx)
        self.library = LibraryPage(ctx)
        self.stats = StatsPage(ctx)
        self.calendar = CalendarPage(ctx)
        self.detail = DetailPage(ctx, self.playback)

        self.stack = QStackedWidget()
        self.holidays = HolidaysPage(ctx)          # in the sidebar while the holiday theme is on
        self.privacy_page = PrivacyPage(ctx)       # What leaves your Mac (2.0)
        self.privacy_page.backRequested.connect(self.back)
        self.wrapped_page = WrappedPage(ctx.images)   # Wrapped (2.0)
        self.wrapped_page.backRequested.connect(self.back)
        for page in (self.home, self.search, self.library, self.calendar, self.stats, self.detail, self.holidays,
                     self.privacy_page, self.wrapped_page):
            self.stack.addWidget(page)
        self.history: list[QWidget] = []
        self.show_history: list = []   # earlier shows when one show page leads to another

        # Sidebar
        sidebar = QWidget(objectName="Sidebar")
        sidebar.setFixedWidth(208)
        self.nav = QButtonGroup(self)
        self.nav_buttons: dict[QWidget, QPushButton] = {}
        self.nav_keys: list[tuple[str, QWidget, str]] = []   # for the Go menu
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 26, 14, 16)
        side.setSpacing(4)
        self.brand = Brand()
        side.addWidget(self.brand)
        self.private_pill = QPushButton("🕶  Private mode", objectName="PrivatePill",
                                        cursor=Qt.CursorShape.PointingHandCursor)
        self.private_pill.setToolTip("Private mode is on: what you watch isn't added to your history, Continue "
                                     "Watching or timeline. Click to turn it off.")
        self.private_pill.clicked.connect(lambda: self.set_private(False))
        self.private_pill.hide()
        side.addWidget(self.private_pill)
        side.addSpacing(4)
        for label, icon, page, keys in (("Home", "home", self.home, "Ctrl+1"), ("Search", "search", self.search, "Ctrl+2"),
                                        ("Library", "heart", self.library, "Ctrl+3"),
                                        ("Holidays", "tree", self.holidays, "Ctrl+6"),
                                        ("Stats", "stats", self.stats, "Ctrl+4"),
                                        ("Calendar", "calendar", self.calendar, "Ctrl+5")):
            if page is self.library:
                # My Library (2.0): your lists nest under it
                self.libnav = LibraryNav(self.nav)
                self.libnav.set_open(bool(ctx.pref("sidebar_lists_open", True)))
                self.libnav.folded.connect(lambda on: ctx.set_pref("sidebar_lists_open", on))
                self.libnav.openOverview.connect(lambda: self.open_library(None))
                self.libnav.openList.connect(self.open_library)
                self.libnav.newList.connect(self._new_list)
                self.libnav.listMenu.connect(self._list_menu)
                self.libnav.header.setToolTip(QKeySequence(keys).toString(QKeySequence.SequenceFormat.NativeText))
                self.nav_keys.append((label, page, keys))
                self.nav_buttons[page] = self.libnav.header
                side.addWidget(self.libnav)
                continue
            btn = QPushButton(f"  {label}", objectName="NavButton", checkable=True,
                              cursor=Qt.CursorShape.PointingHandCursor)
            btn.setIcon(nav_icon(icon))
            btn.setIconSize(QSize(18, 18))
            # toggled covers VoiceOver and other accessibility presses, which check the
            # button without clicking it; clicked covers clicking the already-checked one
            # (e.g. Home while a show page is open). go() ignores the second call.
            btn.toggled.connect(lambda on, p=page: on and self.go(p))
            btn.clicked.connect(lambda _c=False, p=page: self.go(p))
            btn.setToolTip(QKeySequence(keys).toString(QKeySequence.SequenceFormat.NativeText))
            self.nav_keys.append((label, page, keys))
            self.nav.addButton(btn)
            self.nav_buttons[page] = btn
            side.addWidget(btn)
        side.addStretch(1)
        self.countdown = CountdownChip()
        side.addWidget(self.countdown)
        side.addSpacing(6)
        self.lights = SidebarLights(sidebar)
        self.settings_btn = QPushButton("  Settings", objectName="NavButton", cursor=Qt.CursorShape.PointingHandCursor)
        self.settings_btn.setIcon(nav_icon("settings"))
        self.settings_btn.setIconSize(QSize(18, 18))
        self.settings_btn.setToolTip(QKeySequence(QKeySequence.StandardKey.Preferences).toString(
            QKeySequence.SequenceFormat.NativeText) or "Settings")
        self.settings_btn.clicked.connect(lambda: self.open_settings())
        side.addWidget(self.settings_btn)
        side.addSpacing(10)
        self.footer = QLabel("", objectName="SidebarFooter", wordWrap=True)
        side.addWidget(self.footer)

        self.banner = QLabel("", objectName="Banner", wordWrap=True)
        self.banner.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.banner.linkActivated.connect(self._banner_link)
        self.banner.hide()
        content = QWidget()
        content_col = QVBoxLayout(content)
        content_col.setContentsMargins(0, 0, 0, 0)
        content_col.setSpacing(0)
        content_col.addWidget(self.banner)
        content_col.addWidget(self.stack, 1)

        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(sidebar)
        row.addWidget(content, 1)
        self.setCentralWidget(central)
        # 2.0 Cinema: one backdrop behind everything, so artwork runs under the glass sidebar
        self.ambient = Ambient(ctx.images, central, sidebar.width())
        self.toast = Toast(central)
        self.flurry = Flurry(central)
        self.fireworks = Fireworks(central)
        # The built-in player floats above the pages (on the show page, in the corner, or full screen)
        self.player_host = PlayerHost(ctx, central)
        self.now_playing = NowPlayingBridge(ctx, self.playback, self.player_host, self)
        # Decorations hold still while you're in another app (2.0.1)
        reset_quiet()
        app = QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._app_state)
        self.player_host.slot = self._player_slot
        self.player_host.slot_widget = lambda: self.detail.theater.slot
        self.player_host.closed.connect(self._sync_theater)
        self.player_host.expandRequested.connect(self._expand_player)
        self.player_host.backRequested.connect(self._player_back)
        self.player_host.modeChanged.connect(lambda m: self.detail.theater.slot.set_popped(m == "pop"))
        self.player_host.closed.connect(lambda: self.detail.theater.slot.set_popped(False))
        self.detail.theater.slot.bringBack.connect(lambda: self.player_host.pop_in())
        self.player_host.set_drawer_content(self.detail.theater.rail)
        self.detail.theater.all_btn.clicked.connect(lambda: self.player_host.toggle_drawer())
        # Rewatch mode: auto-play moving on moves your rewatch place too
        self.playback.episodeChanged.connect(
            lambda aid, ep: self.ctx.store.rewatch(aid) and self.ctx.store.advance_rewatch(aid, ep))
        self.player_host.drawerChanged.connect(
            lambda on: self.detail.theater.all_btn.setText("✕  Hide episodes" if on else "☰  All episodes"))
        ctx.player.embed = self.player_host.start
        if isinstance(ctx.player, Player):
            ctx.player.embed_available = player_available     # (tests bring their own player)
        self.detail.bound.connect(lambda _aid: self._sync_theater())
        self.detail.theater.slot.moved.connect(self.player_host.place)
        self.detail.verticalScrollBar().valueChanged.connect(lambda _v: self.player_host.place())
        self.stack.currentChanged.connect(lambda _i: self._sync_theater())
        self._update_ambient()
        self.christmas_card = ChristmasCard(central)
        self.fireworks.raise_()
        self.countdown.clicked.connect(self.flurry.play)
        self._midnight = QTimer(self, singleShot=True)       # New Year's Eve, while the app is open
        self.now = dt.datetime.now                            # (tests pin the clock)
        self._midnight.timeout.connect(self._new_year)
        for w in (self.nav_buttons[self.holidays], self.countdown):
            w.setVisible(False)

        # Wiring
        for page in (self.home, self.search, self.library, self.calendar, self.stats, self.holidays):
            page.openItem.connect(self.open_item)
        self.holidays.playEpisode.connect(lambda media, episode: self.open_item(media, autoplay=episode))
        self.home.surprise.connect(lambda item, episode: self.open_item(item, autoplay=episode or True))
        self.calendar.libraryChanged.connect(self._local_changed)
        self.library.listsChanged.connect(self._lists_changed)
        self.library.listMenu.connect(self._list_menu)
        self.library.openMoment.connect(self.play_moment)
        self.library.playDownload.connect(self.play_download)
        dl = ctx.downloads
        dl.changed.connect(self._downloads_changed)
        dl.finished.connect(self._download_done)
        dl.failed.connect(lambda _aid, ep, msg: self.toast.show_message(f"Couldn't download episode {ep}: {msg}",
                                                                        error=True))
        self.playback.progressSaved.connect(lambda _a, _e: self._check_goal())
        self.player_host.momentSaved.connect(lambda: self.stack.currentWidget() is self.library and self.library.refresh())
        self.stats.wrappedRequested.connect(lambda: self.open_wrapped())
        self._lists_changed()
        self.calendar.toast.connect(lambda text, err: self.toast.show_message(text, error=err))
        self.home.playItem.connect(lambda media: self.open_item(media, autoplay=True))
        self.home.historyChanged.connect(self.detail.refresh_if_showing)
        self.search.setupRequested.connect(self.open_setup)
        self.detail.backRequested.connect(self.back)
        self.detail.openItem.connect(self.open_item)
        self.detail.openNext.connect(lambda media: self.open_item(media, autoplay=True))
        self.detail.libraryChanged.connect(self._local_changed)
        self.detail.toast.connect(lambda text, err: self.toast.show_message(text, error=err))
        self.playback.started.connect(lambda *_: self._local_changed())
        self.playback.started.connect(self._on_play_started)
        self.playback.episodeChanged.connect(lambda *_: self._sync_theater())
        self.playback.sessionEnded.connect(self._local_changed)
        self.playback.episodeChanged.connect(lambda *_: self._local_changed())
        self.playback.notice.connect(lambda text, err: self.toast.show_message(text, error=err))

        QShortcut(QKeySequence.StandardKey.Find, self, activated=lambda: (self.go(self.search), self.search.focus_search()))
        QShortcut(QKeySequence("Esc"), self, activated=self._escape)
        # Your data (2.0)
        self.data = DataTools(ctx, self)
        self.data.changed.connect(self._data_changed)
        self.data.message.connect(lambda text, error: self.toast.show_message(text, error))
        QTimer.singleShot(4000, self.data.auto_backup)
        # Touch ID locks (2.0)
        self.gate = Gate(parent=self)
        self.lock_screen = LockScreen(self.centralWidget())
        self.lock_screen.unlockRequested.connect(self.unlock_app)
        self.library.hidden = self._hidden_ids
        if ctx.pref("lock_app"):
            self.lock_screen.cover()
            QTimer.singleShot(500, self.unlock_app)
        # ⌘⌥F: a frame-rate readout, for checking smoothness on a real Mac
        self.frame_meter = FrameMeter(self.centralWidget())
        QShortcut(QKeySequence("Ctrl+Alt+F"), self, activated=self.frame_meter.toggle)

        self.alerts.changed.connect(self.home.refresh_local)
        self.alerts.found.connect(self._on_new_episodes)
        self.alerts.notifier.clicked.connect(self._show_from_notification)
        ctx.events.changed.connect(self._pref_changed)
        self.mature_ask = None   # tests answer the "Show anyway?" window with this
        self._base_icon = None
        self._footer_ani_cli: str | None = None
        if ctx.pref("accent") != "ember" or ctx.pref("app_icon") != "classic":
            self.apply_yours()          # (Make it yours)
        self._holiday_timer = QTimer(self, interval=60 * 60 * 1000)   # the date can change while open
        self._holiday_timer.timeout.connect(lambda: self.apply_holiday())
        self.home.holidayAnswered.connect(self._holiday_answer)

        self.nav_buttons[self.home].setChecked(True)
        self._build_menus()
        self._settings: SettingsDialog | None = None
        self._ani_cli_version: str | None = None

    # -- navigation ---------------------------------------------------------------------

    def go(self, page: QWidget, remember: bool = True) -> None:
        current = self.stack.currentWidget()
        if page is current:
            return
        if page is not self.detail:
            self.show_history.clear()
        if remember:
            self.history.append(current)
            del self.history[:-30]
        crossfade(self.stack, slide_in=page)       # the old page fades out as the new one rises in
        self.stack.setCurrentWidget(page)
        if page in self.nav_buttons:
            btn = self.nav_buttons[page]
            btn.blockSignals(True)            # (its own toggled handler would navigate again)
            btn.setChecked(True)
            btn.blockSignals(False)
        if page is self.home:
            self.home.refresh_local()
        elif page is self.library:
            self.library.refresh()
        elif page is self.stats:
            self.stats.refresh()
        elif page is self.calendar:
            self.calendar.refresh()

    def back(self) -> None:
        if self.stack.currentWidget() is self.detail and self.show_history:
            self.detail.pending_mature_checked = True    # it was already allowed when opened
            self._reopen(self.show_history.pop())  # back to the show we came from
            return
        while self.history:
            page = self.history.pop()
            if page is not self.stack.currentWidget():
                self.go(page, remember=False)
                return
        self.go(self.home, remember=False)

    def open_item(self, item, autoplay: bool | str = False) -> None:
        if self.ctx.pref("lock_mature") and flags_for(self.ctx, item)[0] and not self.gate.is_open("mature"):
            self.gate.require("mature", "open 18+ shows", lambda: self._open_item_now(item, autoplay))
            return
        self._open_item_now(item, autoplay)

    def _open_item_now(self, item, autoplay: bool | str = False) -> None:
        if not confirm_open(self.ctx, item, self, ask=self.mature_ask):
            return
        self.detail.pending_mature_checked = status_known(self.ctx, item)
        if self.stack.currentWidget() is self.detail and self.detail.current_item is not None:
            self.show_history.append(self.detail.current_item)
            del self.show_history[:-30]
        self._reopen(item, autoplay)

    def _reopen(self, item, autoplay: bool | str = False) -> None:
        if self.stack.currentWidget() is self.detail:
            crossfade(self.stack, slide_in=self.detail)   # one show page to another
        if isinstance(item, tuple):  # (anime_id, title, poster) saved by the show page
            self.detail.open_show(*item, autoplay=autoplay)
        elif isinstance(item, Media):
            self.detail.open_media(item, autoplay=autoplay)
        else:  # Show or SearchResult: both carry anime_id, title, poster
            self.detail.open_show(item.anime_id, item.title, item.poster, autoplay=autoplay)
        self.go(self.detail)

    def _local_changed(self) -> None:
        self.home.refresh_local()
        self._lists_changed()

    # -- My Library (2.0) ---------------------------------------------------------------

    def open_library(self, list_id: int | None = None) -> None:
        sl = self.ctx.store.get_list(list_id) if list_id is not None else None
        if sl is not None and sl.locked and not self.gate.is_open(f"list:{list_id}"):
            self.gate.require(f"list:{list_id}", f"open your list “{sl.name}”",
                              lambda: self._open_library_now(list_id),
                              otherwise=lambda: self.libnav.select(self.library.list_id
                                                                   if self.stack.currentWidget() is self.library else None))
            return
        self._open_library_now(list_id)

    def _open_library_now(self, list_id: int | None = None) -> None:
        if list_id is None:
            self.library.show_overview()
        else:
            self.library.show_list(list_id)
        self.go(self.library)
        self.libnav.select(list_id)

    def _lists_changed(self) -> None:
        self.libnav.set_lists(self.ctx.store.lists())
        if self.stack.currentWidget() is self.library:
            self.library.refresh()
            self.libnav.select(self.library.list_id)

    def _new_list(self) -> None:
        lid = ask_new_list(self.ctx.store, self)
        if lid is not None:
            self._lists_changed()
            self.open_library(lid)

    def _list_menu(self, list_id: int, pos) -> None:
        store = self.ctx.store
        sl = store.get_list(list_id)
        if sl is None:
            return
        menu = QMenu(self)
        menu.addAction("Open").triggered.connect(lambda: self.open_library(list_id))
        if list_id != SAVED:
            ids = [x.list_id for x in store.lists() if x.list_id != SAVED]
            i = ids.index(list_id)
            menu.addAction("Rename…").triggered.connect(lambda: self._rename_list(list_id))
            up = menu.addAction("Move up")
            up.setEnabled(i > 0)
            up.triggered.connect(lambda: (store.move_list(list_id, i - 1), self._lists_changed()))
            down = menu.addAction("Move down")
            down.setEnabled(i < len(ids) - 1)
            down.triggered.connect(lambda: (store.move_list(list_id, i + 1), self._lists_changed()))
            menu.addSeparator()
            if sl.locked:
                menu.addAction("Remove Touch ID lock").triggered.connect(lambda: self._lock_list(list_id, False))
            else:
                lock = menu.addAction("Lock with Touch ID")
                lock.setEnabled(self.gate.available())
                lock.triggered.connect(lambda: self._lock_list(list_id, True))
            menu.addSeparator()
            menu.addAction("Delete list…").triggered.connect(lambda: self._delete_list(list_id))
        menu.exec(pos)

    def _lock_list(self, list_id: int, locked: bool) -> None:
        def apply():
            self.ctx.store.set_list_locked(list_id, locked)
            if locked:
                self.gate.unlocked.discard(f"list:{list_id}")
                if self.stack.currentWidget() is self.library and self.library.list_id == list_id:
                    self.open_library(None)
            self._lists_changed()
        if locked:
            apply()
        else:      # taking a lock off needs the lock
            sl = self.ctx.store.get_list(list_id)
            self.gate.require(f"list:{list_id}", f"unlock your list “{sl.name}”", apply)

    def _hidden_ids(self) -> set[str]:
        """Shows that are only in locked lists you haven't opened: kept out of All shows,
        Ratings, Tags and the timeline too."""
        store = self.ctx.store
        hidden, shown = set(), set()
        for sl in store.lists():
            ids = {s.anime_id for s in store.list_shows(sl.list_id)}
            if sl.locked and not self.gate.is_open(f"list:{sl.list_id}"):
                hidden |= ids
            else:
                shown |= ids
        return hidden - shown

    def _check_goal(self) -> None:
        """Weekly goal reached: say so, once a week."""
        from core import goals

        goal = int(self.ctx.pref("weekly_goal") or 0)
        week = goals.week_start().isoformat()
        if not goal or self.ctx.pref("goal_met_week", "") == week:
            return
        if goals.episodes_this_week(self.ctx.store) >= goal:
            self.ctx.set_pref("goal_met_week", week)
            self.toast.show_message(("🎄 " if theme.HOLIDAY else "🎉 ") + f"Weekly goal reached: {goal} episodes!")
            self.home.update_greeting()

    def play_moment(self, m) -> None:
        """Back to a saved frame: the show's page, playing from that second."""
        show = self.ctx.store.get_show(m.anime_id)
        if show is None:
            return
        self.open_item(show)
        self.playback.play(show.anime_id, show.title, m.episode, start=max(0.0, m.position - 2))

    def play_download(self, anime_id: str, title: str, episode: str) -> None:
        show = self.ctx.store.get_show(anime_id)
        if show is None:
            return
        self.open_item(show)
        self.playback.play(show.anime_id, show.title, episode)

    def _download_done(self, anime_id: str, episode: str) -> None:
        show = self.ctx.store.get_show(anime_id)
        name = f"{show.title}, episode {episode}" if show else f"Episode {episode}"
        self.toast.show_message(f"Downloaded {name}. It plays with no internet.", error=False)

    def _downloads_changed(self) -> None:
        self.detail.refresh_downloads()
        if self.stack.currentWidget() is self.library and self.library.list_id is None \
                and self.library.tab == "downloads":
            self.library.refresh_downloads()

    def open_wrapped(self, year: int | None = None) -> None:
        """Your year in anime (worked out in the background: genres may need AniList's cache)."""
        year = year or wrapped_year()
        anilist = self.ctx.catalog.anilist

        def media_for(anilist_id):
            return anilist.media(anilist_id)

        def show(w):
            self.wrapped_page.set_data(w, str(self.ctx.pref("your_name") or ""))
            self.go(self.wrapped_page)
            self.wrapped_page.setFocus()
        self.ctx.runner.submit(wrapped.compute, self.ctx.store, year, media_for, on_done=show,
                               on_error=lambda msg: self.toast.show_message(msg, True), group="wrapped")

    def _data_changed(self) -> None:
        """A restore or an import changed your data: show it everywhere."""
        self.home.refresh_local()
        self._lists_changed()
        self.detail.refresh_if_showing()
        if self.detail.anime_id:
            self.detail.yours.load(self.detail.anime_id, save=False)
        if self.stack.currentWidget() is self.stats:
            self.stats.refresh()

    # -- privacy (2.0) ------------------------------------------------------------------

    def set_private(self, on: bool) -> None:
        on = bool(on)
        if self.ctx.store.private == on:
            return
        self.ctx.store.private = on
        self.private_action.blockSignals(True)
        self.private_action.setChecked(on)
        self.private_action.blockSignals(False)
        self.private_pill.setText(("❄  " if theme.HOLIDAY else "🕶  ") + "Private mode")
        self.private_pill.setVisible(on)
        self.setWindowTitle("AniGUI · Private" if on else "AniGUI")
        self.toast.show_message("Private mode: what you watch isn't saved until you turn it off or quit."
                                if on else "Private mode is off.")

    def unlock_app(self) -> None:
        self.gate.require("app", "open AniGUI", self.lock_screen.hide)

    def lock_now(self) -> None:
        self.gate.lock_all()
        if self.stack.currentWidget() is self.library and self.library.list_id is not None:
            sl = self.ctx.store.get_list(self.library.list_id)
            if sl and sl.locked:
                self.open_library(None)
        elif self.stack.currentWidget() is self.library:
            self.library.refresh()
        if self.ctx.pref("lock_app") and self.gate.available():
            if self.player_host.active:
                self.player_host.close_player()
            self.lock_screen.cover()

    def _rename_list(self, list_id: int) -> None:
        sl = self.ctx.store.get_list(list_id)
        text = f"{sl.emoji} {sl.name}" if sl.emoji else sl.name
        name, ok = QInputDialog.getText(self, "Rename list", "Name (start with an emoji if you like):", text=text)
        if ok and name.strip():
            parts = name.strip().split(" ", 1)
            emoji = None
            if len(parts) == 2 and parts[0] and not parts[0][0].isalnum() and len(parts[0]) <= 3:
                emoji, name = parts[0], parts[1]
            self.ctx.store.rename_list(list_id, name, emoji)
            self._lists_changed()

    def _delete_list(self, list_id: int) -> None:
        sl = self.ctx.store.get_list(list_id)
        box = QMessageBox(QMessageBox.Icon.Question, "Delete list",
                          f"Delete “{sl.name}”?", parent=self)
        box.setInformativeText("Only the list goes. The shows, what you watched, your ratings and notes all stay.")
        box.addButton("Delete list", QMessageBox.ButtonRole.DestructiveRole)
        keep = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep)
        box.exec()
        if box.clickedButton() is not keep:
            self.ctx.store.delete_list(list_id)
            if self.library.list_id == list_id:
                self.open_library(None)
            self._lists_changed()

    # -- menus and settings -------------------------------------------------------------

    def _build_menus(self) -> None:
        """macOS moves Settings, What's New and Check for Updates into the AniGUI menu."""
        bar = self.menuBar()
        app_menu = bar.addMenu("AniGUI")
        whats_new = QAction("What's New", self, menuRole=QAction.MenuRole.ApplicationSpecificRole)
        whats_new.triggered.connect(lambda: self.show_whats_new())
        updates_action = QAction("Check for Updates…", self, menuRole=QAction.MenuRole.ApplicationSpecificRole)
        updates_action.triggered.connect(self.check_updates_now)
        settings = QAction("Settings…", self, menuRole=QAction.MenuRole.PreferencesRole,
                           shortcut=QKeySequence(QKeySequence.StandardKey.Preferences))
        if settings.shortcut().isEmpty():
            settings.setShortcut(QKeySequence("Ctrl+,"))
        settings.triggered.connect(lambda: self.open_settings())
        for action in (whats_new, updates_action, settings):
            app_menu.addAction(action)
        self.settings_action = settings

        go = bar.addMenu("Go")
        self.go_actions: dict[str, QAction] = {}
        for label, page, keys in self.nav_keys:
            action = QAction(label, self, shortcut=QKeySequence(keys))
            action.triggered.connect(lambda _c=False, p=page: self.go(p))
            go.addAction(action)
            self.go_actions[label] = action
        go.addSeparator()
        back = QAction("Back", self, shortcut=QKeySequence(QKeySequence.StandardKey.Back))
        if back.shortcut().isEmpty():
            back.setShortcut(QKeySequence("Ctrl+["))
        back.triggered.connect(self.back)
        go.addAction(back)
        self.go_actions["Back"] = back

        history = bar.addMenu("History")
        self.private_action = QAction("Private Mode", self, checkable=True, shortcut=QKeySequence("Ctrl+Shift+N"))
        self.private_action.toggled.connect(self.set_private)
        history.addAction(self.private_action)
        history.addSeparator()
        clear = history.addAction("Clear Watch History…")
        clear.triggered.connect(self.home.confirm_clear_history)

        privacy_menu = bar.addMenu("Privacy")
        lock_now = QAction("Lock Now", self, shortcut=QKeySequence("Ctrl+Alt+L"))
        lock_now.triggered.connect(self.lock_now)
        privacy_menu.addAction(lock_now)
        leaves = QAction("What Leaves Your Mac", self)
        leaves.triggered.connect(lambda: self.go(self.privacy_page))
        privacy_menu.addAction(leaves)

    def open_settings(self, section: str | None = None) -> SettingsDialog:
        self.ctx.lock_available = self.gate.available()
        if self._settings is None:
            dlg = SettingsDialog(self.ctx, self)
            dlg.clearHistoryRequested.connect(self.home.confirm_clear_history)
            dlg.setupRequested.connect(self.open_setup)
            dlg.checkUpdatesRequested.connect(self.check_updates_now)
            dlg.whatsNewRequested.connect(lambda: self.show_whats_new())
            dlg.checkEpisodesRequested.connect(lambda: self.alerts.check_now(manual=True))
            dlg.privacyPageRequested.connect(lambda: (dlg.close(), self.go(self.privacy_page)))
            dlg.backupRequested.connect(self.data.back_up_now)
            dlg.restoreRequested.connect(lambda: self.data.restore())
            dlg.backupsFolderRequested.connect(self.data.show_folder)
            dlg.importAniListRequested.connect(self.data.import_anilist)
            dlg.importMalRequested.connect(lambda: self.data.import_mal())
            self.alerts.status.connect(dlg.set_episodes_status)
            self._settings = dlg
        self._settings.set_versions(self._ani_cli_version)
        if section:
            self._settings.show_section(section)
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()
        return self._settings

    def show_whats_new(self, since: str | None = None) -> WhatsNewDialog:
        dialog = WhatsNewDialog(self, since)
        dialog.open()
        self._whats_new = dialog
        return dialog

    def _maybe_show_whats_new(self) -> WhatsNewDialog | None:
        """Once per new version. Fresh installs get Setup instead; the version is just recorded."""
        last = str(self.ctx.pref("last_version", "") or "")
        self.ctx.set_pref("last_version", __version__)
        if last == __version__:
            return None
        if not last and not self.ctx.pref("setup_done", False):
            return None  # first launch ever
        # No record but Setup was done: updated from 1.1.x, which didn't record versions
        since = last or "1.1.0"
        if parse_version(since) < (2, 0, 0) <= parse_version(__version__):
            return self.show_tour()            # the big one: a short tour instead of the list
        return self.show_whats_new(since)

    def show_tour(self):
        from .tour import TourDialog
        dialog = TourDialog(self.ctx, self, backup=self.ctx.store.upgrade_backup)
        dialog.openSettings.connect(lambda section: QTimer.singleShot(0, lambda: self.open_settings(section)))
        dialog.open()
        self._tour = dialog
        return dialog

    def apply_yours(self) -> None:
        """Your accent and app icon (Make it yours, 2.0)."""
        app = QApplication.instance()
        theme.set_accent(theme.accent_hex(str(self.ctx.pref("accent"))))
        theme.apply_theme(app)
        self._set_app_icon()
        self.brand.refresh()
        for w in app.allWidgets():
            QWidget.update(w)

    def _set_app_icon(self) -> None:
        app = QApplication.instance()
        if self._base_icon is None:
            self._base_icon = app.windowIcon()
        icon = self._base_icon
        if self.ctx.pref("app_icon") == "accent" and not icon.isNull():
            icon = tinted_icon(icon, theme.accent_hex(str(self.ctx.pref("accent"))))
        if theme.HOLIDAY:
            icon = holiday_icon(icon)
        app.setWindowIcon(icon)

    def _pref_changed(self, key: str, _value) -> None:
        if key in ("accent", "app_icon"):
            self.apply_yours()
        elif key == "not_interested_changed":
            self.home.apply_content_filter()
            self.detail.apply_content_filter()
        elif key == "spoiler_shield":
            self.detail.refresh_if_showing()
        elif key == "weekly_goal":
            self.home.update_greeting()
        elif key == "your_name":
            self.home.update_greeting()
        elif key in ("sub_size", "sub_color", "sub_box", "sharper"):
            self.playback.restyle()
        elif key == "home_rows":
            self.home.apply_rows()
        elif key == "alerts":
            self.home.refresh_local()
        elif key == "import_history":
            self._import_terminal_history()
        elif key == "maturity_found":          # saved shows just got their 18+ status
            self.home.refresh_local()
            self.library.refresh()
        elif key == "holiday_theme":
            self.apply_holiday()
        elif key == "hide_mature":
            self.home.apply_content_filter()
            self.search.apply_content_filter()
            self.library.refresh()
            if self.stack.currentWidget() is self.calendar:
                self.calendar.refresh()
            self.detail.apply_content_filter()

    # -- the built-in player -------------------------------------------------------------

    def _escape(self) -> None:
        host = self.player_host
        if host.active and host.drawer_open and host.drawer.isVisible():
            host.toggle_drawer(False)
        elif host.active and host.mode == "full":
            host.set_mode("theater", forced=True)
        elif host.active and host.controls.countdown:
            host._up_next(False)
        elif self.stack.currentWidget() is self.detail:
            self.back()

    def _on_play_started(self, anime_id: str, episode: str, kind: str) -> None:
        if kind == "anigui" and self.playback.session is not None:
            self.player_host.attach(self.playback.session)
            self.player_host.forced_mini = False
            self.player_host.setFocus()
        self._sync_theater()

    def _playing_show(self) -> str | None:
        host = self.player_host
        if host.active and host.session is not None and not host.session.closed:
            return host.session.now.anime_id
        return None

    def _sync_theater(self) -> None:
        playing = self._playing_show()
        self.detail.set_theater(playing is not None and self.detail.anime_id == playing)
        self.player_host.place()
        self._update_ambient()

    def _update_ambient(self) -> None:
        """What the window's backdrop shows: this page's artwork, or the show's glow while watching."""
        page = self.stack.currentWidget()
        body = page.widget() if isinstance(page, QScrollArea) else None
        self.ambient.set_page(body)
        if page is self.home:
            self.ambient.follow(self.home.hero, "band")
        elif page is self.detail:
            self.ambient.follow(self.detail.header, "glow" if self.detail.theater_on else "band")
        else:
            self.ambient.follow(None)

    def _player_slot(self):
        d = self.detail
        if self.stack.currentWidget() is not d or not d.theater_on or not self.player_host.active:
            return None
        central = self.centralWidget()
        slot = d.theater.slot
        rect = QRect(slot.mapTo(central, QPoint(0, 0)), slot.size())
        vp = d.viewport()
        visible = QRect(vp.mapTo(central, QPoint(0, 0)), vp.size())
        if d._bar_room:                                   # (the bar's strip counts as on screen)
            visible.setTop(visible.top() - d.sticky.height())
        return rect, visible

    def _player_back(self) -> None:
        """The player's Back: leave the show page (the episode keeps playing in the corner)."""
        if self.stack.currentWidget() is self.detail:
            self.back()

    def _expand_player(self) -> None:
        """The mini-player was clicked: back to the show it's playing."""
        aid = self._playing_show()
        if aid is None:
            return
        self.player_host.forced_mini = False
        if self.detail.anime_id == aid:
            self.go(self.detail)
        else:
            show = self.ctx.store.get_show(aid)
            if show is not None:
                self.open_item(show)
        self._sync_theater()

    # -- holiday theme --------------------------------------------------------------------

    def apply_holiday(self, today=None, animate: bool = True) -> None:
        """Switch the holiday colors on or off to match the setting and the date. The app
        eases into the new colors (a snapshot of the old look fades away)."""
        on = holiday_on(self.ctx, today)
        if on != theme.HOLIDAY:
            app = QApplication.instance()
            if animate and self.isVisible():
                crossfade(self.centralWidget(), ms=520)
            theme.set_holiday(on)
            theme.apply_theme(app)
            self._set_app_icon()
            for w in app.allWidgets():
                QWidget.update(w)        # (some dialogs keep data in an attribute called `update`)
        self.brand.refresh()
        self._set_footer()
        self.home.set_holiday(on, today)
        self.lights.set_on(on)
        self.countdown.setVisible(on)
        self.countdown.refresh(today)
        holidays_btn = self.nav_buttons[self.holidays]
        holidays_btn.setVisible(on)
        self.go_actions["Holidays"].setVisible(on)
        if not on and self.stack.currentWidget() is self.holidays:
            self.go(self.home, remember=False)
        self.holidays.today = today
        self.stats.set_holiday(on)
        if on:
            self._big_days(today)

    def _big_days(self, today=None) -> None:
        """Once-a-year moments: the Christmas card and the New Year's fireworks. And Santa's
        sleigh over Home, once a day."""
        today = today or dt.date.today()
        if self.ctx.pref("sleigh_day", "") != today.isoformat() and not reduce_motion():
            self.ctx.set_pref("sleigh_day", today.isoformat())
            QTimer.singleShot(2500, lambda: self.stack.currentWidget() is self.home and self.home.sleigh.play())
        year = str(holiday.season_year(today))
        if (holiday.holidays_open(today) and str(self.ctx.pref("holidays_remind", "")) == year
                and str(self.ctx.pref("holidays_reminded", "")) != year):
            self.ctx.set_pref("holidays_reminded", year)       # Remind me, from November
            self.alerts.notifier.notify("The advent calendar is open 🎁",
                                        "Door 1 has a Christmas episode behind it. Find it under Holidays.")
        if holiday.is_christmas(today) and str(self.ctx.pref("christmas_card", "")) != str(today.year):
            self.ctx.set_pref("christmas_card", str(today.year))
            QTimer.singleShot(900, lambda: self.show_christmas_card(today))
        if holiday.is_new_year(today) and str(self.ctx.pref("fireworks_year", "")) != str(today.year):
            QTimer.singleShot(900, lambda: self._new_year(today))
        if today.month == 12 and today.day == 31:
            midnight = dt.datetime.combine(today + dt.timedelta(days=1), dt.time())
            ms = int((midnight - self.now()).total_seconds() * 1000) + 1000
            if 0 < ms <= 86_401_000:
                self._midnight.start(ms)

    def show_christmas_card(self, today=None) -> None:
        today = today or dt.date.today()
        year = str(today.year)
        seconds = sum(sec for day, _a, _e, sec in self.ctx.store.watch_log() if str(day).startswith(year))
        self.christmas_card.present(*greeting_lines(first_name(), seconds, today.year))
        self.flurry.play()

    def _new_year(self, today=None) -> None:
        today = today or dt.date.today()
        if not holiday.is_new_year(today) or not theme.HOLIDAY:
            return
        self.ctx.set_pref("fireworks_year", str(today.year))
        self.apply_holiday(today)
        self.fireworks.play(today.year)

    def _set_footer(self) -> None:
        ani_cli = self._footer_ani_cli
        text = f"AniGUI {__version__}" + (f"  ·  ani-cli {ani_cli}" if ani_cli else "")
        self.footer.setText(text)

    # -- new episodes ---------------------------------------------------------------------

    def _on_new_episodes(self, items) -> None:
        if len(items) == 1:
            self.toast.show_message(f"New: {items[0].show.title} · {describe(items[0])}")
        else:
            self.toast.show_message(f"New episodes for {len(items)} shows. They're at the top of Home.")

    def _holiday_answer(self, turn_on: bool) -> None:
        import datetime as dt
        self.ctx.set_pref("holiday_banner_seen", str(dt.date.today().year))
        if turn_on:
            self.ctx.set_pref("holiday_theme", "early")

    def _show_from_notification(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.go(self.home)

    def closeEvent(self, event) -> None:
        self.playback.shutdown()  # save the current position before quitting
        self.ctx.downloads.shutdown()
        super().closeEvent(event)

    # -- startup ------------------------------------------------------------------------

    def start(self) -> None:
        self.apply_holiday(animate=False)
        self._holiday_timer.start()
        self.home.load_remote()
        self.home.refresh_local()
        self.alerts.start()
        if self.ctx.settings.value("import_history") is None and self.ctx.pref("setup_done", False):
            self.ctx.set_pref("import_history", True)  # 1.0/1.1 imported automatically; keep that
        self._import_terminal_history()
        self.ctx.runner.submit(setup.current_status, on_done=self._on_status)

    def _import_terminal_history(self) -> None:
        if self.ctx.pref("import_history"):
            self.ctx.runner.submit(self.ctx.store.import_ani_cli_history,
                                   on_done=lambda n: n and self._local_changed())

    def _set_versions(self, ani_cli: str | None) -> None:
        self._ani_cli_version = ani_cli
        self._footer_ani_cli = ani_cli
        self._set_footer()
        if self._settings:
            self._settings.set_versions(ani_cli)

    def _on_status(self, status: setup.SetupStatus) -> None:
        self._set_versions(status.ani_cli_version)
        if not status.ready:
            self.banner.setText("AniGUI needs a quick setup before it can play episodes. "
                                "<a href='#setup' style='color:#FF8559'>Open Setup</a>")
            self.banner.show()
        else:
            self.banner.hide()
            self._offer_built_in_player()
        if not status.ready or not self.ctx.pref("setup_done", False):
            if not self.ctx.pref("setup_done", False):
                self.ctx.set_pref("last_version", __version__)  # first launch: nothing is "new"
            QTimer.singleShot(400, self.open_setup)  # first launch, or something's missing
        elif (welcome := self.open_welcome()) is not None:
            welcome.finished.connect(lambda _r: self._check_updates(status))
        elif (whats_new := self._maybe_show_whats_new()) is not None:
            whats_new.finished.connect(lambda _r: self._check_updates(status))  # after the user reads it
        else:
            self._check_updates(status)

    def _offer_built_in_player(self) -> None:
        """New installs play inside AniGUI; everyone else is asked once."""
        if not self.ctx.player.embed_available():
            return
        if self.ctx.settings.value("player") is None and not self.ctx.pref("setup_done", False):
            self.ctx.set_pref("player", "anigui")
            return
        if self.ctx.pref("player", "auto") == "anigui" or self.ctx.pref("player_offer_seen", False):
            return
        self.banner.setText("New: episodes can play right here in AniGUI. "
                            "<a href='#try-player' style='color:#FF8559'>Try the built-in player</a>"
                            "&nbsp;&nbsp;·&nbsp;&nbsp;<a href='#not-now' style='color:#9B9BAF'>Not now</a>")
        self.banner.show()

    def _banner_link(self, link: str) -> None:
        if link == "#try-player":
            self.ctx.set_pref("player", "anigui")
            self.ctx.set_pref("player_offer_seen", True)
            self.banner.hide()
            self.toast.show_message("Episodes now play in AniGUI. Change it in Settings › Playback.")
        elif link == "#not-now":
            self.ctx.set_pref("player_offer_seen", True)
            self.banner.hide()
        else:
            self.open_setup()

    def open_welcome(self, force: bool = False):
        """Welcome (2.0), once, for a new install. Returns the dialog if it opened."""
        from .welcome import WelcomeDialog, should_welcome
        if not force and not should_welcome(self.ctx):
            return None
        dlg = WelcomeDialog(self.ctx, self)
        dlg.importAniList.connect(self.data.import_anilist)
        dlg.importMal.connect(lambda: self.data.import_mal())
        dlg.finished.connect(lambda _r: self.home.update_greeting())
        dlg.open()
        self._welcome = dlg
        return dlg

    def open_setup(self) -> None:
        dialog = SetupDialog(self.ctx, self)
        dialog.finished_setup.connect(lambda: self.ctx.runner.submit(setup.current_status, on_done=self._after_setup))
        dialog.open()
        self._setup_dialog = dialog

    def _after_setup(self, status: setup.SetupStatus) -> None:
        self._set_versions(status.ani_cli_version)
        self.banner.setVisible(not status.ready)
        if not status.ready:
            return
        if self.open_welcome():           # new install: say hello (2.0); nothing is "new" yet
            return
        # An update that needed Setup first (e.g. ani-cli was missing) still gets What's New
        whats_new = self._maybe_show_whats_new()
        if whats_new is not None:
            whats_new.finished.connect(lambda _r: self._check_updates(status))
        else:
            self._check_updates(status)

    # -- updates ------------------------------------------------------------------------

    def _check_updates(self, status: setup.SetupStatus) -> None:
        # ani-cli comes with AniGUI: each release pins a tested copy. Bring ours up to it.
        if status.ani_cli_managed:
            self.ctx.runner.submit(setup.ensure_pinned_ani_cli, on_done=self._ani_cli_updated)
        if not self.ctx.pref("check_updates"):
            return
        self.ctx.runner.submit(updates.check_anigui, self.ctx.store, on_done=self._offer_app_update)

    def _ani_cli_updated(self, version: str | None) -> None:
        if version:
            self._set_versions(version)
            self.toast.show_message(f"ani-cli updated to {version}, the version this AniGUI was tested with")

    def check_updates_now(self) -> None:
        """Menu / Settings: check both right away, and say so when nothing's new."""
        self.toast.show_message("Checking for updates…")

        def run():
            return updates.check_anigui(self.ctx.store, force=True)

        def done(app):
            if app:
                self._offer_app_update(app, manual=True)
            else:
                self.toast.show_message(f"You're up to date (AniGUI {__version__}"
                                        + (f", ani-cli {self._ani_cli_version})" if self._ani_cli_version else ")"))

        self.ctx.runner.submit(run, on_done=done,
                               on_error=lambda msg: self.toast.show_message(f"Couldn't check for updates: {msg}", error=True))

    def _ask(self, title: str, text: str, primary: str) -> str:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(f"<b>{html.escape(title)}</b>")
        box.setInformativeText(text)   # callers escape what they put in
        yes = box.addButton(primary, QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        skip = box.addButton("Skip This Version", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(yes)
        box.exec()
        clicked = box.clickedButton()
        return "yes" if clicked is yes else ("skip" if clicked is skip else "later")

    def _offer_app_update(self, update, manual: bool = False) -> None:
        if not update or (not manual and self.ctx.pref("skip_anigui", "") == update.latest):
            return
        app = self_update.running_app()
        can_install, _why = self_update.supported(app)
        if can_install and update.installable:
            answer = self._ask(f"AniGUI {update.latest} is available",
                               f"You have {html.escape(update.current)}. AniGUI downloads the update, installs it and restarts. "
                               f"Your library and progress stay as they are.", "Update Now")
        else:
            answer = self._ask(f"AniGUI {update.latest} is available",
                               f"You have {html.escape(update.current)}. Download the new version from GitHub, then replace "
                               f"AniGUI in Applications. Your library and progress carry over.", "Download")
        if answer == "skip":
            self.ctx.set_pref("skip_anigui", update.latest)
        elif answer == "yes" and can_install and update.installable:
            self.install_update(update, app)
        elif answer == "yes" and update.url:
            QDesktopServices.openUrl(QUrl(update.url))

    def install_update(self, update, app) -> UpdateDialog:
        dialog = UpdateDialog(self.ctx, update, app, self)
        dialog.installed.connect(self._restart_into)
        dialog.failed.connect(lambda msg, u=update: self._update_failed(u, msg))
        dialog.start()
        self._update_dialog = dialog
        return dialog

    def _restart_into(self, app) -> None:
        self.playback.shutdown()          # save the episode position first
        self_update.relaunch(app)
        QApplication.instance().quit()

    def _update_failed(self, update, message: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Update didn't finish")
        box.setText("<b>The update didn't finish</b>")
        box.setInformativeText(f"{html.escape(message)}<br><br>AniGUI is unchanged. You can download the new version from "
                               "GitHub and drag it into Applications instead.")
        page = box.addButton("Open Download Page", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is page and update.url:
            QDesktopServices.openUrl(QUrl(update.url))

    def _app_state(self, state) -> None:
        set_quiet("away", state != Qt.ApplicationState.ApplicationActive)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.WindowStateChange:
            set_quiet("minimized", self.isMinimized())
        super().changeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "player_host"):
            self.player_host.place()
        if self.toast.isVisible():
            self.toast.reposition()
