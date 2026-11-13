"""2.0.1: everyday performance. Decorations hold still while an episode plays (or you're in
another app), full screen stops repainting what's under it, and picture caches have a memory
budget."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_step4 import pump, win  # noqa: E402,F401
from test_v1110 import play_inside  # noqa: E402


def test_decorations_hold_still_while_an_episode_plays(win, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from ui import motion
    from ui.holiday import SnowLayer
    monkeypatch.setattr(motion, "_reduce", False)
    host = QWidget()
    host.resize(600, 400)
    host.show()
    snow = SnowLayer(host, flakes=20)
    snow.start()
    assert snow._timer.isActive()
    mpv = play_inside(win)
    mpv.set_prop("pause", False)
    assert pump(lambda: motion.quiet())
    snow._step()                                   # its next frame: parked, no wake-ups at all
    assert not snow._timer.isActive()
    mpv.set_prop("pause", True)                    # paused: no video frames, so it may move again
    assert pump(lambda: not motion.quiet() and snow._timer.isActive())
    mpv.set_prop("pause", False)
    assert pump(lambda: motion.quiet())
    win.player_host.close_player()
    assert pump(lambda: not motion.quiet())
    host.close()


def test_lights_and_the_spotlight_wait_too(win, monkeypatch):
    from ui import motion
    from ui.festive import SidebarLights
    from ui.theater import Lights
    monkeypatch.setattr(motion, "_reduce", False)
    motion.set_quiet("video", True)
    try:
        for w in (SidebarLights(win), Lights(win)):
            w.show()
            w._timer.start()
            t = w.t
            w._step()
            assert w.t == t and not w._timer.isActive()
        hero = win.home.hero
        if len(hero.items) > 1:
            cur = hero.current
            hero._rotate()
            assert hero.current == cur
    finally:
        motion.set_quiet("video", False)


def test_another_app_or_minimized_counts_as_away(win):
    from PySide6.QtCore import QEvent, Qt
    from ui import motion
    win._app_state(Qt.ApplicationState.ApplicationInactive)
    assert motion.quiet()
    win._app_state(Qt.ApplicationState.ApplicationActive)
    assert not motion.quiet()
    win.showMinimized()
    win.changeEvent(QEvent(QEvent.Type.WindowStateChange))
    assert motion.quiet() or not win.isMinimized()       # (some test screens can't minimize)
    win.showNormal()
    win.changeEvent(QEvent(QEvent.Type.WindowStateChange))
    assert not motion.quiet()


def test_full_screen_stops_repainting_whats_under_it(win):
    play_inside(win)
    host = win.player_host
    host.set_mode("full")
    covered = [w for w in host.home.children() if hasattr(w, "updatesEnabled") and w is not host
               and not w.isWindow()]
    assert covered and all(not w.updatesEnabled() for w in covered)
    assert host.updatesEnabled()
    host.set_mode("theater")
    assert all(w.updatesEnabled() for w in covered)
    host.set_mode("full")
    host.close_player()                               # stopping in full screen gives them back too
    assert pump(lambda: all(w.updatesEnabled() for w in covered))


def test_picture_caches_have_a_memory_budget():
    from PySide6.QtGui import QPixmap
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter
    from ui.images import ImageLoader
    from ui.paintcache import PaintCache
    loader = ImageLoader(covers=None, max_bytes=10 * 1024 * 1024)
    big = QPixmap(1000, 1000)                          # 4 MB each
    for i in range(6):
        loader._put((f"u{i}", 1000, 1000), big)
    assert loader.bytes <= 10 * 1024 * 1024 and len(loader._cache) == 2
    assert ("u5", 1000, 1000) in loader._cache        # the newest stay
    loader._put(("u5", 1000, 1000), big)              # replacing one doesn't count it twice
    assert loader.bytes == 2 * 4_000_000
    cache = PaintCache(max_bytes=3 * 1024 * 1024)
    target = QPixmap(10, 10)
    p = QPainter(target)
    for i in range(5):
        cache.draw(p, QRectF(0, 0, 500, 500), ("card", i), lambda q, r: True)   # 1 MB each
    p.end()
    assert len(cache) == 3 and cache.bytes <= 3 * 1024 * 1024


def test_a_mac_asks_for_modern_opengl_for_the_whole_app():
    """mpv needs OpenGL 3+ to take VideoToolbox's frames straight from the graphics chip;
    asked for once, before Qt starts, so the window and the video match."""
    import subprocess
    code = (
        "import sys; sys.path.insert(0, '.'); sys.platform = 'darwin'\n"
        "import main\n"
        "from PySide6.QtGui import QSurfaceFormat\n"
        "print(main.use_modern_opengl())\n"
        "f = QSurfaceFormat.defaultFormat(); print(f.majorVersion(), f.minorVersion(), f.profile().name)\n"
        "import os; os.environ['ANIGUI_GL'] = 'legacy'; print(main.use_modern_opengl())\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.stdout.split() == ["True", "4", "1", "CoreProfile", "False"], out.stderr[-500:]
    import main
    if sys.platform != "darwin":
        assert main.use_modern_opengl() is False


def test_the_log_says_how_video_is_decoded(win, caplog):
    import logging
    from ui.player_view import VideoView

    class FakeMpv:
        handle = 1

        def get(self, name):
            return {"hwdec-current": "videotoolbox", "video-params/w": "1920"}.get(name)

    view = VideoView.__new__(VideoView)
    view.mpv = FakeMpv()
    view.context = lambda: None
    with caplog.at_level(logging.INFO):
        VideoView._log_decoding(view)
    assert "decoding=videotoolbox" in caplog.text
