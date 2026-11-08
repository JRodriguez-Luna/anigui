"""Touch ID locks (2.0): AniGUI itself when it opens, 18+ shows, and any list you lock.

Unlocking lasts until AniGUI quits or you choose Lock Now. Without Touch ID, macOS asks for
your Mac's password instead; AniGUI never sees either, only whether it worked.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from core.touchid import TouchID

from . import theme


class Gate(QObject):
    """require(scope, reason, then): run `then` once this scope is unlocked (asking if needed)."""

    unlockedChanged = Signal()
    _answer = Signal(object, bool)        # (pending request, ok), from macOS's thread to ours

    def __init__(self, backend=None, parent=None) -> None:
        super().__init__(parent)
        self.backend = backend if backend is not None else TouchID()
        self.unlocked: set[str] = set()
        self._answer.connect(self._answered, Qt.ConnectionType.QueuedConnection)
        self.asking = False

    def available(self) -> bool:
        try:
            return bool(self.backend.available())
        except Exception:     # noqa: BLE001 (never let a lock check take the app down)
            return False

    def is_open(self, scope: str) -> bool:
        return scope in self.unlocked

    def require(self, scope: str, reason: str, then: Callable[[], None],
                otherwise: Callable[[], None] | None = None) -> None:
        if scope in self.unlocked:
            then()
            return
        if not self.available():
            # No way to ask on this Mac: don't lock you out of your own app
            self.unlocked.add(scope)
            then()
            return
        if self.asking:
            return
        self.asking = True
        request = (scope, then, otherwise)
        self.backend.ask(reason, lambda ok: self._answer.emit(request, ok))

    def _answered(self, request, ok: bool) -> None:
        self.asking = False
        scope, then, otherwise = request
        if ok:
            self.unlocked.add(scope)
            self.unlockedChanged.emit()
            then()
        elif otherwise is not None:
            otherwise()

    def lock_all(self) -> None:
        self.unlocked.clear()
        self.unlockedChanged.emit()


class LockScreen(QWidget):
    """Covers AniGUI until you unlock it."""

    unlockRequested = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("LockScreen")
        self.title = QLabel("AniGUI is locked", objectName="LockTitle", alignment=Qt.AlignmentFlag.AlignCenter)
        self.sub = QLabel("Use Touch ID or your Mac's password to open it.", objectName="LockSub",
                          alignment=Qt.AlignmentFlag.AlignCenter)
        self.button = QPushButton("Unlock", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        self.button.setFixedWidth(180)
        self.button.clicked.connect(self.unlockRequested)
        col = QVBoxLayout(self)
        col.addStretch(1)
        col.addSpacing(120)
        col.addWidget(self.title)
        col.addWidget(self.sub)
        col.addSpacing(14)
        col.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addStretch(1)
        parent.installEventFilter(self)
        self.hide()

    def cover(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.button.setFocus()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parentWidget() and event.type() == event.Type.Resize and self.isVisible():
            self.setGeometry(obj.rect())
        return False

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.BG))
        c = self.rect().center()
        # a padlock
        body = QRectF(c.x() - 30, c.y() - 96, 60, 46)
        shackle = QPainterPath()
        shackle.moveTo(body.left() + 12, body.top())
        shackle.lineTo(body.left() + 12, body.top() - 14)
        shackle.arcTo(QRectF(body.left() + 12, body.top() - 32, 36, 36), 180, -180)
        shackle.lineTo(body.right() - 12, body.top())
        p.setPen(QPen(QColor(theme.MUTED), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(shackle)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2E8B57") if theme.HOLIDAY else QColor(theme.ACCENT))     # a green present
        p.drawRoundedRect(body, 10, 10)
        if theme.HOLIDAY:                       # a little bow on the lock
            p.setBrush(QColor("#E0403C"))
            p.drawRect(QRectF(body.center().x() - 4, body.top(), 8, body.height()))
            p.drawEllipse(QRectF(body.center().x() - 16, body.top() + 4, 14, 10))
            p.drawEllipse(QRectF(body.center().x() + 2, body.top() + 4, 14, 10))
            p.setBrush(QColor("#B52E2B"))
            p.drawEllipse(QRectF(body.center().x() - 4, body.top() + 6, 8, 8))
        else:
            p.setBrush(QColor(255, 255, 255, 200))
            p.drawEllipse(QRectF(body.center().x() - 5, body.center().y() - 6, 10, 10))
