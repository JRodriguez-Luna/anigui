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


def test_the_log_says_how_video_is_decoded(win, capsys):
    from ui.player_view import VideoView

    class FakeMpv:
        handle = 1

        def get(self, name):
            return {"hwdec-current": "videotoolbox", "video-params/w": "1920", "video-params/h": "1080"}.get(name)

    view = VideoView.__new__(VideoView)
    view.mpv = FakeMpv()
    view.context = lambda: None
    VideoView._log_decoding(view)                     # (AniGUI's log is its output, in the .app)
    assert "video: decoding=videotoolbox opengl=? size=1920x1080" in capsys.readouterr().out


# -- choosing a player, measured on this Mac -------------------------------------------------

class FakeProbe:
    """A player that plays at normal speed and uses `pct` % of a core."""

    def __init__(self, pct, clock):
        self.pct, self.clock, self.t0 = pct, clock, clock()
        self.closed = False

    def position(self):
        return 60 + (self.clock() - self.t0)

    def height(self):
        return 1080

    def cpu(self):
        return (self.clock() - self.t0) * self.pct / 100

    def close(self):
        self.closed = True


class FakeResolver:
    def __init__(self):
        self.asked = []

    def prepare(self, anime_id, title, episode, on_ready, on_fail, on_status=None, online=False):
        from core.ani_cli import StreamInfo
        self.asked.append((anime_id, episode))
        on_ready(StreamInfo(url="https://x.example/v.m3u8", referrer=None, title=title))
        return object()

    def cancel(self, _job):
        pass


def _fast(monkeypatch):
    """Measuring takes seconds of (fake) time, not minutes of real time."""
    import time as _time
    from ui import player_choice
    t = {"now": 1000.0}
    monkeypatch.setattr(player_choice, "MEASURE_S", 3)
    monkeypatch.setattr(player_choice, "SETTLE_S", 0.5)
    monkeypatch.setattr(player_choice.time, "monotonic", lambda: t["now"])
    monkeypatch.setattr(player_choice.Measurer, "POLL_MS", 5)

    def clock():
        return t["now"]

    def advance():
        t["now"] += 0.25
    return clock, advance


def test_settings_shows_the_two_players_side_by_side(win):
    dlg = win.open_settings("Playback")
    ch = dlg.player_choice
    ch.pick("iina")
    assert win.ctx.pref("player") == "iina"
    assert ch.cards["iina"].property("selected") and not ch.cards["anigui"].property("selected")
    assert dlg.controls["player"].currentData() == ""                  # "Other players: Don't use"
    other = dlg.controls["player"]
    other.setCurrentIndex(other.findData("mpv"))
    assert win.ctx.pref("player") == "mpv" and not any(c.property("selected") for c in ch.cards.values())
    other.setCurrentIndex(other.findData(""))                          # back to the AniGUI player
    assert win.ctx.pref("player") == "anigui" and ch.cards["anigui"].property("selected")
    assert ch.measure_box.isVisible() and ch.cards["anigui"].value.text() == "—"
    dlg.close()


def test_measuring_plays_each_player_and_keeps_the_numbers(win, monkeypatch):
    from ui import player_choice
    from ui.player_choice import Measured, Measurer
    clock, advance = _fast(monkeypatch)
    monkeypatch.setattr(player_choice, "find_player", lambda name=None: ("iina", "/x/iina-cli"))
    monkeypatch.setattr(player_choice.sharper, "available", lambda: True)
    use = {"anigui": 31.0, "sharper": 42.0, "iina": 8.0}
    made = []

    def make_probe(self, kind):
        made.append(kind)
        return FakeProbe(use[kind], clock)
    monkeypatch.setattr(Measurer, "make_probe", make_probe)
    resolver = FakeResolver()
    from ui.player_choice import PlayerChooser
    ch = PlayerChooser(win.ctx, {}, resolver)
    done = []
    ch.measurer.finished.connect(done.append)
    ch.measure()
    assert ch.stop_btn.isVisible() or not ch.isVisible()
    for _ in range(2000):
        advance()
        pump(lambda: False, 0.002)
        if done:
            break
    assert done and made == ["anigui", "sharper", "iina"]
    m = done[0]
    assert abs(m.anigui - 31) < 2 and abs(m.sharper - 42) < 2 and abs(m.iina - 8) < 2 and m.height == 1080
    assert resolver.asked and resolver.asked[0][0] == win.ctx.store.continue_watching(1)[0].show.anime_id
    saved = Measured.load(win.ctx)                                     # kept in AniGUI's settings
    assert saved.iina == m.iina and saved.what.endswith(f"episode {resolver.asked[0][1]}")
    assert ch.cards["anigui"].value.text() == "31%" and ch.cards["iina"].value.text() == "8%"
    assert ch.cards["iina"].tag.text() == "ABOUT A QUARTER THE WORK"
    assert "Sharper picture on: 42%" in ch.cards["anigui"].extra.text()
    assert "Measured today on this Mac" in ch.footnote.text() and "1080p" in ch.footnote.text()
    win.ctx.set_pref("player_measure", "")


def test_measuring_says_why_it_couldnt(win, monkeypatch):
    from ui import player_choice
    from ui.player_choice import Measurer
    clock, advance = _fast(monkeypatch)
    monkeypatch.setattr(player_choice, "find_player", lambda name=None: ("iina", "/x/iina-cli"))
    monkeypatch.setattr(player_choice.sharper, "available", lambda: False)

    def make_probe(self, kind):
        if kind == "iina":
            raise RuntimeError("IINA is already open. Quit IINA, then measure again.")
        return FakeProbe(30, clock)
    monkeypatch.setattr(Measurer, "make_probe", make_probe)
    m = Measurer(win.ctx, FakeResolver())
    done, failed = [], []
    m.finished.connect(done.append)
    m.failed.connect(failed.append)
    m.start()
    for _ in range(2000):
        advance()
        pump(lambda: False, 0.002)
        if done:
            break
    assert done and done[0].iina is None and any("already open" in n for n in m.notes)
    busy = Measurer(win.ctx, FakeResolver(), busy=lambda: True)
    busy.failed.connect(failed.append)
    assert not busy.start() and "Stop the episode" in failed[-1]
    win.ctx.set_pref("player_measure", "")


def test_share_words_and_cpu_helpers():
    from core import cpu
    from ui.player_choice import share_words
    assert share_words(8 / 31) == "about a quarter" and share_words(0.5) == "about half"
    assert share_words(0.95) is None and share_words(None) is None
    assert cpu.parse_cputime("1:02.50") == 62.5 and cpu.parse_cputime("1:00:00.00") == 3600
    assert cpu.parse_cputime("2-01:00:00") == 2 * 86400 + 3600 and cpu.parse_cputime("nope") is None
    assert cpu.percent(10, 12, 10) == 20 and cpu.own_cpu_seconds() > 0
    import os
    assert cpu.cpu_seconds(os.getpid()) > 0
    if sys.platform != "darwin":
        assert cpu.on_battery() is False


def test_battery_hint_once_in_the_built_in_player(win, monkeypatch):
    from ui import player_choice
    monkeypatch.setattr(player_choice, "find_player", lambda name=None: ("iina", "/x/iina-cli"))
    monkeypatch.setattr(player_choice.cpu, "on_battery", lambda: True)
    win.ctx.set_pref("battery_hint_done", False)
    mpv = play_inside(win)
    mpv.set_prop("pause", False)
    host = win.player_host
    assert pump(lambda: host._battery_check.isActive())
    host._maybe_battery_hint()
    hint = host.battery_hint
    assert hint.isVisible() and "much less power" in hint.text.text()
    assert win.ctx.pref("battery_hint_done") is True
    hint.use_iina.click()
    assert win.ctx.pref("player") == "iina" and not hint.isVisible()
    win.ctx.set_pref("player", "anigui")
    hint.hide()
    host._maybe_battery_hint()                         # once, ever
    assert not hint.isVisible()
    monkeypatch.setattr(player_choice.cpu, "on_battery", lambda: False)
    win.ctx.set_pref("battery_hint_done", False)
    host._maybe_battery_hint()                         # plugged in: nothing
    assert not hint.isVisible()
