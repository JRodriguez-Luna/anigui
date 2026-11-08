"""Small, quick animations: fades, short slides, hover lifts, loading shimmer.

Everything is either a snapshot of a widget faded over the live one (cheap: one pixmap)
or a painter reading an eased 0..1 value. Nothing animates for long, nothing blocks.

macOS's Reduce motion (System Settings > Accessibility > Display) is respected: slides,
lifts and shimmer are skipped, and only short fades remain (what Apple asks of apps).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

from PySide6.QtCore import (
    QEasingCurve, QObject, QParallelAnimationGroup, QPoint, QPropertyAnimation, Qt, QTimer, QVariantAnimation,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

PAGE_MS = 220
FADE_MS = 240
SLIDE_PX = 10
EASE = QEasingCurve.Type.OutCubic

_reduce: bool | None = None


def reduce_motion() -> bool:
    """macOS's Reduce motion setting (read once). ANIGUI_REDUCE_MOTION=1/0 overrides it."""
    global _reduce
    if _reduce is None:
        env = os.environ.get("ANIGUI_REDUCE_MOTION")
        if env is not None:
            _reduce = env == "1"
        elif sys.platform == "darwin":
            try:
                out = subprocess.run(["defaults", "read", "com.apple.universalaccess", "reduceMotion"],
                                     capture_output=True, text=True, timeout=2)
                _reduce = out.stdout.strip() == "1"
            except (OSError, subprocess.SubprocessError):
                _reduce = False
        else:
            _reduce = False
    return _reduce


def set_reduce_motion(value: bool | None) -> None:
    """Tests: force it (None: read the setting again)."""
    global _reduce
    _reduce = value


def ease(t: float) -> float:
    """Out-cubic, 0..1 -> 0..1."""
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def crossfade(widget: QWidget, slide_in: QWidget | None = None, ms: int = PAGE_MS) -> QLabel | None:
    """Fade a snapshot of `widget` (as it looks now) out over whatever it shows next.
    Call it right before changing the widget. `slide_in`: also slide this child up a few
    pixels into place (the page being shown). Returns the overlay (tests)."""
    if not widget.isVisible() or widget.width() <= 0 or widget.height() <= 0:
        return None
    shot = widget.grab()
    overlay = QLabel(widget)
    overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    overlay.setPixmap(shot)
    overlay.setGeometry(widget.rect())
    overlay.show()
    overlay.raise_()
    effect = QGraphicsOpacityEffect(overlay)
    effect.setOpacity(1.0)
    overlay.setGraphicsEffect(effect)
    group = QParallelAnimationGroup(overlay)
    fade = QPropertyAnimation(effect, b"opacity", group)
    fade.setDuration(ms if not reduce_motion() else min(ms, 160))
    fade.setStartValue(1.0)
    fade.setEndValue(0.0)
    fade.setEasingCurve(EASE)
    group.addAnimation(fade)
    if slide_in is not None and not reduce_motion():
        end = slide_in.pos()
        slide = QPropertyAnimation(slide_in, b"pos", group)
        slide.setDuration(ms)
        slide.setStartValue(end + QPoint(0, SLIDE_PX))
        slide.setEndValue(end)
        slide.setEasingCurve(EASE)
        group.addAnimation(slide)
    group.finished.connect(overlay.deleteLater)
    group.start()
    overlay.animation = group
    return overlay


def fade_in(widget: QWidget, ms: int = FADE_MS, rise: int = 0) -> None:
    """Show `widget` by fading it in (and rising `rise` px, unless Reduce motion)."""
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    widget.show()
    group = QParallelAnimationGroup(widget)
    fade = QPropertyAnimation(effect, b"opacity", group)
    fade.setDuration(ms)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setEasingCurve(EASE)
    group.addAnimation(fade)
    if rise and not reduce_motion():
        end = widget.pos()
        move = QPropertyAnimation(widget, b"pos", group)
        move.setDuration(ms)
        move.setStartValue(end + QPoint(0, rise))
        move.setEndValue(end)
        move.setEasingCurve(EASE)
        group.addAnimation(move)
    # Drop the effect afterwards: a widget with an opacity effect paints through an
    # offscreen buffer, which is slower and can blur text.
    group.finished.connect(lambda: widget.setGraphicsEffect(None))
    group.start()
    widget._motion = group


def fade_out(widget: QWidget, ms: int = 200, drop: int = 0) -> None:
    """Fade `widget` out (sinking `drop` px), then hide it."""
    if not widget.isVisible():
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(1.0)
    widget.setGraphicsEffect(effect)
    group = QParallelAnimationGroup(widget)
    fade = QPropertyAnimation(effect, b"opacity", group)
    fade.setDuration(ms)
    fade.setStartValue(1.0)
    fade.setEndValue(0.0)
    group.addAnimation(fade)
    start = widget.pos()
    if drop and not reduce_motion():
        move = QPropertyAnimation(widget, b"pos", group)
        move.setDuration(ms)
        move.setStartValue(start)
        move.setEndValue(start + QPoint(0, drop))
        group.addAnimation(move)

    def done() -> None:
        widget.hide()
        widget.setGraphicsEffect(None)
        widget.move(start)

    group.finished.connect(done)
    group.start()
    widget._motion = group


def grow_height(widget: QWidget, height: int, ms: int = 200) -> None:
    """Open a panel by growing its height from 0 (instantly with Reduce motion)."""
    if reduce_motion():
        widget.setMaximumHeight(16777215)
        return
    anim = QPropertyAnimation(widget, b"maximumHeight", widget)
    anim.setDuration(ms)
    anim.setStartValue(0)
    anim.setEndValue(max(1, height))
    anim.setEasingCurve(EASE)
    anim.finished.connect(lambda: widget.setMaximumHeight(16777215))
    anim.start()
    widget._motion = anim


class Tween(QObject):
    """Values per key that ease toward a target (hover lifts). `value(key)` is 0..1; the
    callback runs on every frame while anything is moving."""

    def __init__(self, on_frame, ms: int = 140, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.on_frame, self.ms = on_frame, ms
        self._from: dict = {}
        self._to: dict = {}
        self._start: dict = {}
        self._timer = QTimer(self, interval=16)
        self._timer.timeout.connect(self._tick)

    def value(self, key) -> float:
        if key not in self._to:
            return 0.0
        t = (time.monotonic() - self._start[key]) * 1000 / self.ms
        a, b = self._from[key], self._to[key]
        return b if t >= 1 else a + (b - a) * ease(t)

    def set(self, key, target: float) -> None:
        if reduce_motion():
            target = 0.0                  # no lifts: the outline still shows hover
        if self._to.get(key) == target:
            return
        self._from[key] = self.value(key)
        self._to[key] = target
        self._start[key] = time.monotonic()
        if not self._timer.isActive():
            self._timer.start()

    def _tick(self) -> None:
        now = time.monotonic()
        moving = False
        for key in list(self._to):
            if (now - self._start[key]) * 1000 < self.ms:
                moving = True
            elif self._to[key] == 0.0:
                for d in (self._from, self._to, self._start):
                    d.pop(key, None)
        self.on_frame()
        if not moving:
            self._timer.stop()


_last_scroll = 0.0
SCROLL_QUIET_S = 0.25


def note_scroll() -> None:
    """A page is scrolling (decorations hold still until it stops, so scrolling gets the Mac's
    full attention: 2.0)."""
    global _last_scroll
    _last_scroll = time.monotonic()


def scrolling() -> bool:
    return time.monotonic() - _last_scroll < SCROLL_QUIET_S


def shimmer_phase() -> float:
    """0..1, looping every 1.2 s: where the loading highlight is."""
    return (time.monotonic() % 1.2) / 1.2


class Ticker(QObject):
    """Calls `on_frame` about 30 times a second while `running()` is true (shimmer)."""

    def __init__(self, on_frame, running, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.on_frame, self.running = on_frame, running
        self._timer = QTimer(self, interval=33)
        self._timer.timeout.connect(self._tick)

    def poke(self) -> None:
        if not reduce_motion() and self.running() and not self._timer.isActive():
            self._timer.start()

    def _tick(self) -> None:
        if not self.running():
            self._timer.stop()
        self.on_frame()


class Fader(QVariantAnimation):
    """A 0..1 value over `ms`, calling `on_frame(v)` each step (crossfades in painters)."""

    def __init__(self, on_frame, ms: int = FADE_MS, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setDuration(ms)
        self.setStartValue(0.0)
        self.setEndValue(1.0)
        self.setEasingCurve(EASE)
        self.valueChanged.connect(lambda v: on_frame(float(v)))
