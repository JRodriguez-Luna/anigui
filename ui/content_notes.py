"""The show page's Content line: tags with a hover card (rating meter + what it means)
and an ⓘ that opens the explainer panel underneath. Matches the v1.8 concept."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.maturity import NUDITY_18, SEXUAL_VIOLENCE_18, Maturity, level

from . import theme

METER_COLORS = {"Nudity": theme.MATURE, "Sexual violence": theme.MATURE, "Sexual themes": "#E9B44C"}
METER_DEFAULT = "#8A8F9C"


BELOW_LINE = "#E9B44C"   # amber: listed, but not enough for 18+


@dataclass(frozen=True)
class NoteCard:
    title: str            # "Nudity · 88 / 100"
    rank: int | None      # for the meter; None: no meter (e.g. Ecchi genre)
    color: str
    text: str             # what it means, one or two sentences
    line: int | None = None   # where 18+ starts on the meter (Nudity 70, sexual violence 60)


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
    if note in ("Nudity", "Sexual violence"):
        line = NUDITY_18 if note == "Nudity" else SEXUAL_VIOLENCE_18
        if rank >= line:
            text = f"{said} Past the 18+ line ({line}), so it's marked 18+."
            return NoteCard(f"{note} · {rank} / 100", rank, theme.MATURE, text, line)
        text = f"{level(rank)}, but below the 18+ line ({line}). Listed so you know, not hidden."
        return NoteCard(f"{note} · {rank} / 100", rank, BELOW_LINE, text, line)
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
    """A thin rounded bar filled to rank / 100, with an optional white mark where 18+
    starts and '0 · 18+ at 70 · 100' underneath."""

    BAR = 6

    def __init__(self, rank: int, color: str, line: int | None = None, parent=None) -> None:
        super().__init__(parent)
        self.rank, self.color, self.line = rank, color, line
        self.font_ = theme.font(10)
        self.setFixedHeight(self.BAR + 8 + (16 if line else 0))

    def sizeHint(self) -> QSize:
        return QSize(240, self.height())

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        bar = QRectF(0, 4, w, self.BAR)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2E2E3C"))
        p.drawRoundedRect(bar, 3, 3)
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(QRectF(0, bar.top(), w * max(0, min(100, self.rank)) / 100, self.BAR), 3, 3)
        if self.line:
            x = w * self.line / 100
            p.setBrush(QColor(theme.TEXT))
            p.drawRoundedRect(QRectF(x - 1, 0, 2, self.BAR + 8), 1, 1)
            p.setFont(self.font_)
            p.setPen(QColor(theme.FAINT))
            y = QRectF(0, self.BAR + 10, w, 14)
            p.drawText(y, Qt.AlignmentFlag.AlignLeft, "0")
            p.drawText(y, Qt.AlignmentFlag.AlignRight, "100")
            label = f"18+ at {self.line}"
            lw = p.fontMetrics().horizontalAdvance(label)
            p.drawText(QRectF(max(14, min(w - lw - 24, x - lw / 2)), y.top(), lw + 2, 14), Qt.AlignmentFlag.AlignLeft, label)
        p.end()


class NoteHoverCard(QFrame):
    """The card that appears under a Content tag while the mouse is over it."""

    WIDTH = 270

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
            meter = Meter(card.rank, card.color, card.line)
            meter.setFixedWidth(self.WIDTH - 24)
            col.addWidget(meter)
        title.setFixedWidth(self.WIDTH - 24)
        self.text: QLabel | None = None
        if card.text:
            text = QLabel(card.text, wordWrap=True, objectName="NoteCardText")
            text.setTextFormat(Qt.TextFormat.PlainText)
            text.setFixedWidth(self.WIDTH - 24)
            col.addWidget(text)
            self.text = text
        self.setFixedWidth(self.WIDTH)

    def fit(self) -> None:
        """Size the card to its wrapped text. A tooltip-style window doesn't get Qt's
        height-for-width layout pass, and the stylesheet's font only applies once the
        label is polished, so measure after polishing and set the height outright."""
        self.ensurePolished()
        if self.text is not None:
            self.text.ensurePolished()
            w = self.WIDTH - 24
            needed = self.text.fontMetrics().boundingRect(0, 0, w, 10_000, Qt.TextFlag.TextWordWrap,
                                                          self.text.text()).height()
            self.text.setFixedHeight(max(needed, self.text.heightForWidth(w)) + 2)
        self.adjustSize()


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
        self.hover.fit()
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
                      "alone, and Nudity can be listed below 70 (hover it to see where it falls). Tags under 60 aren't "
                      "listed, and spoiler tags never are.", wordWrap=True,
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


class CappedWidth(QWidget):
    """Holds a panel that stops at `cap` pixels wide, at a fixed height: the height its text
    needs at the width it really gets, worked out again whenever that width changes.
    (Left to Qt, a wrapping panel with a maximum width is measured at the whole column's
    width, so in a wide window it got too little height and its last lines were cut off.)"""

    def __init__(self, child: QWidget, cap: int, parent=None) -> None:
        super().__init__(parent)
        self.child, self.cap = child, cap
        child.setParent(self)
        self._fit_timer = QTimer(self, singleShot=True, interval=0)
        self._fit_timer.timeout.connect(self.fit)

    def event(self, event) -> bool:
        # the panel changed inside (shown, fonts applied): measure again
        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Show, QEvent.Type.Polish):
            self._fit_timer.start()
        return super().event(event)

    def sizeHint(self) -> QSize:
        return QSize(min(self.child.sizeHint().width(), self.cap), self.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(min(self.child.minimumSizeHint().width(), self.cap), self.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.child.setGeometry(0, 0, min(self.width(), self.cap), self.height())
        if event.oldSize().width() != event.size().width():
            self._fit_timer.start()

    def fit(self) -> None:
        width = min(self.width(), self.cap)
        self.child.ensurePolished()
        need = self.child.heightForWidth(width)
        if need > 0 and need != self.minimumHeight():
            self.setFixedHeight(need)


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
        self.panel = CappedWidth(self.explainer, 720)
        self.panel.setVisible(False)
        col.addWidget(self.panel)
        self.tags: list[ContentTag] = []

    def set_maturity(self, m: Maturity | None) -> None:
        for tag in self.tags:
            tag.hide_card()
            tag.hide()
            self.tags_row.removeWidget(tag)   # gone now, not when the event loop gets to it
            tag.deleteLater()
        self.tags = []
        for note in (m.notes if m else ()):
            tag = ContentTag(note, note_card(m, note))
            self.tags_row.addWidget(tag)
            self.tags.append(tag)
        self.info.setChecked(False)
        self.setVisible(bool(self.tags))

    def _toggle(self, on: bool) -> None:
        self.panel.setVisible(on)
        self.explainer.setVisible(on)
        self.toggled.emit(on)
