"""Welcome (2.0): a short hello for new installs (nothing watched or saved yet).

Four pages, all skippable: what AniGUI promises about your data, your name and color, bringing
your list from AniList or MyAnimeList, and the keys worth knowing. People updating from 1.x get
"What's new in 2.0" instead.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from . import theme

PROMISES = (
    ("🔒", "Yours, on this Mac", "Your history, lists, ratings and notes live here. No account, no sign-in."),
    ("🙈", "Nothing about you is sent", "No analytics, no tracking, no ads. Settings → Privacy shows every place "
                                       "AniGUI connects to, and why."),
    ("💾", "Easy to keep", "Back up everything to one file, and restore it on any Mac."),
)

KEYS = (
    ("Space", "Play / pause"),
    ("← →", "Back / forward 10 seconds"),
    ("N", "Next episode"),
    ("E", "Episode list"),
    ("F", "Full screen"),
    ("P", "Pop out (stays on top)"),
    ("B", "Save this moment"),
    ("⌘F", "Search"),
)


def should_welcome(ctx) -> bool:
    """New installs only: nothing watched, saved or listed yet."""
    if ctx.pref("welcomed"):
        return False
    store = ctx.store
    if store.all_progress() or store.library_all():
        ctx.set_pref("welcomed", True)       # someone with history: What's New covers 2.0
        return False
    return True


class WelcomeDialog(QDialog):
    importAniList = Signal(str)
    importMal = Signal()

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("WelcomeDialog")
        self.setWindowTitle("Welcome to AniGUI")
        self.setFixedSize(620, 520)
        self.pages = QStackedWidget()
        for page in (self._promise(), self._yours(), self._import(), self._keys()):
            self.pages.addWidget(page)

        self.dots = QHBoxLayout()
        self.dots.setSpacing(6)
        self._dots: list[QLabel] = []
        for _ in range(self.pages.count()):
            d = QLabel(objectName="WelcomeDot")
            d.setFixedSize(8, 8)
            self._dots.append(d)
            self.dots.addWidget(d)
        self.skip = QPushButton("Skip", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.skip.clicked.connect(self.finish)
        self.back = QPushButton("Back", objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.back.clicked.connect(lambda: self.go(self.pages.currentIndex() - 1))
        self.next = QPushButton("Next", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        self.next.setDefault(True)
        self.next.clicked.connect(self._next)
        bar = QHBoxLayout()
        bar.addLayout(self.dots)
        bar.addStretch(1)
        bar.addWidget(self.skip)
        bar.addWidget(self.back)
        bar.addWidget(self.next)

        col = QVBoxLayout(self)
        col.setContentsMargins(36, 32, 36, 24)
        col.setSpacing(16)
        col.addWidget(self.pages, 1)
        col.addLayout(bar)
        self.go(0)

    # -- pages ----------------------------------------------------------------------------------

    @staticmethod
    def _heading(title: str, sub: str) -> list[QWidget]:
        t = QLabel(title, objectName="WelcomeTitle", wordWrap=True)
        s = QLabel(sub, objectName="Muted", wordWrap=True)
        return [t, s]

    def _page(self, widgets: list[QWidget]) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        for w in widgets:
            col.addWidget(w)
        col.addStretch(1)
        return page

    def _promise(self) -> QWidget:
        holiday = " 🎄" if theme.HOLIDAY else ""
        rows = []
        for icon, title, text in PROMISES:
            row = QWidget(objectName="WelcomeRow")
            grid = QGridLayout(row)
            grid.setContentsMargins(14, 12, 14, 12)
            grid.setHorizontalSpacing(14)
            i = QLabel(icon, objectName="WelcomeIcon")
            i.setFixedWidth(30)
            grid.addWidget(i, 0, 0, 2, 1, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(QLabel(title, objectName="SettingTitle"), 0, 1)
            grid.addWidget(QLabel(text, objectName="Muted", wordWrap=True), 1, 1)
            rows.append(row)
        return self._page(self._heading(f"Welcome to AniGUI{holiday}",
                                        "Anime on your Mac, the way you like it. A quick hello before you start:")
                          + rows)

    def _yours(self) -> QWidget:
        self.name = QLineEdit(str(self.ctx.pref("your_name") or ""), placeholderText="Your name (optional)",
                              objectName="TagBox")
        self.name.setFixedWidth(260)
        swatches = QWidget()
        row = QHBoxLayout(swatches)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.accents = QButtonGroup(swatches)
        current = str(self.ctx.pref("accent"))
        for key, name, hexcolor in theme.ACCENTS:
            b = QPushButton(objectName="Swatch", checkable=True, cursor=Qt.CursorShape.PointingHandCursor)
            b.setFixedSize(32, 32)
            b.setToolTip(name)
            b.setProperty("accent", key)
            b.setStyleSheet(f"QPushButton#Swatch {{ background: {hexcolor}; border-radius: 16px; "
                            f"border: 2px solid transparent; }} QPushButton#Swatch:checked {{ border: 2px solid #FFFFFF; }}")
            b.setChecked(key == current)
            b.clicked.connect(lambda _c=False, k=key: self.ctx.set_pref("accent", k))
            self.accents.addButton(b)
            row.addWidget(b)
        row.addStretch(1)
        note = ("The holiday theme's red and green take over in December; your color comes back after."
                if theme.HOLIDAY else "You can change these any time in Settings → Make it yours.")
        return self._page(self._heading("Make it yours", "Home says hello with your name, and AniGUI wears your color.")
                          + [QLabel("Name", objectName="SettingTitle"), self.name,
                             QLabel("Color", objectName="SettingTitle"), swatches,
                             QLabel(note, objectName="Muted", wordWrap=True)])

    def _import(self) -> QWidget:
        self.user = QLineEdit(placeholderText="AniList username", objectName="TagBox")
        self.user.setFixedWidth(220)
        go = QPushButton("Import", cursor=Qt.CursorShape.PointingHandCursor)
        go.clicked.connect(self._import_anilist)
        self.user.returnPressed.connect(go.click)
        anilist = QWidget()
        r = QHBoxLayout(anilist)
        r.setContentsMargins(0, 0, 0, 0)
        r.setSpacing(8)
        r.addWidget(self.user)
        r.addWidget(go)
        r.addStretch(1)
        mal = QPushButton("Choose MyAnimeList export file…", cursor=Qt.CursorShape.PointingHandCursor)
        mal.clicked.connect(self._import_mal)
        mal_row = QWidget()
        m = QHBoxLayout(mal_row)
        m.setContentsMargins(0, 0, 0, 0)
        m.addWidget(mal)
        m.addStretch(1)
        return self._page(self._heading("Bring your list", "Watched anime somewhere else? Bring your shows, "
                                        "scores and progress along. It's read once; nothing is ever written back.")
                          + [QLabel("From AniList (your public list, no sign-in)", objectName="SettingTitle"), anilist,
                             QLabel("From MyAnimeList (your profile → Export)", objectName="SettingTitle"), mal_row,
                             QLabel("Starting fresh? Just press Next.", objectName="Muted")])

    def _keys(self) -> QWidget:
        box = QWidget(objectName="WelcomeRow")
        grid = QGridLayout(box)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        for i, (key, what) in enumerate(KEYS):
            k = QLabel(key, objectName="WelcomeKey", alignment=Qt.AlignmentFlag.AlignCenter)
            k.setMinimumWidth(56)
            grid.addWidget(k, i % 4, (i // 4) * 2)
            grid.addWidget(QLabel(what, objectName="Muted"), i % 4, (i // 4) * 2 + 1)
        return self._page(self._heading("A few keys worth knowing", "While an episode plays:") + [
            box, QLabel("Right-click an episode to download it for watching with no internet, or mark it watched.",
                        objectName="Muted", wordWrap=True)])

    # -- moving ---------------------------------------------------------------------------------

    def go(self, index: int) -> None:
        index = max(0, min(self.pages.count() - 1, index))
        self.pages.setCurrentIndex(index)
        last = index == self.pages.count() - 1
        self.back.setVisible(index > 0)
        self.skip.setVisible(not last)
        self.next.setText("Start watching" if last else "Next")
        for i, d in enumerate(self._dots):
            d.setProperty("on", i == index)
            d.style().unpolish(d)
            d.style().polish(d)

    def _save_name(self) -> None:
        name = self.name.text().strip()
        if name != str(self.ctx.pref("your_name") or ""):
            self.ctx.set_pref("your_name", name)

    def _next(self) -> None:
        if self.pages.currentIndex() == 1:
            self._save_name()
        if self.pages.currentIndex() == self.pages.count() - 1:
            self.finish()
        else:
            self.go(self.pages.currentIndex() + 1)

    def _import_anilist(self) -> None:
        user = self.user.text().strip()
        if user:
            self.importAniList.emit(user)
            self.go(3)

    def _import_mal(self) -> None:
        self.importMal.emit()
        self.go(3)

    def finish(self) -> None:
        self._save_name()
        self.ctx.set_pref("welcomed", True)
        self.accept()

    def reject(self) -> None:          # Esc or the close button: same as Skip
        self.ctx.set_pref("welcomed", True)
        super().reject()
