"""Settings window (⌘,): playback, skipping, new-episode alerts, history, connection, updates."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from core import __version__

from .context import AppContext
from .detail_page import QUALITIES

PLAYERS = [("Auto (IINA, then mpv)", "auto"), ("IINA", "iina"), ("mpv", "mpv")]
AUDIO = [("Sub (original audio, subtitles)", False), ("Dub (English audio)", True)]
SCOPES = [("My List", "library"), ("My List and Continue Watching", "library+continue")]
VPN_LABELS = {"warp": "Cloudflare WARP", "own": "Your own VPN", "none": "No VPN"}


class SettingRow(QWidget):
    """Title and explanation on the left, a control on the right."""

    def __init__(self, title: str, detail: str, control: QWidget | None, parent=None) -> None:
        super().__init__(parent, objectName="SettingRow")
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = QLabel(title, objectName="SettingTitle")
        text.addWidget(self.title)
        self.detail = QLabel(detail, objectName="Muted", wordWrap=True)
        self.detail.setVisible(bool(detail))
        text.addWidget(self.detail)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(16)
        row.addLayout(text, 1)
        if control is not None:
            row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)


class SettingsDialog(QDialog):
    """Every control writes straight to the preferences; there's no Save button."""

    clearHistoryRequested = Signal()
    setupRequested = Signal()
    checkUpdatesRequested = Signal()
    checkEpisodesRequested = Signal()
    whatsNewRequested = Signal()

    SECTIONS = ("Playback", "Skipping", "New Episodes", "History", "Connection", "Updates")

    def __init__(self, ctx: AppContext, parent=None, section: str | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Settings")
        self.setObjectName("SettingsDialog")
        self.setFixedSize(820, 560)
        self.controls: dict[str, QWidget] = {}

        self.nav = QListWidget(objectName="SettingsNav")
        self.nav.setFixedWidth(190)
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pages = QStackedWidget()
        for name, build in zip(self.SECTIONS, (self._playback, self._skipping, self._episodes,
                                               self._history, self._connection, self._updates)):
            self.nav.addItem(QListWidgetItem(name))
            self.pages.addWidget(self._page(name, build()))
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(self.SECTIONS.index(section) if section in self.SECTIONS else 0)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.nav)
        row.addWidget(self.pages, 1)

        ctx.events.changed.connect(self._pref_changed)

    def show_section(self, name: str) -> None:
        self.nav.setCurrentRow(self.SECTIONS.index(name))

    # -- building blocks ----------------------------------------------------------------

    def _page(self, title: str, rows: list[QWidget]) -> QWidget:
        body = QWidget(objectName="SettingsPage")
        col = QVBoxLayout(body)
        col.setContentsMargins(28, 24, 28, 24)
        col.setSpacing(12)
        col.addWidget(QLabel(title, objectName="DialogTitle"))
        group = QFrame(objectName="SettingsGroup")
        group_col = QVBoxLayout(group)
        group_col.setContentsMargins(0, 4, 0, 4)
        group_col.setSpacing(0)
        for i, row in enumerate(rows):
            if isinstance(row, QLabel):  # a note under the group
                continue
            if i:
                group_col.addWidget(QFrame(objectName="SettingsDivider", frameShape=QFrame.Shape.HLine))
            group_col.addWidget(row)
        col.addWidget(group)
        for note in (r for r in rows if isinstance(r, QLabel)):
            col.addWidget(note)
        col.addStretch(1)
        scroll = QScrollArea(objectName="SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        return scroll

    def _check(self, key: str) -> QCheckBox:
        box = QCheckBox(cursor=Qt.CursorShape.PointingHandCursor)
        box.setChecked(bool(self.ctx.pref(key)))
        box.toggled.connect(lambda on, k=key: self.ctx.set_pref(k, on))
        self.controls[key] = box
        return box

    def _choice(self, key: str, options: list[tuple[str, Any]]) -> QComboBox:
        combo = QComboBox(cursor=Qt.CursorShape.PointingHandCursor)
        combo.setFixedWidth(250)
        for label, value in options:
            combo.addItem(label, value)
        self._select(combo, self.ctx.pref(key))
        combo.currentIndexChanged.connect(lambda _i, k=key, c=combo: self.ctx.set_pref(k, c.currentData()))
        self.controls[key] = combo
        return combo

    @staticmethod
    def _select(combo: QComboBox, value: Any) -> None:
        for i in range(combo.count()):
            if str(combo.itemData(i)).lower() == str(value).lower():
                combo.setCurrentIndex(i)
                return

    @staticmethod
    def _button(text: str, slot: Callable[[], None], primary: bool = False) -> QPushButton:
        btn = QPushButton(text, objectName="Primary" if primary else "", cursor=Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn

    @staticmethod
    def _note(text: str) -> QLabel:
        label = QLabel(text, objectName="SettingsNote", wordWrap=True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        label.setOpenExternalLinks(True)
        return label

    # -- sections -----------------------------------------------------------------------

    def _playback(self) -> list[QWidget]:
        return [
            SettingRow("Player", "Which app plays episodes. If it isn't installed, the other one is used.",
                       self._choice("player", PLAYERS)),
            SettingRow("Audio", "Episodes without a dub play subbed.", self._choice("dub", AUDIO)),
            SettingRow("Quality", "Falls back to the best available if this one isn't offered.",
                       self._choice("quality", QUALITIES)),
            SettingRow("Auto-play next episode", "Counts down at the end of an episode, then plays the next one.",
                       self._check("autoplay")),
        ]

    def _skipping(self) -> list[QWidget]:
        return [
            SettingRow("Skip intros", "Jumps past the opening song.", self._check("skip_intro")),
            SettingRow("Skip endings", "Jumps past the ending credits; with auto-play on, the next episode starts sooner.",
                       self._check("skip_ending")),
            SettingRow("Skip recaps", "Jumps past \"previously on\" recaps.", self._check("skip_recap")),
            self._note("Skip times come from <a href='https://aniskip.com' style='color:#FF8559'>AniSkip</a>, "
                       "a community database. Episodes nobody has timed yet play normally. "
                       "Works with IINA and mpv; nothing extra to install."),
        ]

    def _episodes(self) -> list[QWidget]:
        self.episodes_status = QLabel("", objectName="Muted")
        check = self._button("Check Now", self.checkEpisodesRequested.emit)
        self.check_episodes_btn = check
        return [
            SettingRow("Look for new episodes", "Checks airing shows when AniGUI opens and every hour while it's open.",
                       self._check("alerts")),
            SettingRow("Shows to watch", "", self._choice("alerts_scope", SCOPES)),
            SettingRow("Mac notifications", "Shows a notification when a new episode is out. "
                       "New episodes always appear at the top of Home.", self._check("notify")),
            SettingRow("Check now", "", check),
            self._note("An episode counts as out once it's on hianime, which can be a few hours after it airs "
                       "in Japan. Dubs usually come later."),
        ]

    def _history(self) -> list[QWidget]:
        return [
            SettingRow("Clear watch history", "Empties Continue Watching and removes resume points and watched "
                       "marks. My List stays.", self._button("Clear History…", self.clearHistoryRequested.emit)),
            SettingRow("Include Terminal history", "Also shows what you watch with ani-cli in Terminal.",
                       self._check("import_history")),
        ]

    def _connection(self) -> list[QWidget]:
        self.vpn_label = QLabel("", objectName="Muted")
        self._update_vpn_label()
        return [
            SettingRow("Setup & connection", "Checks ani-cli, your video player and whether hianime is reachable "
                       "on this network.", self._button("Open Setup…", self.setupRequested.emit)),
            SettingRow("VPN", "Your choice from Setup. Change it there.", self.vpn_label),
        ]

    def _updates(self) -> list[QWidget]:
        self.versions = QLabel(f"AniGUI {__version__}", objectName="Muted")
        return [
            SettingRow("Check for updates automatically", "Looks for new versions of AniGUI and ani-cli once a day.",
                       self._check("check_updates")),
            SettingRow("Check now", "", self._button("Check for Updates", self.checkUpdatesRequested.emit)),
            SettingRow("What's new", "See what changed in each version.",
                       self._button("What's New", self.whatsNewRequested.emit)),
            SettingRow("Version", "", self.versions),
        ]

    # -- live updates -------------------------------------------------------------------

    def set_versions(self, ani_cli: str | None) -> None:
        self.versions.setText(f"AniGUI {__version__}" + (f"  ·  ani-cli {ani_cli}" if ani_cli else ""))

    def set_episodes_status(self, text: str, busy: bool = False) -> None:
        self.check_episodes_btn.setEnabled(not busy)
        rows = self.pages.widget(self.SECTIONS.index("New Episodes")).widget().findChildren(SettingRow)
        rows[-1].detail.setText(text)
        rows[-1].detail.setVisible(bool(text))

    def _update_vpn_label(self) -> None:
        self.vpn_label.setText(VPN_LABELS.get(str(self.ctx.pref("vpn_choice", "")), "Not needed so far"))

    def _pref_changed(self, key: str, value) -> None:
        control = self.controls.get(key)
        if isinstance(control, QCheckBox):
            control.blockSignals(True)
            control.setChecked(bool(self.ctx.pref(key)))
            control.blockSignals(False)
        elif isinstance(control, QComboBox):
            control.blockSignals(True)
            self._select(control, self.ctx.pref(key))
            control.blockSignals(False)
        elif key == "vpn_choice":
            self._update_vpn_label()
