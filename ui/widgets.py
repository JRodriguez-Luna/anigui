"""Small shared widgets: toast, poster image, empty-state label."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QLabel, QWidget

from . import theme
from .images import ImageLoader


class Toast(QLabel):
    """Bottom-center message that hides itself."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, objectName="Toast")
        self.setWordWrap(True)
        self.setMaximumWidth(560)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, error: bool = False, ms: int = 4500) -> None:
        self.setProperty("kind", "error" if error else "info")
        self.style().unpolish(self)
        self.style().polish(self)
        self.setText(text)
        self.setFixedWidth(min(560, self.fontMetrics().horizontalAdvance(text) + 48))
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._timer.start(ms + (2500 if error else 0))

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 28)


class PosterWidget(QWidget):
    """Rounded cover image with a soft shadow-free border."""

    def __init__(self, images: ImageLoader, w: int = 190, h: int = 285, parent=None) -> None:
        super().__init__(parent)
        self.images = images
        self.url: str | None = None
        self.color: str | None = None
        self.label = ""
        self.setFixedSize(w, h)
        images.loaded.connect(lambda url: url == self.url and self.update())

    def set_cover(self, url: str | None, color: str | None = None, label: str = "") -> None:
        self.url, self.color, self.label = url, color, label
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        p.setClipPath(path)
        pm = self.images.pixmap(self.url, self.width(), self.height())
        if pm is not None:
            p.drawPixmap(self.rect(), pm)
        else:
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0, QColor(self.color or theme.SURFACE_3).darker(130))
            grad.setColorAt(1, QColor(theme.SURFACE))
            p.fillRect(rect, grad)
            p.setPen(QColor(255, 255, 255, 140))
            p.setFont(theme.font(15, QFont.Weight.Bold))
            p.drawText(rect.adjusted(14, 14, -14, -14), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.label)
        p.setClipping(False)
        p.setPen(QColor(255, 255, 255, 30))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 10, 10)


def empty_state(text: str) -> QLabel:
    label = QLabel(text, objectName="EmptyState")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    return label
