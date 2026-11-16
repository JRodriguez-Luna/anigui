"""Watch on your TV: the guide (2.1). Opens from the one-time pointer in the player, from Settings →
Playback and from the player's ⚙ menu. Looks for AirPlay TVs on your Wi-Fi while it's open."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.tvrelay import airplay_receivers, tvs

from . import theme

STEPS = (
    ("📺", "Turn on your TV",
     "It needs AirPlay (most Samsung, LG, Sony, Roku and Vizio TVs from 2018 on, and any Apple TV) and the "
     "same Wi-Fi as this Mac."),
    ("▶", "Play an episode, then click the AirPlay button",
     "It's in the player's controls, next to ⚙. The episode is already playing here, so nothing is lost."),
    ("✓", "Pick your TV in the menu that opens",
     "The episode moves to the TV from the same second, and this Mac becomes the remote: pause, Skip intro, "
     "the next episode, the sleep timer and your keyboard's ⏯ ⏭ keys all work from here."),
    ("↩", "Bring it back whenever you like",
     "“Bring back to this Mac” in the player picks up where the TV was."),
)


class TvGuideDialog(QDialog):
    sendRequested = Signal()        # "Send this episode": one is playing on this Mac right now

    def __init__(self, ctx, parent=None, can_send: bool = False) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("WelcomeDialog")
        self.setWindowTitle("Watch on your TV")
        self.setFixedSize(600, 520)
        self.receivers: list[str] | None = None

        title = QLabel("Watch on your TV" + (" 🎄" if theme.HOLIDAY else ""), objectName="WelcomeTitle")
        sub = QLabel("Send an episode to your AirPlay TV and use this Mac as the remote. It takes almost nothing "
                     "from this Mac's battery: the TV does the playing.", objectName="Muted", wordWrap=True)
        box = QWidget(objectName="WelcomeRow")
        grid = QGridLayout(box)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(2)
        for i, (icon, head, text) in enumerate(STEPS):
            ic = QLabel(icon, objectName="WelcomeIcon")
            ic.setFixedWidth(28)
            grid.addWidget(ic, i * 2, 0, 2, 1, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(QLabel(head, objectName="SettingTitle"), i * 2, 1)
            t = QLabel(text, objectName="Muted", wordWrap=True)
            t.setContentsMargins(0, 0, 0, 8 if i < len(STEPS) - 1 else 0)
            grid.addWidget(t, i * 2 + 1, 1)
        self.found = QLabel("Looking for AirPlay TVs on your Wi-Fi…", objectName="Muted", wordWrap=True)
        privacy = QLabel("The TV fetches the episode from this Mac over your Wi-Fi only. Nothing about you goes "
                         "with it, and nothing goes anywhere else.", objectName="SettingsNote", wordWrap=True)

        self.send = QPushButton("Send this episode", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.send.clicked.connect(lambda: (self.sendRequested.emit(), self.accept()))
        self.send.setVisible(can_send)
        self.ok = QPushButton("Got it", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        bar = QHBoxLayout()
        bar.addStretch(1)
        bar.addWidget(self.send)
        bar.addWidget(self.ok)

        col = QVBoxLayout(self)
        col.setContentsMargins(36, 30, 36, 24)
        col.setSpacing(12)
        col.addWidget(title)
        col.addWidget(sub)
        col.addWidget(box)
        col.addWidget(self.found)
        col.addWidget(privacy)
        col.addStretch(1)
        col.addLayout(bar)

        threading.Thread(target=self._scan, daemon=True).start()
        self._settle = QTimer(self, interval=400)
        self._settle.timeout.connect(self._show_found)
        self._settle.start()

    def _scan(self) -> None:
        self.receivers = airplay_receivers(3.0)

    def _show_found(self) -> None:
        if self.receivers is None:
            return
        self._settle.stop()
        found = tvs(self.receivers)
        if len(found) == 1:
            self.found.setText(f"Found on your Wi-Fi: {found[0]} ✓")
        elif found:
            self.found.setText(f"Found on your Wi-Fi: {', '.join(found)} ✓  Pick one in the AirPlay menu.")
        elif self.receivers:
            self.found.setText("Only this Mac answered on your Wi-Fi. Is the TV on, and on the same network?")
        else:
            self.found.setText("No AirPlay TVs answered on your Wi-Fi yet. Is the TV on, and on the same network? "
                               "Some TVs only answer once they're awake.")
