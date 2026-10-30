"""Runs new-episode checks on a timer and tells the user: Home row, toast, Mac notification."""

from __future__ import annotations

import subprocess
import sys
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from core import alerts
from core.store import NewEpisodes

from .context import AppContext

CHECK_EVERY_MS = 60 * 60 * 1000
FIRST_CHECK_MS = 15_000     # let startup (covers, Setup, updates) go first


def describe(item: NewEpisodes) -> str:
    if item.count > 1:
        return f"{item.count} new · up to EP {item.latest}"
    return f"Episode {item.latest} is out"


class Notifier(QObject):
    """Mac notifications. Qt's tray-icon messages show as notifications from AniGUI;
    if they aren't available, AppleScript's `display notification` is the fallback."""

    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.tray: QSystemTrayIcon | None = None

    def notify(self, title: str, body: str) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages():
            tray = self._tray()
            tray.show()
            tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.NoIcon, 10_000)
        elif sys.platform == "darwin":
            def q(text: str) -> str:
                return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
            try:
                subprocess.Popen(["osascript", "-e", f"display notification {q(body)} with title {q(title)}"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass

    def _tray(self) -> QSystemTrayIcon:
        if self.tray is None:
            app = QApplication.instance()
            icon = app.windowIcon() if app and not app.windowIcon().isNull() else QIcon()
            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip("AniGUI")
            menu = QMenu()
            menu.addAction("Open AniGUI").triggered.connect(self.clicked)
            self.tray.setContextMenu(menu)
            self._menu = menu
            self.tray.messageClicked.connect(self.clicked)
            self.tray.activated.connect(lambda _reason: self.clicked.emit())
        return self.tray


class AlertsController(QObject):
    found = Signal(list)            # list[NewEpisodes] that are new since the last notification
    changed = Signal()              # the set of new episodes changed (refresh Home)
    status = Signal(str, bool)      # message, busy

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.notifier = Notifier(self)
        self.running = False
        self.last_checked: float | None = None
        self._timer = QTimer(self, interval=CHECK_EVERY_MS)
        self._timer.timeout.connect(self.check_now)
        ctx.events.changed.connect(self._pref_changed)

    def start(self) -> None:
        if self.ctx.pref("alerts"):
            self._timer.start()
            QTimer.singleShot(FIRST_CHECK_MS, self.check_now)

    def _pref_changed(self, key: str, _value) -> None:
        if key == "alerts":
            if self.ctx.pref("alerts"):
                self._timer.start()
                self.check_now()
            else:
                self._timer.stop()
        elif key == "alerts_scope" and self.ctx.pref("alerts"):
            self.check_now()

    def check_now(self, manual: bool = False) -> None:
        if self.running or not (manual or self.ctx.pref("alerts")):
            return
        self.running = True
        self.status.emit("Checking for new episodes…", True)
        self.ctx.runner.submit(alerts.check, self.ctx.store, self.ctx.catalog, str(self.ctx.pref("alerts_scope")),
                               on_done=self._done, on_error=self._failed)

    def _done(self, fresh: list[NewEpisodes]) -> None:
        self.running = False
        self.last_checked = time.time()
        waiting = len(self.ctx.store.new_episodes())
        self.status.emit(f"Last checked {time.strftime('%-I:%M %p')}. "
                         + (f"{waiting} show{'s' if waiting != 1 else ''} with new episodes." if waiting
                            else "No new episodes."), False)
        self.changed.emit()
        if not fresh:
            return
        self.found.emit(fresh)
        if self.ctx.pref("notify"):
            if len(fresh) == 1:
                self.notifier.notify(fresh[0].show.title, describe(fresh[0]))
            else:
                names = ", ".join(i.show.title for i in fresh[:3]) + ("…" if len(fresh) > 3 else "")
                self.notifier.notify(f"New episodes for {len(fresh)} shows", names)

    def _failed(self, message: str) -> None:
        self.running = False
        self.status.emit(f"Couldn't check: {message}", False)
