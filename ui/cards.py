"""Poster cards: model, painter, horizontal rows and wrapping grids."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from PySide6.QtCore import (
    QAbstractListModel, QEasingCurve, QModelIndex, QPersistentModelIndex, QPropertyAnimation,
    QPoint, QRectF, QSize, Qt, Signal,
)
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListView, QPushButton, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QVBoxLayout, QWidget,
)

from . import theme
from .images import ImageLoader

CARD_ROLE = Qt.ItemDataRole.UserRole + 1
SKELETON = "__skeleton__"


@dataclass(frozen=True)
class Card:
    key: str
    title: str
    subtitle: str = ""
    cover: str | None = None
    color: str | None = None        # AniList's dominant cover color, used while loading
    progress: float | None = None   # 0..1 bar along the bottom of the poster
    badge: str | None = None        # e.g. "★ 89" or "EP 4"
    payload: Any = None             # Media, SearchResult, Show... whatever the page needs

    @property
    def is_skeleton(self) -> bool:
        return self.key.startswith(SKELETON)


class CardModel(QAbstractListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cards: list[Card] = []

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._cards)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        card = self._cards[index.row()]
        if role == CARD_ROLE:
            return card
        if role == Qt.ItemDataRole.DisplayRole:
            return card.title
        if role == Qt.ItemDataRole.ToolTipRole and not card.is_skeleton:
            return card.title
        return None

    def cards(self) -> list[Card]:
        return list(self._cards)

    def set_cards(self, cards: list[Card]) -> None:
        self.beginResetModel()
        self._cards = list(cards)
        self.endResetModel()

    def set_loading(self, count: int = 8) -> None:
        self.set_cards([Card(f"{SKELETON}{i}", "") for i in range(count)])

    def is_loading(self) -> bool:
        return bool(self._cards) and self._cards[0].is_skeleton

    def update_card(self, key: str, **changes: Any) -> None:
        for row, card in enumerate(self._cards):
            if card.key == key:
                self._cards[row] = replace(card, **changes)
                idx = self.index(row)
                self.dataChanged.emit(idx, idx)
                return


class CardDelegate(QStyledItemDelegate):
    W, H = 150, 225          # 2:3 poster
    TEXT_H = 46

    def __init__(self, images: ImageLoader, parent=None) -> None:
        super().__init__(parent)
        self.images = images
        self.title_font = theme.font(13, QFont.Weight.DemiBold)
        self.sub_font = theme.font(12)
        self.badge_font = theme.font(11, QFont.Weight.Bold)

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(self.W, self.H + self.TEXT_H)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index) -> None:
        card: Card = index.data(CARD_ROLE)
        if card is None:
            return
        r = option.rect
        poster = QRectF(r.x(), r.y(), self.W, self.H)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver) and not card.is_skeleton

        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(poster, theme.RADIUS, theme.RADIUS)
        p.setClipPath(clip)

        pm = None if card.is_skeleton else self.images.pixmap(card.cover, self.W, self.H)
        if pm is not None:
            p.drawPixmap(poster.toRect(), pm)
        else:
            self._placeholder(p, poster, card)

        if hover:
            p.fillRect(poster, QColor(255, 255, 255, 16))
        if card.badge:
            self._badge(p, poster, card.badge)
        if card.progress is not None:
            bar = QRectF(poster.left(), poster.bottom() - 4, poster.width(), 4)
            p.fillRect(bar, QColor(255, 255, 255, 70))
            p.fillRect(QRectF(bar.left(), bar.top(), bar.width() * max(0.0, min(1.0, card.progress)), 4),
                       QColor(theme.ACCENT))
        p.setClipping(False)

        if hover:
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(poster.adjusted(1, 1, -1, -1), theme.RADIUS, theme.RADIUS)

        text_top = poster.bottom() + 8
        if card.is_skeleton:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.SURFACE_2))
            p.drawRoundedRect(QRectF(r.x(), text_top + 2, self.W * 0.8, 10), 4, 4)
            p.drawRoundedRect(QRectF(r.x(), text_top + 20, self.W * 0.5, 9), 4, 4)
        else:
            p.setFont(self.title_font)
            p.setPen(QColor(theme.TEXT if not hover else "#FFFFFF"))
            title = p.fontMetrics().elidedText(card.title, Qt.TextElideMode.ElideRight, self.W)
            p.drawText(QRectF(r.x(), text_top, self.W, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
            if card.subtitle:
                p.setFont(self.sub_font)
                p.setPen(QColor(theme.MUTED))
                sub = p.fontMetrics().elidedText(card.subtitle, Qt.TextElideMode.ElideRight, self.W)
                p.drawText(QRectF(r.x(), text_top + 19, self.W, 17), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sub)
        p.restore()

    def _placeholder(self, p: QPainter, rect: QRectF, card: Card) -> None:
        base = QColor(card.color) if card.color else QColor(theme.SURFACE_2)
        if card.is_skeleton:
            p.fillRect(rect, QColor(theme.SURFACE))
            return
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0, base.darker(140))
        grad.setColorAt(1, QColor(theme.SURFACE))
        p.fillRect(rect, grad)
        p.setPen(QColor(255, 255, 255, 150))
        p.setFont(self.title_font)
        p.drawText(rect.adjusted(12, 12, -12, -12),
                   Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, card.title)

    def _badge(self, p: QPainter, poster: QRectF, text: str) -> None:
        p.setFont(self.badge_font)
        w = p.fontMetrics().horizontalAdvance(text) + 14
        pill = QRectF(poster.left() + 8, poster.top() + 8, w, 20)
        p.setPen(Qt.PenStyle.NoPen)
        # "NEW…" badges use the accent color so new episodes stand out
        p.setBrush(QColor(theme.ACCENT) if text.startswith("NEW") else QColor(10, 10, 15, 190))
        p.drawRoundedRect(pill, 10, 10)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)


class CardView(QListView):
    """Shared setup for rows and grids. Emits the Card that was clicked."""

    cardActivated = Signal(object)
    cardMenuRequested = Signal(object, QPoint)   # Card, global position (right-click)

    def __init__(self, images: ImageLoader, parent=None) -> None:
        super().__init__(parent)
        self.model_ = CardModel(self)
        self.delegate = CardDelegate(images, self)
        self.setModel(self.model_)
        self.setItemDelegate(self.delegate)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clicked.connect(self._on_click)
        images.loaded.connect(lambda _url: self.viewport().update())

    def _on_click(self, index) -> None:
        card: Card = index.data(CARD_ROLE)
        if card and not card.is_skeleton:
            self.cardActivated.emit(card)

    def contextMenuEvent(self, event) -> None:
        card = self.indexAt(event.pos()).data(CARD_ROLE)
        if card and not card.is_skeleton:
            self.cardMenuRequested.emit(card, event.globalPos())

    @property
    def cards(self) -> CardModel:
        return self.model_


class CardRow(QWidget):
    """Section title plus a single horizontally scrolling line of cards."""

    cardActivated = Signal(object)
    cardMenuRequested = Signal(object, QPoint)
    SPACING = 14

    def __init__(self, title: str, images: ImageLoader, parent=None) -> None:
        super().__init__(parent)
        self.title = QLabel(title, objectName="SectionTitle")
        self.count = QLabel("", objectName="SectionCount")
        self.left = QPushButton("‹", objectName="Arrow", cursor=Qt.CursorShape.PointingHandCursor)
        self.right = QPushButton("›", objectName="Arrow", cursor=Qt.CursorShape.PointingHandCursor)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.title)
        header.addWidget(self.count)
        self.header = header
        header.addStretch(1)
        header.addWidget(self.left)
        header.addWidget(self.right)

        self.view = _RowView(images, self)
        self.view.setFlow(QListView.Flow.LeftToRight)
        self.view.setWrapping(False)
        self.view.setSpacing(self.SPACING // 2)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setFixedHeight(CardDelegate.H + CardDelegate.TEXT_H + self.SPACING + 2)
        self.view.cardActivated.connect(self.cardActivated)
        self.view.cardMenuRequested.connect(self.cardMenuRequested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.view)

        self._anim = QPropertyAnimation(self.view.horizontalScrollBar(), b"value", self)
        self._anim.setDuration(380)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.left.clicked.connect(lambda: self._page(-1))
        self.right.clicked.connect(lambda: self._page(1))
        self.view.horizontalScrollBar().rangeChanged.connect(lambda *_: self._update_arrows())
        self.view.horizontalScrollBar().valueChanged.connect(lambda *_: self._update_arrows())

    def set_cards(self, cards: list[Card], hide_when_empty: bool = True) -> None:
        self.view.cards.set_cards(cards)
        self.count.setText(str(len(cards)) if cards else "")
        self.setVisible(bool(cards) or not hide_when_empty)
        self.view.horizontalScrollBar().setValue(0)
        self._update_arrows()

    def add_action(self, text: str, tooltip: str = "") -> QPushButton:
        """A small text button next to the section title (e.g. "Clear")."""
        button = QPushButton(text, objectName="RowAction", cursor=Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tooltip)
        self.header.insertWidget(2, button, 0, Qt.AlignmentFlag.AlignVCenter)
        return button

    def set_loading(self) -> None:
        self.view.cards.set_loading()
        self.count.setText("")
        self.setVisible(True)

    def model(self) -> CardModel:
        return self.view.cards

    def _page(self, direction: int) -> None:
        bar = self.view.horizontalScrollBar()
        step = int(self.view.viewport().width() * 0.85)
        target = max(bar.minimum(), min(bar.maximum(), bar.value() + direction * step))
        self._anim.stop()
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.start()

    def _update_arrows(self) -> None:
        bar = self.view.horizontalScrollBar()
        self.left.setEnabled(bar.value() > bar.minimum())
        self.right.setEnabled(bar.value() < bar.maximum())
        scrollable = bar.maximum() > 0
        self.left.setVisible(scrollable)
        self.right.setVisible(scrollable)


class _RowView(CardView):
    def wheelEvent(self, event) -> None:
        delta = event.angleDelta()
        if abs(delta.y()) > abs(delta.x()):
            event.ignore()  # vertical scrolling belongs to the page, not the row
            return
        super().wheelEvent(event)


class CardGrid(CardView):
    """Wrapping grid that scrolls vertically (search results, My List)."""

    def __init__(self, images: ImageLoader, parent=None) -> None:
        super().__init__(images, parent)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setSpacing(10)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


FORMAT_LABELS = {
    "TV": "TV", "TV_SHORT": "TV Short", "MOVIE": "Movie", "SPECIAL": "Special",
    "OVA": "OVA", "ONA": "ONA", "MUSIC": "Music",
}


def format_label(fmt: str | None) -> str | None:
    return FORMAT_LABELS.get(fmt or "", fmt.title() if fmt else None)


def media_card(media) -> Card:
    """Card for an AniList Media."""
    bits = [b for b in (format_label(media.format),
                        f"{media.episodes} eps" if media.episodes and media.format != "MOVIE" else None,
                        str(media.year) if media.year else None) if b]
    return Card(
        key=f"anilist:{media.anilist_id}",
        title=media.display_title,
        subtitle=" · ".join(bits),
        cover=media.cover,
        color=media.cover_color,
        badge=f"★ {media.score}" if media.score else None,
        payload=media,
    )
