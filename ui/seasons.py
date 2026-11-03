"""The show page's Seasons row: every season of the series in order, with your progress,
plus the series' movies and specials, and an Up next card when a season is done."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from core.anilist import Media
from core.seasons import Season, Series

from . import theme
from .images import ImageLoader

UPCOMING = ("NOT_YET_RELEASED",)


@dataclass(frozen=True)
class SeasonState:
    watched: int = 0             # episodes finished
    total: int | None = None     # episodes in the season (AniList), if known
    current: bool = False        # the season this page is showing
    blur: bool = False           # 18+ while Hide 18+ shows is on

    @property
    def done(self) -> bool:
        return bool(self.total) and self.watched >= (self.total or 0)

    @property
    def fraction(self) -> float:
        return min(1.0, self.watched / self.total) if self.total else 0.0


def season_line(season: Season, state: SeasonState) -> str:
    m = season.media
    if (m.status or "") in UPCOMING:
        when = " ".join(b for b in ((m.season or "").title(), str(m.year) if m.year else "") if b)
        return f"Coming {when}".strip() if when else "Coming soon"
    if state.done:
        return "✓ Watched"
    if state.current:
        return f"You're here · {state.watched}/{state.total}" if state.watched and state.total else "You're here"
    if state.watched:
        return f"{state.watched}/{state.total} watched" if state.total else f"{state.watched} watched"
    return "Not started"


def season_sub(media: Media) -> str:
    bits = [str(media.year) if media.year else None,
            f"{media.episodes} eps" if media.episodes else None]
    return " · ".join(b for b in bits if b)


class SeasonCard(QWidget):
    """One season: picture, name, year and episodes, a progress bar, and where you are."""

    clicked = Signal(object)          # Media
    W, H, PIC_H = 150, 150, 74

    def __init__(self, season: Season, state: SeasonState, images: ImageLoader, parent=None) -> None:
        super().__init__(parent)
        self.season, self.state, self.images = season, state, images
        self.line = season_line(season, state)
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        m = season.media
        self.setToolTip(m.display_title)
        self.setAccessibleName(f"{season.label}, {self.line}")
        self.title_font = theme.font(13, QFont.Weight.DemiBold)
        self.small_font = theme.font(11)
        images.loaded.connect(self._on_loaded)

    @property
    def picture(self) -> str | None:
        return self.season.media.banner or self.season.media.cover

    def _on_loaded(self, url: str) -> None:
        if url == self.picture:
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.season.media)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = self.underMouse()
        card = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QColor(theme.ACCENT) if self.state.current else QColor("#3A3A4C" if hover else theme.BORDER))
        p.setBrush(QColor(theme.SURFACE_2))
        if self.state.current:
            pen = p.pen()
            pen.setWidthF(2)
            p.setPen(pen)
        p.drawRoundedRect(card, 10, 10)

        pic = QRectF(8, 8, self.W - 16, self.PIC_H)
        clip = QPainterPath()
        clip.addRoundedRect(pic, 6, 6)
        p.save()
        p.setClipPath(clip)
        load = self.images.blurred if self.state.blur else self.images.pixmap
        pm = load(self.picture, int(pic.width()), int(pic.height()))
        if pm is not None:
            p.drawPixmap(pic.toRect(), pm)
        else:
            p.fillRect(pic, QColor(self.season.media.cover_color or theme.SURFACE_3).darker(140))
        if (self.season.media.status or "") in UPCOMING:
            p.fillRect(pic, QColor(0, 0, 0, 110))
        p.restore()

        x, w = 10, self.W - 20
        p.setPen(QColor(theme.TEXT))
        p.setFont(self.title_font)
        name = p.fontMetrics().elidedText(self.season.label, Qt.TextElideMode.ElideRight, w)
        p.drawText(QRectF(x, pic.bottom() + 6, w, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        p.setFont(self.small_font)
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(x, pic.bottom() + 24, w, 15), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   season_sub(self.season.media))
        bar = QRectF(x, pic.bottom() + 43, w, 3)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.SURFACE_3))
        p.drawRoundedRect(bar, 1.5, 1.5)
        if self.state.fraction:
            p.setBrush(QColor(theme.GOOD if self.state.done else theme.ACCENT))
            p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * self.state.fraction, 3), 1.5, 1.5)
        color = theme.GOOD if self.state.done else (theme.ACCENT_HOVER if self.state.current else theme.MUTED)
        p.setPen(QColor(color))
        line = p.fontMetrics().elidedText(self.line, Qt.TextElideMode.ElideRight, w)
        p.drawText(QRectF(x, bar.bottom() + 4, w, 15), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
        p.end()


class _Strip(QScrollArea):
    """A row that scrolls sideways (trackpad or the ‹ › buttons), never vertically."""

    def __init__(self, height: int, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(height)
        self.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        inner = QWidget()
        self.row = QHBoxLayout(inner)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(10)
        self.row.addStretch(1)
        self.setWidget(inner)
        self._anim = QPropertyAnimation(self.horizontalScrollBar(), b"value", self)
        self._anim.setDuration(320)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def wheelEvent(self, event) -> None:
        d = event.angleDelta()
        if abs(d.x()) > abs(d.y()):
            super().wheelEvent(event)
        else:
            event.ignore()               # vertical scrolling belongs to the page

    def clear(self) -> None:
        while self.row.count() > 1:
            item = self.row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def add(self, widget: QWidget) -> None:
        self.row.insertWidget(self.row.count() - 1, widget)

    def page(self, direction: int) -> None:
        bar = self.horizontalScrollBar()
        self._anim.stop()
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(max(0, min(bar.maximum(), bar.value() + direction * int(self.viewport().width() * 0.8))))
        self._anim.start()


class SeasonsRow(QWidget):
    """'Seasons  7 seasons · 4 movies   ‹ ›', the cards, then 'Movies and specials:' pills."""

    openMedia = Signal(object)        # Media

    def __init__(self, images: ImageLoader, parent=None) -> None:
        super().__init__(parent)
        self.images = images
        self.series: Series | None = None
        self.cards: list[SeasonCard] = []
        self.title = QLabel("Seasons", objectName="SectionTitle")
        self.count = QLabel("", objectName="SectionCount")
        self.left = QPushButton("‹", objectName="Arrow", cursor=Qt.CursorShape.PointingHandCursor)
        self.right = QPushButton("›", objectName="Arrow", cursor=Qt.CursorShape.PointingHandCursor)
        self.left.setAccessibleName("Earlier seasons")
        self.right.setAccessibleName("Later seasons")
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(self.title)
        header.addWidget(self.count)
        header.addStretch(1)
        header.addWidget(self.left)
        header.addWidget(self.right)

        self.strip = _Strip(SeasonCard.H + 4)
        self.extras_label = QLabel("Movies and specials:", objectName="Muted")
        self.extras = _Strip(30)
        extras_row = QHBoxLayout()
        extras_row.setSpacing(10)
        extras_row.addWidget(self.extras_label)
        extras_row.addWidget(self.extras, 1)
        self.extras_box = QWidget()
        self.extras_box.setLayout(extras_row)
        extras_row.setContentsMargins(0, 0, 0, 0)

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        col.addLayout(header)
        col.addWidget(self.strip)
        col.addWidget(self.extras_box)
        self.left.clicked.connect(lambda: self.strip.page(-1))
        self.right.clicked.connect(lambda: self.strip.page(1))
        bar = self.strip.horizontalScrollBar()
        bar.rangeChanged.connect(lambda *_: self._arrows())
        bar.valueChanged.connect(lambda *_: self._arrows())
        self.setVisible(False)

    def _arrows(self) -> None:
        bar = self.strip.horizontalScrollBar()
        scrollable = bar.maximum() > 0
        self.left.setVisible(scrollable)
        self.right.setVisible(scrollable)
        self.left.setEnabled(bar.value() > 0)
        self.right.setEnabled(bar.value() < bar.maximum())

    def clear(self) -> None:
        self.series = None
        self.cards = []
        self.strip.clear()
        self.extras.clear()
        self.setVisible(False)

    def set_series(self, series: Series, states: dict[int, SeasonState], hidden_extras: set[int] = frozenset()) -> None:
        self.clear()
        if not series.worth_showing:
            return
        self.series = series
        for s in series.seasons:
            card = SeasonCard(s, states.get(s.media.anilist_id, SeasonState()), self.images)
            card.clicked.connect(self._open)
            self.strip.add(card)
            self.cards.append(card)
        extras = [m for m in series.extras if m.anilist_id not in hidden_extras]
        for m in extras:
            pill = QPushButton(_extra_label(m), objectName="ExtraPill", cursor=Qt.CursorShape.PointingHandCursor)
            pill.setToolTip(m.display_title)
            pill.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            pill.clicked.connect(lambda _c=False, media=m: self._open(media))
            self.extras.add(pill)
        self.extras_box.setVisible(bool(extras))
        n, k = len(series.seasons), len(extras)
        bits = [f"{n} season{'s' if n != 1 else ''}"] + ([f"{k} movie{'s' if k != 1 else ''} and specials"] if k else [])
        self.count.setText(" · ".join(bits))
        self.setVisible(True)
        current = next((c for c in self.cards if c.state.current), None)
        if current is not None:
            self.strip.ensureWidgetVisible(current, 40, 0)
        self._arrows()

    def _open(self, media: Media) -> None:
        if self.series and not any(c.state.current and c.season.media.anilist_id == media.anilist_id for c in self.cards):
            self.openMedia.emit(media)

    def sizeHint(self) -> QSize:
        return QSize(600, super().sizeHint().height())


def _extra_label(m: Media) -> str:
    kind = {"MOVIE": "", "OVA": "OVA · ", "SPECIAL": "Special · ", "ONA": "", "TV_SHORT": ""}.get(m.format or "", "")
    title = m.display_title if len(m.display_title) <= 34 else m.display_title[:32].rstrip() + "…"
    return f"{kind}{title}{f' · {m.year}' if m.year else ''}"


class UpNextCard(QFrame):
    """After the last episode of a season: 'Up next: Season 3   ▶ Start Season 3'."""

    start = Signal(object)            # Media

    def __init__(self, images: ImageLoader, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("UpNextCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.media: Media | None = None
        from .widgets import PosterWidget
        self.poster = PosterWidget(images, 46, 64)
        self.title = QLabel("", objectName="UpNextTitle")
        self.sub = QLabel("", objectName="Muted")
        self.button = QPushButton("", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(lambda: self.media is not None and self.start.emit(self.media))
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.title)
        text.addWidget(self.sub)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(14)
        row.addWidget(self.poster)
        row.addLayout(text, 1)
        row.addWidget(self.button)
        self.setVisible(False)

    def show_for(self, season: Season | None) -> None:
        self.media = season.media if season else None
        if season is None:
            self.setVisible(False)
            return
        m = season.media
        self.poster.set_cover(m.cover, m.cover_color, season.label)
        self.title.setText(f"Up next: {season.label}")
        self.sub.setText("  ·  ".join(b for b in (m.display_title, season_sub(m)) if b))
        self.button.setText(f"▶  Start {season.label}")
        self.setVisible(True)
