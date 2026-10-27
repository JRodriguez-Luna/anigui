#!/usr/bin/env python3
"""Render each page with offline fake data and save screenshots (used for the README).

    QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 python tools/ui_preview.py docs/screenshots

Shows and artwork are invented by tests/ui_fakes.py; no network access is needed.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.main_window import MainWindow  # noqa: E402
from ui.theme import apply_theme  # noqa: E402
from ui_fakes import fake_context  # noqa: E402


def pump(seconds: float, until=None) -> None:
    end = time.time() + seconds
    while time.time() < end:
        QCoreApplication.processEvents()
        if until and until():
            break
        time.sleep(0.01)


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "shots")
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    apply_theme(app)
    ctx = fake_context(Path(tempfile.mkdtemp(prefix="anigui-preview-")))
    win = MainWindow(ctx)
    win.resize(1320, 860)
    win.show()
    win.home.load_remote()
    win.home.refresh_local()
    pump(3.0)

    def shot(name: str) -> None:
        pump(0.8)
        path = out / f"{name}.png"
        win.grab().save(str(path))
        print(path)

    shot("home")
    win.home.verticalScrollBar().setValue(430)
    shot("home-rows")
    win.home.verticalScrollBar().setValue(0)

    # Show page with an episode playing and progress being tracked
    starfall = win.home.trending_row.model().cards()[0].payload
    win.open_item(starfall)
    pump(3.0, until=lambda: win.detail.grid.model_.items)
    win.detail.play("5")
    pump(3.0, until=lambda: win.playback.session is not None and win.playback.session.alive)
    mpv = ctx.player.mpv
    if mpv is not None:
        pump(1.0)
        mpv.set_prop("duration", 1440.0)
        mpv.set_prop("time-pos", 655.0)
        pump(1.0)
    win.toast.hide()
    shot("show")

    win.go(win.search)
    win.search.box.setText("academy courier tea moon")
    win.search._search()
    pump(1.5)
    shot("search")

    win.go(win.library)
    shot("my-list")
    ctx.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
