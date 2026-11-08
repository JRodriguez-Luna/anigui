"""v2.0 stage 1: Cinema look, the Full bleed watch page, the pop-out player, staying awake."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from core.power import KeepAwake  # noqa: E402
from test_step4 import STARFALL, fast, pump, win  # noqa: E402,F401
from test_v1110 import play_inside  # noqa: E402


class FakePower:
    def __init__(self):
        self.held, self.next_id = set(), 7

    def hold(self, reason):
        self.next_id += 1
        self.held.add(self.next_id)
        return self.next_id

    def let_go(self, ident):
        self.held.discard(ident)


def test_keep_awake_holds_once_and_lets_go():
    power = FakePower()
    k = KeepAwake(power)
    k.hold()
    k.hold()
    assert k.held and len(power.held) == 1
    k.release()
    k.release()
    assert not k.held and not power.held


def test_mac_stays_awake_only_while_playing(win):
    power = FakePower()
    win.player_host.awake = KeepAwake(power)
    mpv = play_inside(win)
    mpv.set_prop("pause", False)
    assert pump(lambda: win.player_host.awake.held)
    mpv.set_prop("pause", True)
    assert pump(lambda: not win.player_host.awake.held)
    mpv.set_prop("pause", False)
    assert pump(lambda: win.player_host.awake.held)
    win.player_host.close_player()
    assert pump(lambda: not win.player_host.awake.held and not power.held)


# -- the Full bleed watch page -------------------------------------------------------------------

def test_video_fits_the_window(win):
    play_inside(win)
    slot = win.detail.theater.slot
    slot.set_room(600)
    assert slot.heightForWidth(1600) == 600 - slot.RESERVE          # tall windows: capped so the title shows
    assert slot.heightForWidth(640) == 360                          # narrow: plain 16:9
    slot.set_room(100)
    assert slot.heightForWidth(1600) >= 220                         # never collapses


def test_back_lives_in_the_player(win):
    play_inside(win)
    assert pump(lambda: win.player_host.mode == "theater")
    win.player_host._action("back")
    assert pump(lambda: win.stack.currentWidget() is not win.detail)
    assert win.playback.session is not None and win.playback.session.alive   # keeps playing in the corner
    assert pump(lambda: win.player_host.mode == "mini")


def test_all_episodes_opens_the_drawer(win):
    play_inside(win)
    host = win.player_host
    assert pump(lambda: host.mode == "theater")
    assert not host.drawer.isVisible()
    win.detail.theater.all_btn.click()
    assert pump(lambda: host.drawer.isVisible())
    assert win.detail.theater.rail.parentWidget() is host.drawer
    host._action("list")
    assert pump(lambda: not host.drawer.isVisible())


def test_episode_strip_replaces_the_grid(win):
    play_inside(win)
    d = win.detail
    assert pump(lambda: d.theater.strip.model().rowCount() > 0)
    assert not d.episodes_box.isVisible()


def test_sticky_bar_takes_you_back_to_the_video(win):
    play_inside(win)
    d = win.detail
    win.resize(1100, 640)
    pump(lambda: False, 0.3)
    bar = d.verticalScrollBar()
    bar.setValue(bar.maximum())
    assert pump(lambda: d.sticky.isVisible())
    assert d.sticky.play.text() == "⤒  Back to the video"
    assert d.sticky.where.text().startswith("▶ Playing episode 5")
    d.sticky.play.click()
    assert pump(lambda: bar.value() == 0)
