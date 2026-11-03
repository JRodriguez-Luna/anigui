"""v1.11.0: the built-in player (video in AniGUI's own window), and Because you watched."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from core import aniskip  # noqa: E402
from core.ani_cli import StreamInfo  # noqa: E402
from core.player import PlayerError, embedded_options, embedded_tracks  # noqa: E402
from test_step4 import LANTERN, STARFALL, fast, pump, win  # noqa: E402,F401


def play_inside(w, anime_id=STARFALL, episode="5"):
    w.ctx.set_pref("player", "anigui")
    w.open_item(w.ctx.store.get_show(anime_id))
    assert pump(lambda: w.detail.grid.model_.items)
    w.detail.play(episode)
    assert pump(lambda: w.playback.session is not None and w.playback.session.alive, 8)
    mpv = w.ctx.player.mpv
    assert pump(lambda: len(mpv.named("observe_property")) >= 4)
    return mpv


# -- core ----------------------------------------------------------------------------------------

def test_embedded_options_match_the_mpv_command():
    info = StreamInfo(url="https://cdn.example/v.m3u8", referrer="https://ref.example/", title="x",
                      audio_url="https://cdn.example/a:b.m3u8", subtitle_url="https://cdn.example/s.vtt",
                      show_subtitles=False)
    opts, url = embedded_options(info, "Show · Episode 5", "/tmp/x.sock", 125.4)
    assert url == info.url and opts["vo"] == "libmpv" and opts["input-ipc-server"] == "/tmp/x.sock"
    assert opts["referrer"] == info.referrer and opts["start"] == "125" and opts["force-media-title"] == "Show · Episode 5"
    assert opts["idle"] == "yes" and opts["input-default-bindings"] == "no"
    # separate tracks are added by command after loading, so a ':' in a link stays whole
    assert embedded_tracks(info) == [("audio-add", info.audio_url, "select"), ("sub-add", info.subtitle_url, "auto")]
    with pytest.raises(PlayerError):
        embedded_options(StreamInfo(url="file:///etc/passwd", referrer=None, title=None), "t")


def test_libmpv_binding_if_installed():
    from core import libmpv
    try:
        libmpv.load()
    except libmpv.LibMpvError:
        pytest.skip("no libmpv here")
    import locale
    locale.setlocale(locale.LC_NUMERIC, "")          # what Qt does; mpv needs "C", and gets it
    m = libmpv.Mpv({"vo": "null", "ao": "null", "idle": "yes"})
    try:
        m.command("loadfile", "av://lavfi:testsrc=duration=1:size=64x48:rate=10")
        m.observe(1, "duration")
        import time
        end, seen = time.time() + 5, {}
        while time.time() < end and "duration" not in seen:
            for kind, data in m.events():
                if kind == "property" and data[1] is not None:
                    seen[data[0]] = data[1]
            time.sleep(0.02)
        assert seen.get("duration", 0) > 0.5
    finally:
        m.close()


# -- the player in the window ------------------------------------------------------------------------

def test_plays_inside_the_show_page(win):
    mpv = play_inside(win)
    host = win.player_host
    assert win.playback.session.kind == "anigui" and host.active and host.session is win.playback.session
    assert win.detail.theater_on and win.detail.header.isHidden()
    assert pump(lambda: host.mode == "theater" and host.isVisible())
    slot = win.detail.theater.slot
    assert host.video.size() == slot.size()                                # exactly over the slot
    assert win.ctx.player.launched                                          # (through the same launcher)
    mpv.set_prop("duration", 1440.0)
    mpv.set_prop("time-pos", 600.0)
    assert pump(lambda: host.controls.position == 600.0 and host.controls.duration == 1440.0)
    assert host.controls.title == "Starfall Academy · Episode 5"
    # the rail beside it marks what's playing
    items = win.detail.theater.rail.model.items
    assert [i["number"] for i in items if i["playing"]] == ["5"]


def test_controls_drive_mpv(win):
    mpv = play_inside(win)
    c = win.player_host.controls
    for name in ("play", "back10", "fwd10", "mute"):
        c.action.emit(name)
    c.seekTo.emit(300.0)
    assert pump(lambda: ["cycle", "pause"] in mpv.commands and ["seek", "300.00", "absolute"] in mpv.commands)
    assert ["seek", "-10", "relative"] in mpv.commands and ["seek", "10", "relative"] in mpv.commands
    assert ["cycle", "mute"] in mpv.commands


def test_mini_player_away_from_the_show(win):
    play_inside(win)
    host = win.player_host
    win.go(win.home)
    assert pump(lambda: host.mode == "mini")
    assert (host.width(), host.height()) == (189 * 16 // 9, 189) or host.height() == 189
    host.controls.action.emit("expand")                                     # click it: back to the show
    assert pump(lambda: win.stack.currentWidget() is win.detail and host.mode == "theater")


def test_chevron_shrinks_it_and_full_screen_fills_the_window(win):
    play_inside(win)
    host = win.player_host
    host.controls.action.emit("down")
    assert host.mode == "mini" and win.detail.theater_on                    # stays mini on purpose
    host.controls.action.emit("expand")
    assert pump(lambda: host.mode == "theater")
    host.controls.action.emit("full")
    assert host.mode == "full" and host.geometry() == win.centralWidget().rect()
    win._escape()
    assert host.mode == "theater"


def test_skip_intro_button(win):
    mpv = play_inside(win)
    s = win.playback.session
    s.now.skips = [aniskip.Segment("intro", 5.0, 95.0)]
    mpv.set_prop("time-pos", 12.0)
    c = win.player_host.controls
    assert pump(lambda: c.skip_label == "intro")
    c.skip.emit()
    assert pump(lambda: ["seek", "95.00", "absolute"] in mpv.commands)
    assert c.skip_label is None


def test_up_next_card(win):
    play_inside(win)
    s = win.playback.session
    c = win.player_host.controls
    s.countdown.emit("Episode 6", 8)
    assert c.countdown == ("Episode 6", 8)
    played = []
    s.play_next_now = lambda: played.append("now")
    s.cancel_countdown = lambda: played.append("cancel")
    c.upNext.emit(False)
    c.upNext.emit(True)
    assert played == ["cancel", "now"]
    s.countdown.emit("", -1)
    assert c.countdown is None


def test_built_in_messages_replace_mpvs_text(win):
    mpv = play_inside(win)
    s = win.playback.session
    s._osd("That was the last episode", 3000)
    assert win.player_host.controls.message[0] == "That was the last episode"
    assert not mpv.named("show-text")


def test_menu_has_tracks_speed_and_holiday_switches(win, monkeypatch):
    from ui import theme
    mpv = play_inside(win)
    mpv.set_prop("track-list", [{"id": 1, "type": "audio", "lang": "jpn", "selected": True},
                                {"id": 1, "type": "sub", "lang": "eng", "title": "English", "selected": True}])
    host = win.player_host
    assert pump(lambda: host._tracks)
    host.menu_test = True
    monkeypatch.setattr(theme, "HOLIDAY", True)
    menu = host._menu()
    names = [a.text() for a in menu.actions()]
    assert names[:3] == ["Audio", "Subtitles", "Speed"] and "Lights" in names and "Snow around the player" in names
    lights = next(a for a in menu.actions() if a.text() == "Lights")
    lights.toggle()
    assert win.ctx.pref("player_lights") is False
    subs = menu.actions()[1].menu()
    assert [a.text() for a in subs.actions()] == ["Off", "English (eng)"]
    menu.close()


def test_closing_the_player_saves_and_puts_the_page_back(win):
    mpv = play_inside(win)
    mpv.set_prop("duration", 1440.0)
    mpv.set_prop("time-pos", 700.0)
    host = win.player_host
    assert pump(lambda: host.controls.position == 700.0)
    host.controls.action.emit("close")
    assert pump(lambda: not host.active and host.isHidden())
    assert not win.detail.theater_on and not win.detail.header.isHidden()
    p = win.ctx.store.get_progress(STARFALL, "5")
    assert p and abs(p.position - 700.0) < 1


def test_external_players_unchanged(win):
    win.ctx.set_pref("player", "auto")
    win.open_item(win.ctx.store.get_show(STARFALL))
    assert pump(lambda: win.detail.grid.model_.items)
    win.detail.play("5")
    assert pump(lambda: win.playback.session is not None and win.playback.session.alive, 8)
    assert win.playback.session.kind == "mpv" and not win.player_host.active and not win.detail.theater_on


def test_holiday_decor_around_the_player(win, monkeypatch):
    from ui import theme
    monkeypatch.setattr(theme, "HOLIDAY", True)
    play_inside(win)
    t = win.detail.theater
    assert not t.lights.isHidden() and not t.garland.isHidden()
    win.ctx.set_pref("player_lights", False)
    win.detail.refresh_theater()
    assert t.lights.isHidden() and t.garland.isHidden()


def test_offer_the_built_in_player_once(win):
    from core import setup
    win.ctx.set_pref("setup_done", True)
    win.ctx.set_pref("player", "auto")
    win._on_status(setup.SetupStatus("/x/ani-cli", "4.10", True, True, ("iina", "/x/iina"), True))
    assert not win.banner.isHidden() and "built-in player" in win.banner.text()
    win._banner_link("#try-player")
    assert win.ctx.pref("player") == "anigui" and win.banner.isHidden()
    win.ctx.set_pref("player", "iina")
    win._offer_built_in_player()
    assert win.banner.isHidden()                       # asked once


def test_new_installs_play_inside(win):
    win.ctx.settings.remove("player")
    win.ctx.set_pref("setup_done", False)
    win._offer_built_in_player()
    assert win.ctx.pref("player") == "anigui"
