"""Window shell: sidebar navigation, page stack with Back history, toasts, startup checks."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMessageBox, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from core.anilist import Media
from core import __version__
from core import setup, updates

from .alerts import AlertsController, describe
from .context import AppContext
from .detail_page import DetailPage
from .home_page import HomePage
from .library_page import LibraryPage
from .playback import PlaybackController
from .search_page import SearchPage
from .settings_dialog import SettingsDialog
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
        self.alerts = AlertsController(ctx, self)
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
        self.settings_btn = QPushButton("⚙   Settings", objectName="NavButton", cursor=Qt.CursorShape.PointingHandCursor)
        self.settings_btn.setToolTip(QKeySequence(QKeySequence.StandardKey.Preferences).toString(
            QKeySequence.SequenceFormat.NativeText) or "Settings")
        self.settings_btn.clicked.connect(lambda: self.open_settings())
        side.addWidget(self.settings_btn)
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
        self.home.historyChanged.connect(self.detail.refresh_if_showing)
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

        self.alerts.changed.connect(self.home.refresh_local)
        self.alerts.found.connect(self._on_new_episodes)
        self.alerts.notifier.clicked.connect(self._show_from_notification)
        ctx.events.changed.connect(lambda key, _v: key == "alerts" and self.home.refresh_local())

        self.nav_buttons[self.home].setChecked(True)
        self._build_menus()
        self._settings: SettingsDialog | None = None
        self._ani_cli_version: str | None = None

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

        history = bar.addMenu("History")
        clear = history.addAction("Clear Watch History…")
        clear.triggered.connect(self.home.confirm_clear_history)

    def open_settings(self, section: str | None = None) -> SettingsDialog:
        if self._settings is None:
            dlg = SettingsDialog(self.ctx, self)
            dlg.clearHistoryRequested.connect(self.home.confirm_clear_history)
            dlg.setupRequested.connect(self.open_setup)
            dlg.checkUpdatesRequested.connect(self.check_updates_now)
            dlg.whatsNewRequested.connect(lambda: self.show_whats_new())
            dlg.checkEpisodesRequested.connect(lambda: self.alerts.check_now(manual=True))
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
        return self.show_whats_new(last or "1.1.0")

    # -- new episodes ---------------------------------------------------------------------

    def _on_new_episodes(self, items) -> None:
        if len(items) == 1:
            self.toast.show_message(f"New: {items[0].show.title} · {describe(items[0])}")
        else:
            self.toast.show_message(f"New episodes for {len(items)} shows. They're at the top of Home.")

    def _show_from_notification(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.go(self.home)

    def closeEvent(self, event) -> None:
        self.playback.shutdown()  # save the current position before quitting
        super().closeEvent(event)

    # -- startup ------------------------------------------------------------------------

    def start(self) -> None:
        self.home.load_remote()
        self.home.refresh_local()
        self.alerts.start()
        if self.ctx.pref("import_history"):
            self.ctx.runner.submit(self.ctx.store.import_ani_cli_history,
                                   on_done=lambda n: n and self.home.refresh_local())
        self.ctx.runner.submit(setup.current_status, on_done=self._on_status)

    def _set_versions(self, ani_cli: str | None) -> None:
        self._ani_cli_version = ani_cli
        self.footer.setText(f"AniGUI {__version__}" + (f"  ·  ani-cli {ani_cli}" if ani_cli else ""))
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
        if not status.ready or not self.ctx.pref("setup_done", False):
            if not self.ctx.pref("setup_done", False):
                self.ctx.set_pref("last_version", __version__)  # first launch: nothing is "new"
            QTimer.singleShot(400, self.open_setup)  # first launch, or something's missing
        elif (whats_new := self._maybe_show_whats_new()) is not None:
            whats_new.finished.connect(lambda _r: self._check_updates(status))  # after the user reads it
        else:
            self._check_updates(status)

    def open_setup(self) -> None:
        dialog = SetupDialog(self.ctx, self)
        dialog.finished_setup.connect(lambda: self.ctx.runner.submit(setup.current_status, on_done=self._after_setup))
        dialog.open()
        self._setup_dialog = dialog

    def _after_setup(self, status: setup.SetupStatus) -> None:
        self._set_versions(status.ani_cli_version)
        self.banner.setVisible(not status.ready)
        if status.ready:
            self._check_updates(status)

    # -- updates ------------------------------------------------------------------------

    def _check_updates(self, status: setup.SetupStatus) -> None:
        if not self.ctx.pref("check_updates"):
            return
        if status.ani_cli_managed:
            self.ctx.runner.submit(updates.check_ani_cli, status.ani_cli_version, self.ctx.store,
                                   on_done=self._offer_ani_cli_update)
        self.ctx.runner.submit(updates.check_anigui, self.ctx.store, on_done=self._offer_app_update)

    def check_updates_now(self) -> None:
        """Menu / Settings: check both right away, and say so when nothing's new."""
        self.toast.show_message("Checking for updates…")

        def run():
            status = setup.current_status()
            ani = (updates.check_ani_cli(status.ani_cli_version, self.ctx.store, force=True)
                   if status.ani_cli_managed and status.ani_cli_version else None)
            return ani, updates.check_anigui(self.ctx.store, force=True)

        def done(result):
            ani, app = result
            if app:
                self._offer_app_update(app, manual=True)
            if ani:
                self._offer_ani_cli_update(ani, manual=True)
            if not (ani or app):
                self.toast.show_message(f"You're up to date (AniGUI {__version__}"
                                        + (f", ani-cli {self._ani_cli_version})" if self._ani_cli_version else ")"))

        self.ctx.runner.submit(run, on_done=done,
                               on_error=lambda msg: self.toast.show_message(f"Couldn't check for updates: {msg}", error=True))

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

    def _offer_ani_cli_update(self, update, manual: bool = False) -> None:
        if not update or (not manual and self.ctx.pref("skip_ani_cli", "") == update.latest):
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
                                                      self._set_versions(v)),
                                   on_error=lambda msg: self.toast.show_message(f"ani-cli update failed: {msg}", error=True))

    def _offer_app_update(self, update, manual: bool = False) -> None:
        if not update or (not manual and self.ctx.pref("skip_anigui", "") == update.latest):
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
