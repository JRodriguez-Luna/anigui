"""Window shell: sidebar navigation, page stack with Back history, toasts, startup checks."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMessageBox, QButtonGroup, QCheckBox, QComboBox, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from core.anilist import Media
from core import __version__
from core import setup, updates
from core.env import which

from .context import AppContext
from .detail_page import DetailPage
from .home_page import HomePage
from .library_page import LibraryPage
from .playback import PlaybackController
from .search_page import SearchPage
from .setup_dialog import SetupDialog
from .widgets import Toast



class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("AniGUI")
        self.resize(1320, 860)
        self.setMinimumSize(980, 640)

        self.playback = PlaybackController(ctx, self)
        self.home = HomePage(ctx)
        self.search = SearchPage(ctx)
        self.library = LibraryPage(ctx)
        self.detail = DetailPage(ctx, self.playback)

        self.stack = QStackedWidget()
        for page in (self.home, self.search, self.library, self.detail):
            self.stack.addWidget(page)
        self.history: list[QWidget] = []

        # Sidebar
        sidebar = QWidget(objectName="Sidebar")
        sidebar.setFixedWidth(208)
        self.nav = QButtonGroup(self)
        self.nav_buttons: dict[QWidget, QPushButton] = {}
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 26, 14, 16)
        side.setSpacing(4)
        brand = QLabel("Ani<span style='color:#FF6B3D'>GUI</span>", objectName="Brand")
        side.addWidget(brand)
        for label, page, keys in (("⌂   Home", self.home, "Ctrl+1"), ("⌕   Search", self.search, "Ctrl+2"),
                                  ("♡   My List", self.library, "Ctrl+3")):
            btn = QPushButton(label, objectName="NavButton", checkable=True, cursor=Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, p=page: self.go(p))
            btn.setToolTip(QKeySequence(keys).toString(QKeySequence.SequenceFormat.NativeText))
            QShortcut(QKeySequence(keys), self, activated=lambda p=page: self.go(p))
            self.nav.addButton(btn)
            self.nav_buttons[page] = btn
            side.addWidget(btn)
        side.addStretch(1)
        side.addWidget(self._playback_settings())
        self.setup_btn = QPushButton("⚙   Setup && connection", objectName="NavButton", cursor=Qt.CursorShape.PointingHandCursor)
        self.setup_btn.clicked.connect(self.open_setup)
        side.addSpacing(6)
        side.addWidget(self.setup_btn)
        side.addSpacing(10)
        self.footer = QLabel("", objectName="SidebarFooter", wordWrap=True)
        side.addWidget(self.footer)

        self.banner = QLabel("", objectName="Banner", wordWrap=True)
        self.banner.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.banner.linkActivated.connect(lambda _link: self.open_setup())
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
        self.toast = Toast(central)

        # Wiring
        for page in (self.home, self.search, self.library):
            page.openItem.connect(self.open_item)
        self.home.playItem.connect(lambda media: self.open_item(media, autoplay=True))
        self.search.setupRequested.connect(self.open_setup)
        self.detail.backRequested.connect(self.back)
        self.detail.libraryChanged.connect(self._local_changed)
        self.detail.toast.connect(lambda text, err: self.toast.show_message(text, error=err))
        self.playback.started.connect(lambda *_: self._local_changed())
        self.playback.sessionEnded.connect(self._local_changed)
        self.playback.episodeChanged.connect(lambda *_: self._local_changed())
        self.playback.notice.connect(lambda text, err: self.toast.show_message(text, error=err))

        QShortcut(QKeySequence.StandardKey.Find, self, activated=lambda: (self.go(self.search), self.search.focus_search()))
        QShortcut(QKeySequence.StandardKey.Back, self, activated=self.back)
        QShortcut(QKeySequence("Esc"), self, activated=lambda: self.stack.currentWidget() is self.detail and self.back())

        self.nav_buttons[self.home].setChecked(True)

    # -- navigation ---------------------------------------------------------------------

    def go(self, page: QWidget, remember: bool = True) -> None:
        current = self.stack.currentWidget()
        if page is current:
            return
        if remember:
            self.history.append(current)
            del self.history[:-30]
        self.stack.setCurrentWidget(page)
        if page in self.nav_buttons:
            self.nav_buttons[page].setChecked(True)
        if page is self.home:
            self.home.refresh_local()
        elif page is self.library:
            self.library.refresh()

    def back(self) -> None:
        while self.history:
            page = self.history.pop()
            if page is not self.stack.currentWidget():
                self.go(page, remember=False)
                return
        self.go(self.home, remember=False)

    def open_item(self, item, autoplay: bool = False) -> None:
        if isinstance(item, Media):
            self.detail.open_media(item, autoplay=autoplay)
        else:  # Show or SearchResult: both carry anime_id, title, poster
            self.detail.open_show(item.anime_id, item.title, item.poster, autoplay=autoplay)
        self.go(self.detail)

    def _local_changed(self) -> None:
        self.home.refresh_local()
        if self.stack.currentWidget() is self.library:
            self.library.refresh()

    # -- settings -----------------------------------------------------------------------

    def _playback_settings(self) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(4, 0, 4, 0)
        col.setSpacing(8)
        col.addWidget(QLabel("PLAYBACK", objectName="SidebarHeading"))

        self.player_choice = QComboBox(cursor=Qt.CursorShape.PointingHandCursor)
        for label, value in (("Auto (IINA, then mpv)", "auto"), ("IINA", "iina"), ("mpv", "mpv")):
            self.player_choice.addItem(label, value)
        self.player_choice.setCurrentIndex(max(0, self.player_choice.findData(str(self.ctx.pref("player", "auto")))))
        self.player_choice.currentIndexChanged.connect(
            lambda _i: self.ctx.set_pref("player", self.player_choice.currentData()))
        self.player_choice.setToolTip("Which player opens episodes")
        col.addWidget(self.player_choice)

        self.autoplay = QCheckBox("Auto-play next episode", cursor=Qt.CursorShape.PointingHandCursor)
        self.autoplay.setChecked(self.ctx.pref("autoplay", True))
        self.autoplay.toggled.connect(lambda on: self.ctx.set_pref("autoplay", on))
        col.addWidget(self.autoplay)

        self.skip_intro = QCheckBox("Skip intros", cursor=Qt.CursorShape.PointingHandCursor)
        has_skip = bool(which("ani-skip"))
        self.skip_intro.setEnabled(has_skip)
        self.skip_intro.setChecked(has_skip and self.ctx.pref("skip_intro", False))
        self.skip_intro.setToolTip("Uses ani-skip; works with mpv when a player window first opens"
                                   if has_skip else "Install ani-skip to enable: brew install ani-skip")
        self.skip_intro.toggled.connect(lambda on: self.ctx.set_pref("skip_intro", on))
        col.addWidget(self.skip_intro)
        return box

    def closeEvent(self, event) -> None:
        self.playback.shutdown()  # save the current position before quitting
        super().closeEvent(event)

    # -- startup ------------------------------------------------------------------------

    def start(self) -> None:
        self.home.load_remote()
        self.home.refresh_local()
        self.ctx.runner.submit(self.ctx.store.import_ani_cli_history,
                               on_done=lambda n: n and self.home.refresh_local())
        self.ctx.runner.submit(setup.current_status, on_done=self._on_status)

    def _on_status(self, status: setup.SetupStatus) -> None:
        version = status.ani_cli_version
        self.footer.setText(f"AniGUI {__version__}" + (f"  ·  ani-cli {version}" if version else ""))
        if not status.ready:
            self.banner.setText("AniGUI needs a quick setup before it can play episodes. "
                                "<a href='#setup' style='color:#FF8559'>Open Setup</a>")
            self.banner.show()
        else:
            self.banner.hide()
        if not status.ready or not self.ctx.pref("setup_done", False):
            QTimer.singleShot(400, self.open_setup)  # first launch, or something's missing
        else:
            self._check_updates(status)

    def open_setup(self) -> None:
        dialog = SetupDialog(self.ctx, self)
        dialog.finished_setup.connect(lambda: self.ctx.runner.submit(setup.current_status, on_done=self._after_setup))
        dialog.open()
        self._setup_dialog = dialog

    def _after_setup(self, status: setup.SetupStatus) -> None:
        version = status.ani_cli_version
        self.footer.setText(f"AniGUI {__version__}" + (f"  ·  ani-cli {version}" if version else ""))
        self.banner.setVisible(not status.ready)
        if status.ready:
            self._check_updates(status)

    # -- updates ------------------------------------------------------------------------

    def _check_updates(self, status: setup.SetupStatus) -> None:
        if status.ani_cli_managed:
            self.ctx.runner.submit(updates.check_ani_cli, status.ani_cli_version, self.ctx.store,
                                   on_done=self._offer_ani_cli_update)
        self.ctx.runner.submit(updates.check_anigui, self.ctx.store, on_done=self._offer_app_update)

    def _ask(self, title: str, text: str, primary: str) -> str:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(f"<b>{title}</b>")
        box.setInformativeText(text)
        yes = box.addButton(primary, QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        skip = box.addButton("Skip This Version", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(yes)
        box.exec()
        clicked = box.clickedButton()
        return "yes" if clicked is yes else ("skip" if clicked is skip else "later")

    def _offer_ani_cli_update(self, update) -> None:
        if not update or self.ctx.pref("skip_ani_cli", "") == update.latest:
            return
        note = "" if update.compatible else (
            "<br><br>This is a bigger update than AniGUI has been tested with; "
            "AniGUI may need an update too.")
        answer = self._ask(f"ani-cli {update.latest} is available",
                           f"You have {update.current}. Updates usually fix searching and playback "
                           f"when the site changes.{note}", "Update")
        if answer == "skip":
            self.ctx.set_pref("skip_ani_cli", update.latest)
        elif answer == "yes":
            self.ctx.runner.submit(setup.install_ani_cli, update.script,
                                   on_done=lambda v: (self.toast.show_message(f"ani-cli updated to {v}"),
                                                      self.footer.setText(f"AniGUI {__version__}  ·  ani-cli {v}")),
                                   on_error=lambda msg: self.toast.show_message(f"ani-cli update failed: {msg}", error=True))

    def _offer_app_update(self, update) -> None:
        if not update or self.ctx.pref("skip_anigui", "") == update.latest:
            return
        answer = self._ask(f"AniGUI {update.latest} is available",
                           f"You have {update.current}. Download the new version from GitHub, then replace "
                           f"AniGUI in Applications. Your library and progress carry over.", "Download")
        if answer == "skip":
            self.ctx.set_pref("skip_anigui", update.latest)
        elif answer == "yes" and update.url:
            QDesktopServices.openUrl(QUrl(update.url))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast.reposition()
