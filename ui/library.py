"""My Library (2.0): your lists in the sidebar, and your rating, tags and note on a show page.

Everything here lives in AniGUI's database on this Mac. Nothing is sent anywhere.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
                               QPlainTextEdit, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from core.store import SAVED, ShowList, stars

from . import theme
from .icons import nav_icon


def list_label(sl: ShowList) -> str:
    return f"{sl.emoji}  {sl.name}" if sl.emoji else sl.name


# -- the sidebar ---------------------------------------------------------------------------------

class _SubNav(QPushButton):
    """One list under Library in the sidebar, with its count on the right."""

    def __init__(self, sl: ShowList) -> None:
        super().__init__(objectName="NavSub", checkable=True, cursor=Qt.CursorShape.PointingHandCursor)
        self.list_id = sl.list_id
        self.set_list(sl)

    def set_list(self, sl: ShowList) -> None:
        self.sl = sl
        self.setText(list_label(sl))
        self.setToolTip(f"{sl.name} · {sl.count} show{'s' if sl.count != 1 else ''}"
                        + (" · locked" if sl.locked else ""))
        self.update()

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(theme.FAINT))
        p.setFont(theme.font(11, QFont.Weight.DemiBold))
        right = QRectF(0, 0, self.width() - 10, self.height())
        p.drawText(right, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   ("🔒 " if self.sl.locked else "") + (str(self.sl.count) if self.sl.count else ""))


class LibraryNav(QWidget):
    """Library in the sidebar: the heading opens My Library; your lists sit under it, and
    the arrow folds them away."""

    openOverview = Signal()
    openList = Signal(int)
    newList = Signal()
    listMenu = Signal(int, QPoint)
    folded = Signal(bool)          # True: open

    def __init__(self, group: QButtonGroup, parent=None) -> None:
        super().__init__(parent)
        self.group = group
        self.header = QPushButton("  Library", objectName="NavButton", checkable=True,
                                  cursor=Qt.CursorShape.PointingHandCursor)
        self.header.setIcon(nav_icon("heart"))
        self.header.setIconSize(QSize(18, 18))
        self.header.clicked.connect(self.openOverview)
        self.header.toggled.connect(lambda on: on and self.openOverview.emit())
        group.addButton(self.header)
        self.chevron = QToolButton(self.header, objectName="NavChevron", cursor=Qt.CursorShape.PointingHandCursor)
        self.chevron.setToolTip("Show or hide your lists")
        self.chevron.clicked.connect(lambda: self.set_open(not self.is_open, emit=True))
        self.items = QVBoxLayout()
        self.items.setContentsMargins(0, 2, 0, 4)
        self.items.setSpacing(1)
        self.box = QWidget()
        self.box.setLayout(self.items)
        self.new_btn = QPushButton("+  New list", objectName="NavNew", cursor=Qt.CursorShape.PointingHandCursor)
        self.new_btn.clicked.connect(self.newList)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self.header)
        col.addWidget(self.box)
        self.items.addWidget(self.new_btn)
        self.subs: dict[int, _SubNav] = {}
        self.is_open = True
        self.set_open(True)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        h = self.header.height()
        self.chevron.setGeometry(self.header.width() - 30, (h - 24) // 2, 24, 24)

    def set_open(self, on: bool, emit: bool = False) -> None:
        self.is_open = on
        self.box.setVisible(on)
        self.chevron.setText("▾" if on else "▸")
        if emit:
            self.folded.emit(on)

    def set_lists(self, lists: list[ShowList]) -> None:
        ids = [sl.list_id for sl in lists]
        for lid in list(self.subs):
            if lid not in ids:
                btn = self.subs.pop(lid)
                self.group.removeButton(btn)
                btn.deleteLater()
        for i, sl in enumerate(lists):
            btn = self.subs.get(sl.list_id)
            if btn is None:
                btn = _SubNav(sl)
                btn.clicked.connect(lambda _c=False, lid=sl.list_id: self.openList.emit(lid))
                btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                btn.customContextMenuRequested.connect(
                    lambda pos, b=btn: self.listMenu.emit(b.list_id, b.mapToGlobal(pos)))
                self.group.addButton(btn)
                self.subs[sl.list_id] = btn
            else:
                btn.set_list(sl)
            self.items.removeWidget(btn)
            self.items.insertWidget(i, btn)

    def select(self, list_id: int | None) -> None:
        """Light up a list (or the Library heading, with None)."""
        btn = self.header if list_id is None else self.subs.get(list_id)
        if btn is not None:
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)
        if list_id is not None and not self.is_open:
            self.set_open(True, emit=True)


# -- on a show page ------------------------------------------------------------------------------

class StarRating(QWidget):
    """Five stars; click the left half of a star for a half. Click your rating again to clear it."""

    changed = Signal(object)        # 1..10, or None

    STAR = 22
    GAP = 4

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rating: int | None = None
        self.hover: int | None = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(5 * self.STAR + 4 * self.GAP, self.STAR + 2)
        self.setToolTip("Your rating (only you see it)")

    def set_rating(self, rating: int | None) -> None:
        self.rating = rating
        self.update()

    def _at(self, x: float) -> int:
        step = self.STAR + self.GAP
        i = int(max(0, min(4, x // step)))
        half = (x - i * step) < self.STAR / 2
        return i * 2 + (1 if half else 2)

    def mouseMoveEvent(self, e) -> None:
        self.hover = self._at(e.position().x())
        self.update()

    def leaveEvent(self, _e) -> None:
        self.hover = None
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        value = self._at(e.position().x())
        self.rating = None if value == self.rating else value
        self.update()
        self.changed.emit(self.rating)

    @staticmethod
    def _star(center: QPointF, r: float) -> QPainterPath:
        import math
        path = QPainterPath()
        for k in range(10):
            ang = -math.pi / 2 + k * math.pi / 5
            rad = r if k % 2 == 0 else r * 0.45
            pt = QPointF(center.x() + rad * math.cos(ang), center.y() + rad * math.sin(ang))
            path.moveTo(pt) if k == 0 else path.lineTo(pt)
        path.closeSubpath()
        return path

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shown = self.hover if self.hover is not None else (self.rating or 0)
        gold = QColor("#F5C04A") if self.hover is None else QColor("#F5C04A").lighter(115)
        empty = QColor(255, 255, 255, 50)
        for i in range(5):
            c = QPointF(i * (self.STAR + self.GAP) + self.STAR / 2, self.height() / 2)
            star = self._star(c, self.STAR / 2)
            p.fillPath(star, empty)
            filled = shown - i * 2
            if filled >= 2:
                p.fillPath(star, gold)
            elif filled == 1:
                p.save()
                p.setClipRect(QRectF(c.x() - self.STAR / 2, 0, self.STAR / 2, self.height()))
                p.fillPath(star, gold)
                p.restore()


class _Chip(QPushButton):
    def __init__(self, text: str) -> None:
        super().__init__(f"{text}  ×", objectName="TagChip", cursor=Qt.CursorShape.PointingHandCursor)
        self.tag = text
        self.setToolTip(f"Remove “{text}”")


class YourNotes(QFrame):
    """Yours: rating, tags and a private note for this show."""

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent, objectName="YoursPanel")
        self.store = store
        self.anime_id: str | None = None
        self._loading = False
        title = QLabel("Yours", objectName="YoursTitle")
        hint = QLabel("only on this Mac", objectName="YoursHint")
        self.stars = StarRating()
        self.stars.changed.connect(self._rated)
        self.rating_text = QLabel("", objectName="YoursHint")
        self.tags_row = QHBoxLayout()
        self.tags_row.setSpacing(6)
        self.tag_box = QLineEdit(objectName="TagBox", placeholderText="+ Add a tag")
        self.tag_box.setFixedWidth(120)
        self.tag_box.returnPressed.connect(self._add_tag)
        self.note = QPlainTextEdit(objectName="NoteBox")
        self.note.setPlaceholderText("A note for yourself: why you liked it, where you stopped, who recommended it…")
        self.note.setFixedHeight(58)
        self.note.textChanged.connect(lambda: self._loading or self._note_timer.start())
        self._note_timer = QTimer(self, singleShot=True, interval=600)      # saves as you type
        self._note_timer.timeout.connect(self._save_note)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(title)
        head.addWidget(hint)
        head.addStretch(1)
        rate = QHBoxLayout()
        rate.setSpacing(12)
        rate.addWidget(self.stars)
        rate.addWidget(self.rating_text)
        rate.addSpacing(18)
        rate.addLayout(self.tags_row)
        rate.addWidget(self.tag_box)
        rate.addStretch(1)
        col = QVBoxLayout(self)
        col.setContentsMargins(18, 14, 18, 14)
        col.setSpacing(10)
        col.addLayout(head)
        col.addLayout(rate)
        col.addWidget(self.note)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def load(self, anime_id: str | None, save: bool = True) -> None:
        """Show this show's rating, tags and note (saving the open note first, unless your
        data was just replaced underneath it)."""
        if save:
            self._save_note()
        else:
            self._note_timer.stop()
        self.anime_id = anime_id
        n = self.store.notes(anime_id) if anime_id else None
        self._loading = True
        self.stars.set_rating(n.rating if n else None)
        self._show_rating(n.rating if n else None)
        self._set_tags(n.tags if n else ())
        self.note.setPlainText(n.note if n else "")
        self._loading = False

    def _show_rating(self, rating) -> None:
        self.rating_text.setText(f"{rating / 2:g} / 5" if rating else "Rate it")

    def _rated(self, rating) -> None:
        if self.anime_id:
            self.store.set_rating(self.anime_id, rating)
        self._show_rating(rating)

    def _set_tags(self, tags) -> None:
        while self.tags_row.count():
            w = self.tags_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        for t in tags:
            chip = _Chip(t)
            chip.clicked.connect(lambda _c=False, tag=t: self._remove_tag(tag))
            self.tags_row.addWidget(chip)

    def _add_tag(self) -> None:
        text = self.tag_box.text().strip()
        if not text or not self.anime_id:
            return
        tags = list(self.store.notes(self.anime_id).tags) + [text]
        self.store.set_tags(self.anime_id, tags)
        self.tag_box.clear()
        self._set_tags(self.store.notes(self.anime_id).tags)

    def _remove_tag(self, tag: str) -> None:
        if not self.anime_id:
            return
        self.store.set_tags(self.anime_id, [t for t in self.store.notes(self.anime_id).tags if t != tag])
        self._set_tags(self.store.notes(self.anime_id).tags)

    def _save_note(self) -> None:
        self._note_timer.stop()
        if self.anime_id and not self._loading:
            text = self.note.toPlainText()
            if text.strip() != self.store.notes(self.anime_id).note:
                self.store.set_note(self.anime_id, text)


class ListsButton(QPushButton):
    """“Lists ▾”: put this show in any of your lists, or a new one."""

    changed = Signal()

    def __init__(self, store, parent=None) -> None:
        super().__init__("☰  Lists ▾", parent, objectName="Glass", cursor=Qt.CursorShape.PointingHandCursor)
        self.store = store
        self.anime_id: str | None = None
        self.setToolTip("Add to one of your lists")
        self.menu_ = QMenu(self)
        self.menu_.aboutToShow.connect(self._build)
        self.setMenu(self.menu_)

    def set_show(self, anime_id: str | None) -> None:
        self.anime_id = anime_id
        self._label()

    def _label(self) -> None:
        mine = self.store.lists_for(self.anime_id) - {SAVED} if self.anime_id else set()
        self.setText(f"☰  In {len(mine)} list{'s' if len(mine) != 1 else ''}" if mine else "☰  Lists")

    def _build(self) -> None:
        self.menu_.clear()
        if not self.anime_id:
            return
        mine = self.store.lists_for(self.anime_id)
        for sl in self.store.lists():
            if sl.list_id == SAVED:
                continue
            act = self.menu_.addAction(list_label(sl))
            act.setCheckable(True)
            act.setChecked(sl.list_id in mine)
            act.toggled.connect(lambda on, lid=sl.list_id: self._toggle(lid, on))
        if len(self.menu_.actions()):
            self.menu_.addSeparator()
        self.menu_.addAction("New list…").triggered.connect(self._new)

    def _toggle(self, list_id: int, on: bool) -> None:
        (self.store.add_to_list if on else self.store.remove_from_list)(list_id, self.anime_id)
        self._label()
        self.changed.emit()

    def _new(self) -> None:
        lid = ask_new_list(self.store, self.window())
        if lid is not None and self.anime_id:
            self.store.add_to_list(lid, self.anime_id)
            self._label()
            self.changed.emit()


def ask_new_list(store, parent) -> int | None:
    name, ok = QInputDialog.getText(parent, "New list", "Name your list (start with an emoji if you like):")
    name = name.strip()
    if not ok or not name:
        return None
    emoji = None
    first = name.split(" ", 1)
    if len(first) == 2 and first[0] and not first[0][0].isalnum() and len(first[0]) <= 3:
        emoji, name = first[0], first[1].strip()
    return store.create_list(name, emoji)


def stars_text(rating: int | None) -> str:
    return stars(rating)
