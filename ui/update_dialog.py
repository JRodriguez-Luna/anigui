"""The Update Now window: progress while downloading and installing, then a restart."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from core import self_update

from .context import AppContext


class _Relay(QObject):
    """Carries progress from the worker thread to the window (queued across threads)."""
    progress = Signal(int, int)
    stage = Signal(str)


class UpdateDialog(QDialog):
    installed = Signal(object)      # Path of the new app: time to restart
    failed = Signal(str)            # readable message; the caller offers the download page

    def __init__(self, ctx: AppContext, update, app: Path, parent=None) -> None:
        super().__init__(parent)
        self.ctx, self.update, self.app = ctx, update, app
        self._cancel = False
        self.setWindowTitle("Updating AniGUI")
        self.setObjectName("UpdateDialog")
        self.setModal(True)
        self.setFixedWidth(460)

        title = QLabel(f"Updating to AniGUI {update.latest}", objectName="DialogTitle")
        self.stage = QLabel("Starting…", objectName="Muted")
        self.bar = QProgressBar(objectName="UpdateBar", textVisible=False)
        self.bar.setRange(0, 0)
        self.detail = QLabel("", objectName="Muted")
        self.cancel_btn = QPushButton("Cancel", cursor=Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._on_cancel)
        buttons = QHBoxLayout()
        buttons.addWidget(self.detail, 1)
        buttons.addWidget(self.cancel_btn)

        col = QVBoxLayout(self)
        col.setContentsMargins(26, 24, 26, 22)
        col.setSpacing(12)
        col.addWidget(title)
        col.addWidget(self.stage)
        col.addWidget(self.bar)
        col.addLayout(buttons)

        self.relay = _Relay(self)
        self.relay.progress.connect(self._on_progress)
        self.relay.stage.connect(self._on_stage)

    def start(self) -> None:
        self.show()
        self.ctx.runner.submit(
            self_update.download_and_install, self.update, self.app,
            self.relay.progress.emit, lambda: self._cancel, self.relay.stage.emit,
            on_done=self._on_done, on_error=self._on_error,
        )

    def _on_stage(self, text: str) -> None:
        self.stage.setText(text)
        if not text.startswith("Downloading"):
            self.bar.setRange(0, 0)       # busy indicator
            self.detail.setText("")
        if text == "Installing…":
            self.cancel_btn.setEnabled(False)  # past the point of no return (it's quick)

    def _on_progress(self, done: int, total: int) -> None:
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done * 1000 / total))
            self.detail.setText(f"{done / 1048576:.1f} of {total / 1048576:.1f} MB")
        else:
            self.detail.setText(f"{done / 1048576:.1f} MB")

    def _on_cancel(self) -> None:
        self._cancel = True
        self.cancel_btn.setEnabled(False)
        self.stage.setText("Cancelling…")

    def _on_done(self, app: Path) -> None:
        self.stage.setText("Installed. Restarting AniGUI…")
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.installed.emit(app)

    def _on_error(self, message: str) -> None:
        self.reject()
        if not self._cancel:
            self.failed.emit(message)
