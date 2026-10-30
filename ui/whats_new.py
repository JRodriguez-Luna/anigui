"""What's New: the changelog, newest first. Opens once after an update."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from core import __version__, changelog


class WhatsNewDialog(QDialog):
    def __init__(self, parent=None, since: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("What's New")
        self.setObjectName("WhatsNewDialog")
        self.setFixedSize(620, 600)

        newer = {r.version for r in changelog.since(since)} if since else set()
        heading = QLabel(f"What's new in AniGUI {__version__}", objectName="DialogTitle")
        self.subtitle = sub = QLabel(f"Updated from {since}." if since else "Everything that changed, newest first.",
                                     objectName="Muted")

        body = QWidget(objectName="SettingsPage")
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(18)
        self.release_boxes: list[QFrame] = []
        for release in changelog.RELEASES:
            col.addWidget(self._release(release, highlight=release.version in newer))
        col.addStretch(1)

        scroll = QScrollArea(objectName="SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)

        ok = QPushButton("Got It", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        ok.clicked.connect(self.accept)
        ok.setDefault(True)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(10)
        layout.addWidget(heading)
        layout.addWidget(sub)
        layout.addSpacing(8)
        layout.addWidget(scroll, 1)
        layout.addSpacing(6)
        layout.addLayout(buttons)

    def _release(self, release: changelog.Release, highlight: bool) -> QFrame:
        box = QFrame(objectName="ReleaseBox")
        box.setProperty("highlight", highlight)
        col = QVBoxLayout(box)
        col.setContentsMargins(18, 16, 18, 16)
        col.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(QLabel(f"Version {release.version}", objectName="ReleaseVersion"))
        if release.version == __version__:
            top.addWidget(QLabel("NEW", objectName="ReleaseTag"))
        top.addStretch(1)
        top.addWidget(QLabel(release.date, objectName="Muted"))
        col.addLayout(top)
        for change in release.changes:
            text = QLabel(f"<b>{change.title}</b><br>{change.text}", objectName="ReleaseItem", wordWrap=True)
            text.setTextFormat(Qt.TextFormat.RichText)
            col.addWidget(text)
        self.release_boxes.append(box)
        return box
