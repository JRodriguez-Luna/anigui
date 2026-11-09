"""What's new in 2.0: a short, skippable tour for people updating from 1.x.

(New installs get Welcome instead.) Everything new is off until you switch it on, except the
media keys; the last page says so and opens Settings.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout,
                               QWidget)

from . import theme

PAGES = (
    ("AniGUI 2.0: yours", "Personal, private, and it all stays on your Mac. Here's what's new; it takes a minute.", (
        ("🎬", "Cinema", "A new look: the show's colors behind every page, and a full-bleed player."),
        ("📚", "My Library", "Your own lists, ratings, tags and notes, and a timeline of what you watched. "
                             "My List is now called Saved; everything in it is still there."),
        ("🔒", "Private", "Private mode, Touch ID locks, and a page that shows everything AniGUI connects to."),
    )),
    ("Watching", "The built-in player picked up a few tricks.", (
        ("🪟", "Pop out", "P floats the video over other apps and full-screen windows."),
        ("⬇", "Downloads", "Right-click an episode → Download, and watch it with no internet."),
        ("✨", "Moments and Sharper picture", "B saves the frame you're on. Sharper picture (⚙ menu) cleans up "
                                            "older or lower-quality video."),
        ("⏯", "Media keys", "Your keyboard's ⏯ ⏭ keys, AirPods and Control Center control the player."),
        ("🌙", "Sleep timer and your queue", "Stop after this episode or in 30 minutes; queue what's next."),
    )),
    ("Yours", "AniGUI keeps track for you, not for anyone else.", (
        ("⭐", "Rate, tag and note", "Under Yours on any show's page."),
        ("🎁", "Wrapped and goals", "Your year in anime on the Stats page, plus a weekly goal and streaks."),
        ("💾", "Back up and bring your list", "One file with everything; import from AniList or MyAnimeList."),
        ("🎨", "Make it yours", "Your color, an app icon to match, your name on Home, Home's rows in your order."),
    )),
)


class TourDialog(QDialog):
    openSettings = Signal(str)          # a Settings section

    def __init__(self, ctx, parent=None, backup: Path | None = None) -> None:
        super().__init__(parent)
        self.ctx, self.backup = ctx, backup
        self.setObjectName("WelcomeDialog")
        self.setWindowTitle("What's new in AniGUI 2.0")
        self.setFixedSize(640, 560)
        self.pages = QStackedWidget()
        for title, sub, rows in PAGES:
            self.pages.addWidget(self._page(title, sub, rows, first=not self.pages.count()))
        self.pages.addWidget(self._last())

        self._dots: list[QLabel] = []
        dots = QHBoxLayout()
        dots.setSpacing(6)
        for _ in range(self.pages.count()):
            d = QLabel(objectName="WelcomeDot")
            d.setFixedSize(8, 8)
            self._dots.append(d)
            dots.addWidget(d)
        self.skip = QPushButton("Skip", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.skip.clicked.connect(self.accept)
        self.back = QPushButton("Back", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.back.clicked.connect(lambda: self.go(self.pages.currentIndex() - 1))
        self.next = QPushButton("Next", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        self.next.setDefault(True)
        self.next.clicked.connect(self._next)
        bar = QHBoxLayout()
        bar.addLayout(dots)
        bar.addStretch(1)
        bar.addWidget(self.skip)
        bar.addWidget(self.back)
        bar.addWidget(self.next)

        col = QVBoxLayout(self)
        col.setContentsMargins(36, 30, 36, 24)
        col.setSpacing(14)
        col.addWidget(self.pages, 1)
        col.addLayout(bar)
        self.go(0)

    def _rows(self, rows) -> QWidget:
        box = QWidget(objectName="WelcomeRow")
        grid = QGridLayout(box)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(2)
        for i, (icon, title, text) in enumerate(rows):
            ic = QLabel(icon, objectName="WelcomeIcon")
            ic.setFixedWidth(28)
            grid.addWidget(ic, i * 2, 0, 2, 1, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(QLabel(title, objectName="SettingTitle"), i * 2, 1)
            t = QLabel(text, objectName="Muted", wordWrap=True)
            t.setContentsMargins(0, 0, 0, 8 if i < len(rows) - 1 else 0)
            grid.addWidget(t, i * 2 + 1, 1)
        return box

    def _page(self, title: str, sub: str, rows, first: bool = False) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        if first and theme.HOLIDAY:
            title += " 🎄"
        col.addWidget(QLabel(title, objectName="WelcomeTitle", wordWrap=True))
        col.addWidget(QLabel(sub, objectName="Muted", wordWrap=True))
        col.addWidget(self._rows(rows))
        if first and self.backup is not None:
            note = QHBoxLayout()
            note.addWidget(QLabel("Your history and lists were backed up before updating, just in case.",
                                  objectName="Muted", wordWrap=True), 1)
            show = QPushButton("Show", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
            show.clicked.connect(self._show_backup)
            note.addWidget(show)
            col.addLayout(note)
        col.addStretch(1)
        return page

    def _last(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        col.addWidget(QLabel("Nothing changes until you say so", objectName="WelcomeTitle", wordWrap=True))
        col.addWidget(QLabel("New features start off, so AniGUI works just like before. Switch on what you like in "
                             "Settings. (The media keys are on; Settings → Playback turns them off.)",
                             objectName="Muted", wordWrap=True))
        for section, label in (("Make it yours", "Pick your color and name"), ("Privacy", "Privacy and locks"),
                               ("Your data", "Back up or bring your list")):
            b = QPushButton(label, cursor=Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, s=section: (self.accept(), self.openSettings.emit(s)))
            row = QHBoxLayout()
            row.addWidget(b)
            row.addStretch(1)
            col.addLayout(row)
        col.addWidget(QLabel("Every change, small ones too, is in the AniGUI menu → What's New.", objectName="Muted"))
        col.addStretch(1)
        return page

    def go(self, index: int) -> None:
        index = max(0, min(self.pages.count() - 1, index))
        self.pages.setCurrentIndex(index)
        last = index == self.pages.count() - 1
        self.back.setVisible(index > 0)
        self.skip.setVisible(not last)
        self.next.setText("Done" if last else "Next")
        for i, d in enumerate(self._dots):
            d.setProperty("on", i == index)
            d.style().unpolish(d)
            d.style().polish(d)

    def _next(self) -> None:
        if self.pages.currentIndex() == self.pages.count() - 1:
            self.accept()
        else:
            self.go(self.pages.currentIndex() + 1)

    def _show_backup(self) -> None:
        if self.backup is not None and sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(self.backup)])
