"""The show page's Content line: tags with a hover card (rating meter + what it means)
and an ⓘ that opens the explainer panel underneath. Matches the v1.8 concept."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.maturity import NUDITY_18, SEXUAL_VIOLENCE_18, Maturity, level

from . import theme

METER_COLORS = {"Nudity": theme.MATURE, "Sexual violence": theme.MATURE, "Sexual themes": "#E9B44C"}
METER_DEFAULT = "#8A8F9C"


@dataclass(frozen=True)
class NoteCard:
    title: str            # "Nudity · 88 / 100"
    rank: int | None      # for the meter; None: no meter (e.g. Ecchi genre)
    color: str
    text: str             # what it means, one or two sentences


def note_card(m: Maturity, note: str) -> NoteCard:
    tags = m.source(note)
    color = METER_COLORS.get(note, METER_DEFAULT)
    if not tags:
        if note == "Sexual themes":
            return NoteCard(note, None, color, "Fan service: AniList lists this show as Ecchi. On its own this "
                                               "doesn't make a show 18+.")
        return NoteCard(note, None, color, "")
    name, rank = tags[0]
    said = level(rank) + "."
    if note == "Nudity":
        text = f"{said} {NUDITY_18}+ is what makes a show 18+."
    elif note == "Sexual violence":
        text = f"{said} {SEXUAL_VIOLENCE_18}+ makes a show 18+."
    elif note == "Sexual themes":
        text = (f"Fan service: {', '.join(f'{n} ({r})' for n, r in tags[:3])}. "
                "On its own this doesn't make a show 18+.")
    elif note == "Gore":
        source = "" if (len(tags) == 1 and name == "Gore") else f" From {', '.join(f'{n} ({r})' for n, r in tags)}."
        text = f"{said}{source} Violence never makes a show 18+ by itself."
    else:   # Disturbing themes
        text = f"{said} From {', '.join(f'{n} ({r})' for n, r in tags)}."
    return NoteCard(f"{note} · {rank} / 100", rank, color, text)


class Meter(QWidget):
    """A thin rounded bar filled to rank / 100."""

    def __init__(self, rank: int, color: str, parent=None) -> None:
        super().__init__(parent)
        self.rank, self.color = rank, color
        self.setFixedHeight(5)

    def sizeHint(self) -> QSize:
        return QSize(220, 5)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2E2E3C"))
        p.drawRoundedRect(r, 2.5, 2.5)
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(QRectF(r.left(), r.top(), r.width() * max(0, min(100, self.rank)) / 100, r.height()), 2.5, 2.5)
        p.end()


class NoteHoverCard(QFrame):
    """The card that appears under a Content tag while the mouse is over it."""

    def __init__(self, card: NoteCard, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("NoteCard")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        title = QLabel(card.title, objectName="NoteCardTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        col = QVBoxLayout(self)
        col.setContentsMargins(12, 10, 12, 11)
        col.setSpacing(7)
        col.addWidget(title)
        if card.rank is not None:
            col.addWidget(Meter(card.rank, card.color))
        if card.text:
            text = QLabel(card.text, wordWrap=True, objectName="NoteCardText")
            text.setTextFormat(Qt.TextFormat.PlainText)
            col.addWidget(text)
        self.setFixedWidth(270)


class ContentTag(QLabel):
    """One Content tag ("Nudity"). Hovering shows its NoteHoverCard."""

    def __init__(self, note: str, card: NoteCard, parent=None) -> None:
        super().__init__(note, parent)
        self.setObjectName("ContentPill")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.card = card
        self.hover: NoteHoverCard | None = None
        self._delay = QTimer(self, singleShot=True, interval=120)
        self._delay.timeout.connect(self.show_card)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def enterEvent(self, event) -> None:
        self._delay.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._delay.stop()
        self.hide_card()
        super().leaveEvent(event)

    def show_card(self) -> None:
        if self.hover is None:
            self.hover = NoteHoverCard(self.card, self)
        self.hover.adjustSize()
        self.hover.move(self.mapToGlobal(QPoint(0, self.height() + 8)))
        self.hover.show()

    def hide_card(self) -> None:
        if self.hover is not None:
            self.hover.hide()

    def hideEvent(self, event) -> None:
        self.hide_card()
        super().hideEvent(event)


class Explainer(QFrame):
    """'What these tags mean': where the ratings come from, the 0-100 scale, and 18+."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Explainer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        title = QLabel("What these tags mean", objectName="ExplainerTitle")
        intro = QLabel("They come from AniList, where fans tag shows and vote on <b>how big a part of the "
                       "show</b> each tag is, from 0 to 100. It's about how much of the show it is, not how "
                       "explicit one scene gets.", wordWrap=True, objectName="ExplainerText")
        intro.setTextFormat(Qt.TextFormat.RichText)   # our own text only
        scale = QGridLayout()
        scale.setSpacing(6)
        for i, (span, words) in enumerate((("0–40", "minor"), ("40–60", "noticeable"),
                                           ("60–80", "a regular part"), ("80–100", "what it's known for"))):
            box = QLabel(f"<b>{span}</b><br><span style='color:{theme.MUTED}'>{words}</span>", objectName="ScaleBox")
            box.setTextFormat(Qt.TextFormat.RichText)
            scale.addWidget(box, 0, i)
            scale.setColumnStretch(i, 1)
        badge = QLabel("18+", objectName="MatureBadge")
        rule = QLabel(f"means nudity rated <b>{NUDITY_18}+</b> or sexual violence rated <b>{SEXUAL_VIOLENCE_18}+</b>, "
                      "or AniList marks the show adult. Gore and other themes are listed but never make a show 18+ "
                      "alone. Tags under 60 aren't listed, and spoiler tags never are.", wordWrap=True,
                      objectName="ExplainerText")
        rule.setTextFormat(Qt.TextFormat.RichText)
        rule_row = QHBoxLayout()
        rule_row.setSpacing(8)
        rule_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        rule_row.addWidget(rule, 1)
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 14, 16, 14)
        col.setSpacing(9)
        col.addWidget(title)
        col.addWidget(intro)
        col.addLayout(scale)
        col.addLayout(rule_row)
        self.setMaximumWidth(720)


class ContentLine(QWidget):
    """'Content: [Nudity] [Sexual themes] [Gore] (i)' plus the explainer under it."""

    toggled = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.label = QLabel("Content:", objectName="ContentLabel")
        self.tags_row = QHBoxLayout()
        self.tags_row.setSpacing(6)
        self.info = QPushButton("i", objectName="InfoButton", cursor=Qt.CursorShape.PointingHandCursor,
                                checkable=True)
        self.info.setToolTip("What do these mean?")
        self.info.toggled.connect(self._toggle)
        self.explainer = Explainer()
        self.explainer.setVisible(False)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.label)
        row.addLayout(self.tags_row)
        row.addWidget(self.info)
        row.addStretch(1)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        col.addLayout(row)
        col.addWidget(self.explainer)
        self.tags: list[ContentTag] = []

    def set_maturity(self, m: Maturity | None) -> None:
        for tag in self.tags:
            tag.hide_card()
            tag.deleteLater()
        self.tags = []
        for note in (m.notes if m else ()):
            tag = ContentTag(note, note_card(m, note))
            self.tags_row.addWidget(tag)
            self.tags.append(tag)
        self.info.setChecked(False)
        self.setVisible(bool(self.tags))

    def _toggle(self, on: bool) -> None:
        self.explainer.setVisible(on)
        self.toggled.emit(on)
