"""A small frame-rate readout for checking smoothness on a real Mac (⌘⌥F shows or hides it).

A timer asks to run every frame (16 ms). When AniGUI is busy drawing, the timer runs late, so
how often it actually ran is how many frames a second AniGUI could keep up with, and its
longest wait is the worst stutter. Shown twice a second; nothing is measured while hidden.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QLabel, QWidget


class FrameMeter(QLabel):
    FRAME_MS = 16
    REPORT_S = 0.5

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("FrameMeter")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("QLabel#FrameMeter { background: rgba(0,0,0,0.72); color: #E8FFE8; "
                           "font: 600 12px 'Menlo', monospace; padding: 5px 9px; border-radius: 6px; }")
        self._tick = QTimer(self, interval=self.FRAME_MS)
        self._tick.setTimerType(Qt.TimerType.PreciseTimer)
        self._tick.timeout.connect(self._on_tick)
        self._last = 0.0
        self._window_start = 0.0
        self._frames = 0
        self._worst = 0.0
        self.fps = 0.0
        self.worst_ms = 0.0
        parent.installEventFilter(self)
        self.hide()

    def toggle(self) -> None:
        self.set_on(self.isHidden())

    def set_on(self, on: bool) -> None:
        if on:
            self._last = self._window_start = time.perf_counter()
            self._frames, self._worst = 0, 0.0
            self.setText("measuring…")
            self.adjustSize()
            self._place()
            self.show()
            self.raise_()
            self._tick.start()
        else:
            self._tick.stop()
            self.hide()

    def _on_tick(self) -> None:
        now = time.perf_counter()
        self._worst = max(self._worst, now - self._last)
        self._last = now
        self._frames += 1
        span = now - self._window_start
        if span >= self.REPORT_S:
            self.fps = self._frames / span
            self.worst_ms = self._worst * 1000
            self.setText(f"{self.fps:4.0f} fps · slowest frame {self.worst_ms:3.0f} ms")
            self.adjustSize()
            self._place()
            self._window_start, self._frames, self._worst = now, 0, 0.0

    def _place(self) -> None:
        p = self.parentWidget()
        self.move(p.width() - self.width() - 14, 10)
        self.raise_()

    def eventFilter(self, obj: QObject, event) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        return False
