"""What leaves your Mac (2.0): every place AniGUI connects to, what it sends and why, what never
leaves, and the hosts it has actually contacted since it opened."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from core import privacy

from .context import AppContext


def _ago(t: float) -> str:
    s = max(0, int(time.time() - t))
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    return f"{s // 3600} h ago"


class PrivacyPage(QScrollArea):
    backRequested = Signal()

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Page")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(objectName="PageBody")
        col = QVBoxLayout(body)
        col.setContentsMargins(44, 32, 44, 44)
        col.setSpacing(14)

        back = QPushButton("‹  Back", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.backRequested)
        col.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        col.addWidget(QLabel("What leaves your Mac", objectName="LibraryTitle"))
        intro = QLabel("AniGUI has no accounts, no analytics and no tracking. It only connects where it has to, to "
                       "find and play anime. Here's every place, what goes there, and why.",
                       objectName="LibrarySub", wordWrap=True)
        col.addWidget(intro)

        never = QFrame(objectName="NeverPanel")
        ncol = QVBoxLayout(never)
        ncol.setContentsMargins(18, 14, 18, 14)
        ncol.setSpacing(6)
        ncol.addWidget(QLabel("Never leaves this Mac", objectName="YoursTitle"))
        for line in privacy.NEVER_SENT:
            ncol.addWidget(QLabel(f"✓  {line}", objectName="NeverLine"))
        col.addSpacing(6)
        col.addWidget(never)

        col.addSpacing(10)
        col.addWidget(QLabel("Where AniGUI connects", objectName="SectionTitle"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for i, d in enumerate(privacy.DESTINATIONS):
            card = QFrame(objectName="DestCard")
            c = QVBoxLayout(card)
            c.setContentsMargins(16, 12, 16, 14)
            c.setSpacing(5)
            head = QLabel(d.name, objectName="DestName")
            c.addWidget(head)
            for label, text in (("Sends", d.sends), ("Why", d.why), ("When", d.when)):
                row = QLabel(f"<b>{label}</b>&nbsp;&nbsp;{text}", objectName="DestLine", wordWrap=True)
                row.setTextFormat(Qt.TextFormat.RichText)
                c.addWidget(row)
            if d.hosts:
                c.addWidget(QLabel(" · ".join(d.hosts), objectName="DestHosts", wordWrap=True))
            c.addStretch(1)
            grid.addWidget(card, i // 2, i % 2)
        col.addLayout(grid)

        col.addSpacing(10)
        head = QHBoxLayout()
        head.addWidget(QLabel("Since AniGUI opened", objectName="SectionTitle"))
        head.addStretch(1)
        self.clear_btn = QPushButton("Clear", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(lambda: (privacy.LOG.clear(), self.refresh()))
        head.addWidget(self.clear_btn)
        col.addLayout(head)
        col.addWidget(QLabel("The places AniGUI actually contacted, counted. Only the host names: what was asked "
                             "isn't kept.", objectName="LibrarySub", wordWrap=True))
        self.live = QGridLayout()
        self.live.setHorizontalSpacing(24)
        self.live.setVerticalSpacing(6)
        col.addLayout(self.live)
        col.addStretch(1)
        self.setWidget(body)
        self._timer = QTimer(self, interval=2000)
        self._timer.timeout.connect(self.refresh)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.refresh()
        self._timer.start()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._timer.stop()

    def refresh(self) -> None:
        while self.live.count():
            w = self.live.takeAt(0).widget()
            if w:
                w.deleteLater()
        rows = privacy.LOG.snapshot()
        if not rows:
            self.live.addWidget(QLabel("Nothing yet.", objectName="DestLine"), 0, 0)
            return
        for i, (host, count, last, dest) in enumerate(rows):
            for j, text in enumerate((host, dest, f"{count}×", _ago(last))):
                self.live.addWidget(QLabel(text, objectName="LiveHost" if j == 0 else "DestLine"), i, j)
