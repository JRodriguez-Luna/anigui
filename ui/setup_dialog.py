"""Setup assistant: ani-cli, a video player, and a connection check, all one click each."""

from __future__ import annotations

import html

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QRadioButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from core import setup
from core.ani_cli import SUPPORTED_VERSIONS

from .context import AppContext

VPN_CHOICES = (
    ("warp", "Use Cloudflare WARP (free)"),
    ("own", "I'll use my own VPN"),
    ("none", "Continue without a VPN (search and playback may fail)"),
)


class StepRow(QFrame):
    """One checklist line: status dot, title, detail, action button."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent, objectName="SetupRow")
        self.dot = QLabel("•", objectName="SetupDot")
        self.dot.setFixedWidth(26)
        self.title = QLabel(title, objectName="SetupTitle")
        self.detail = QLabel("Checking…", objectName="Muted", wordWrap=True)
        self.detail.setOpenExternalLinks(True)
        self.button = QPushButton("", cursor=Qt.CursorShape.PointingHandCursor)
        self.button.setVisible(False)

        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(self.title)
        text.addWidget(self.detail)

        self.top = QHBoxLayout()
        self.top.setSpacing(12)
        self.top.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        self.top.addLayout(text, 1)
        self.top.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(10)
        self.body.addLayout(self.top)

    def set_state(self, state: str, detail: str, action: str | None = None) -> None:
        """state: ok | needed | busy | warn"""
        self.dot.setText({"ok": "✓", "needed": "!", "busy": "…", "warn": "!"}.get(state, "•"))
        self.dot.setProperty("state", state)
        self.dot.style().unpolish(self.dot)
        self.dot.style().polish(self.dot)
        self.detail.setText(detail)
        self.button.setVisible(bool(action))
        self.button.setEnabled(state != "busy")
        if action:
            self.button.setText(action)
        dialog = self.window()
        if hasattr(dialog, "_fit"):
            QTimer.singleShot(0, dialog._fit)


class SetupDialog(QDialog):
    finished_setup = Signal()

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.status: setup.SetupStatus | None = None
        self.network: setup.NetworkStatus | None = None
        self._queue: list[str] = []
        self.setWindowTitle("Set up AniGUI")
        self.setObjectName("SetupDialog")
        self.setModal(True)
        self.setFixedWidth(660)

        heading = QLabel("Set up AniGUI", objectName="DialogTitle")
        intro = QLabel("AniGUI needs ani-cli to find streams and a video player to watch them. "
                       "It can install both for you; nothing else is required.", objectName="Muted", wordWrap=True)

        self.ani_cli = StepRow("ani-cli")
        self.ani_cli.button.clicked.connect(self.install_ani_cli)
        self.player = StepRow("Video player")
        self.player.button.clicked.connect(self.install_player)
        self.net = StepRow("Connection to hianime")
        self.net.button.clicked.connect(self.check_connection)

        # VPN choices, shown only when hianime is blocked
        self.vpn_box = QWidget()
        vpn = QVBoxLayout(self.vpn_box)
        vpn.setContentsMargins(38, 0, 0, 0)
        vpn.setSpacing(6)
        self.vpn_group = QButtonGroup(self)
        saved = str(ctx.pref("vpn_choice", ""))
        for key, label in VPN_CHOICES:
            radio = QRadioButton(label, cursor=Qt.CursorShape.PointingHandCursor)
            radio.setProperty("choice", key)
            radio.setChecked(key == saved)
            self.vpn_group.addButton(radio)
            vpn.addWidget(radio)
        self.vpn_group.buttonToggled.connect(self._vpn_changed)
        self.get_warp = QPushButton("Get Cloudflare WARP", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.get_warp.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(setup.WARP_URL)))
        self.get_warp.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.vpn_hint = QLabel("", objectName="Muted", wordWrap=True)
        vpn.addSpacing(4)
        vpn.addWidget(self.vpn_hint)
        vpn.addWidget(self.get_warp, 0, Qt.AlignmentFlag.AlignLeft)
        self.net.body.addWidget(self.vpn_box)
        self.vpn_box.setVisible(False)

        # Optional: shows watched with ani-cli in Terminal (only shown when there are some)
        self.terminal = StepRow("Terminal history (optional)")
        self.terminal.button.clicked.connect(self.import_terminal_history)
        self.terminal.setVisible(False)
        self._terminal_count = 0

        self.everything = QPushButton("Set up everything", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        self.everything.clicked.connect(self.set_up_everything)
        self.done_btn = QPushButton("Done", cursor=Qt.CursorShape.PointingHandCursor)
        self.done_btn.clicked.connect(self._finish)
        self.footer_note = QLabel("", objectName="Muted", wordWrap=True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.footer_note, 1)
        buttons.addWidget(self.everything)
        buttons.addWidget(self.done_btn)

        col = QVBoxLayout(self)
        col.setContentsMargins(26, 24, 26, 22)
        col.setSpacing(12)
        col.addWidget(heading)
        col.addWidget(intro)
        col.addSpacing(4)
        col.addWidget(self.ani_cli)
        col.addWidget(self.player)
        col.addWidget(self.net)
        col.addWidget(self.terminal)
        col.addSpacing(6)
        col.addLayout(buttons)

        self.refresh()

    # -- checks -----------------------------------------------------------------------

    def refresh(self) -> None:
        self._check_terminal_history()
        self.ani_cli.set_state("busy", "Checking…")
        self.player.set_state("busy", "Checking…")
        self.ctx.runner.submit(setup.current_status, on_done=self._on_status,
                               on_error=lambda msg: self.ani_cli.set_state("needed", msg, "Install"),
                               group="setup-status")
        self.check_connection()

    def check_connection(self) -> None:
        self.net.set_state("busy", "Testing search and the video servers (takes a few seconds)…")
        self.ctx.runner.submit(setup.check_network, on_done=self._on_network,
                               on_error=lambda msg: self.net.set_state("warn", msg, "Test again"),
                               group="setup-network")

    def _on_status(self, status: setup.SetupStatus) -> None:
        self.status = status
        if status.ani_cli_path and status.ani_cli_supported:
            where = "AniGUI's copy" if status.ani_cli_managed else "your Terminal install"
            self.ani_cli.set_state("ok", f"Version {status.ani_cli_version} ({where}).")
        elif status.ani_cli_path:
            self.ani_cli.set_state(
                "needed", f"Your ani-cli is version {status.ani_cli_version or 'unknown'}, but AniGUI needs "
                          f"{SUPPORTED_VERSIONS[0]}.x. Install AniGUI's own copy (your Terminal one stays as it is).",
                "Install")
        else:
            self.ani_cli.set_state("needed", "Not installed. AniGUI downloads it from ani-cli's official GitHub.",
                                   "Install")
        wanted = str(self.ctx.pref("player", "auto"))
        if status.player and not status.iina and wanted == "iina":
            self.player.set_state("needed", "Playback is set to IINA, but only mpv is installed. Episodes open in "
                                            "mpv until you install IINA.", "Install IINA")
        elif status.player:
            kind, _path = status.player
            self.player.set_state("ok", f"{'IINA' if kind == 'iina' else 'mpv'} is installed.")
        else:
            self.player.set_state("needed", "No player found. AniGUI can install IINA, a free player for Mac.",
                                  "Install IINA")
        self._update_footer()
        self._next_in_queue()

    def _on_network(self, status: setup.NetworkStatus) -> None:
        self.network = status
        blocked = status.state == "blocked"
        self.vpn_box.setVisible(blocked)
        if status.ok:
            self.net.set_state("ok", "hianime is reachable.")
        elif blocked:
            self.net.set_state("warn", status.message, "Test again")
            self._vpn_changed()
        else:
            self.net.set_state("warn", status.message, "Test again")
        self._update_footer()

    def _vpn_changed(self, *_args) -> None:
        checked = self.vpn_group.checkedButton()
        choice = checked.property("choice") if checked else ""
        if choice:
            self.ctx.set_pref("vpn_choice", choice)
        self.get_warp.setVisible(choice in ("", "warp"))
        QTimer.singleShot(0, self._fit)
        self.vpn_hint.setText({
            "warp": "Install WARP, switch it on, then press Test again.",
            "own": "Connect your VPN, then press Test again.",
            "none": "You can still browse; searches and playback may fail on this network.",
        }.get(choice, "Pick an option, connect, then press Test again."))

    def _check_terminal_history(self) -> None:
        count = self.ctx.store.ani_cli_history_shows()
        self._terminal_count = count
        if not count:
            self.terminal.setVisible(False)
            return
        self.terminal.setVisible(True)
        shows = f"{count} show{'s' if count != 1 else ''}"
        if self.ctx.pref("import_history"):
            self.terminal.set_state("ok", f"Your {shows} from ani-cli in Terminal show up in Continue Watching.")
        else:
            self.terminal.set_state("optional", f"You've watched {shows} with ani-cli in Terminal. Add them to "
                                              "Continue Watching? You can change this later in Settings.", "Import")

    def import_terminal_history(self) -> None:
        self.terminal.set_state("busy", "Importing…")
        self.ctx.set_pref("import_history", True)  # main window imports on this change
        self.ctx.runner.submit(self.ctx.store.import_ani_cli_history,
                               on_done=lambda _n: self._check_terminal_history(),
                               on_error=lambda msg: self.terminal.set_state("needed", msg, "Try again"))

    # -- installs ---------------------------------------------------------------------

    def install_ani_cli(self) -> None:
        self.ani_cli.set_state("busy", "Downloading ani-cli from GitHub…")
        self.ctx.runner.submit(setup.install_ani_cli,
                               on_done=lambda v: self._installed(self.ani_cli, f"Installed ani-cli {v}."),
                               on_error=lambda msg: self._failed(self.ani_cli, msg, "Try again"))

    def install_player(self) -> None:
        self.player.set_state("busy", "Downloading and installing IINA (about 30 MB)…")
        self.ctx.runner.submit(setup.install_iina,
                               on_done=lambda path: self._installed(self.player, f"Installed IINA in {path.parent}."),
                               on_error=lambda msg: self._failed(self.player, msg, "Try again"))

    def set_up_everything(self) -> None:
        self._queue = []
        if self.status and not (self.status.ani_cli_path and self.status.ani_cli_supported):
            self._queue.append("ani-cli")
        if self.status and (not self.status.player or (
                not self.status.iina and self.ctx.pref("player", "auto") == "iina")):
            self._queue.append("player")
        self._queue.append("network")
        self.everything.setEnabled(False)
        self._next_in_queue()

    def _next_in_queue(self) -> None:
        if not self._queue:
            self.everything.setEnabled(True)
            return
        step = self._queue.pop(0)
        if step == "ani-cli":
            self.install_ani_cli()
        elif step == "player":
            self.install_player()
        else:
            self.check_connection()
            self.everything.setEnabled(True)

    def _installed(self, row: StepRow, message: str) -> None:
        row.set_state("ok", message)
        self.ctx.runner.submit(setup.current_status, on_done=self._on_status, group="setup-status")

    def _failed(self, row: StepRow, message: str, action: str) -> None:
        if "iina.io" in message:
            message = html.escape(message).replace(
                "iina.io", f"<a href='{setup.IINA_SITE}' style='color:#FF8559'>iina.io</a>")
        row.set_state("needed", message, action)
        self._queue = []
        self.everything.setEnabled(True)

    # -- sizing -----------------------------------------------------------------------

    def _fit(self) -> None:
        """Size the height to the wrapped text; Qt doesn't do this for dialogs on its own."""
        lay = self.layout()
        lay.activate()
        width = self.width()
        height = lay.heightForWidth(width) if lay.hasHeightForWidth() else lay.sizeHint().height()
        self.setFixedHeight(max(height, lay.minimumSize().height()))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit()

    # -- finish -----------------------------------------------------------------------

    def _update_footer(self) -> None:
        QTimer.singleShot(0, self._fit)
        ready = bool(self.status and self.status.ready)
        if not ready:
            self.footer_note.setText("AniGUI can't play episodes until ani-cli and a player are set up.")
        elif self.network and not self.network.ok:
            self.footer_note.setText("Ready, but hianime isn't reachable yet. See the connection options above.")
        else:
            self.footer_note.setText("All set.")
        self.everything.setVisible(not ready)

    def _finish(self) -> None:
        self.ctx.set_pref("setup_done", True)
        self.finished_setup.emit()
        self.accept()
