"""TV mode (2.1): the relay that lets a TV fetch an episode itself, and the AirPlay bridge."""

import http.server
import sys
import threading
import urllib.request
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_step4 import fast, pump, win  # noqa: E402,F401
from test_v1110 import play_inside  # noqa: E402


class _Site:
    """hianime stand-in: a master playlist with two qualities, an encrypted variant, a VTT."""

    def __init__(self):
        self.seen = []
        self.files = {
            "/v/master.m3u8": ("#EXTM3U\n#EXT-X-VERSION:3\n"
                               '#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=1,URI="iframes.m3u8"\n'
                               "#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360\n360/index.m3u8\n"
                               "#EXT-X-STREAM-INF:BANDWIDTH=4000000,RESOLUTION=1920x1080\n1080/index.m3u8\n"),
            "/v/1080/index.m3u8": ("#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-MEDIA-SEQUENCE:0\n"
                                   '#EXT-X-KEY:METHOD=AES-128,URI="../key.key",IV=0x00000000000000000000000000000001\n'
                                   '#EXT-X-MAP:URI="init.mp4"\n'
                                   "#EXTINF:4.000,\nseg0.ts\n#EXTINF:3.500,\nseg1.ts\n#EXTINF:2.250,\n"
                                   "https://cdn.example.invalid/far/seg2.ts\n#EXT-X-ENDLIST\n"),
            "/v/360/index.m3u8": "#EXTM3U\n#EXTINF:4,\na.ts\n#EXT-X-ENDLIST\n",
            "/v/key.key": "0123456789abcdef",
            "/v/1080/init.mp4": "INIT",
            "/v/1080/seg0.ts": "S0" * 70000,
            "/v/1080/seg1.ts": "S1" * 100,
            "/subs/en.vtt": "00:00.000 --> 00:01.000\nHi\n",
        }

    def handler(self):
        site = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_GET(self):
                site.seen.append((self.path, self.headers.get("Referer"), self.headers.get("Range")))
                body = site.files.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = body.encode() if isinstance(body, str) else body
                rng = self.headers.get("Range")
                if rng:
                    start = int(rng[6:].split("-")[0])
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                    data = data[start:]
                else:
                    self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        return H


@pytest.fixture
def site():
    s = _Site()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), s.handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    s.base = f"http://127.0.0.1:{server.server_address[1]}"
    yield s
    server.shutdown()
    server.server_close()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, dict(r.headers), r.read()


def test_relay_hands_the_tv_a_playlist_that_points_back_home(site):
    from core.ani_cli import StreamInfo
    from core.tvrelay import Relay
    info = StreamInfo(url=site.base + "/v/master.m3u8", referrer="https://ref.example/", title="x",
                      subtitle_url=site.base + "/subs/en.vtt")
    relay = Relay(host="127.0.0.1")
    try:
        url = relay.start(info, "Show")
        assert url.startswith(relay.base + "/m/") and url.endswith("/index.m3u8")
        _st, hd, body = _get(url)
        master = body.decode()
        assert hd["Content-Type"].startswith("application/vnd.apple.mpegurl")
        assert "cdn.example" not in master and "I-FRAME" not in master
        assert 'TYPE=SUBTITLES' in master and 'SUBTITLES="anigui-subs"' in master
        lines = [ln for ln in master.splitlines() if ln and not ln.startswith("#")]
        assert len(lines) == 2 and all(ln.startswith(relay.base + "/m/") for ln in lines)
        _st, _hd, body = _get(lines[1])                                  # 1080p
        variant = body.decode()
        assert "key.key" not in variant and "init.mp4" not in variant    # every address relayed
        assert variant.count(relay.base + "/s/") == 5                    # key, map, 3 pieces
        seg0 = [ln for ln in variant.splitlines() if ln.endswith("piece.ts")][0]
        st, hd, body = _get(seg0)
        assert st == 200 and body == b"S0" * 70000 and hd["Content-Type"] == "video/mp2t"
        st, hd, body = _get(seg0, {"Range": "bytes=139990-"})            # a TV asking for a part
        assert st == 206 and body == b"S0" * 5
        assert all(ref == "https://ref.example/" for _p, ref, _r in site.seen)   # what hianime wants
        assert relay.stats.pieces >= 2 and "127.0.0.1" in relay.stats.clients
    finally:
        relay.stop()


def test_relay_subtitles_cover_the_whole_episode(site):
    from core.ani_cli import StreamInfo
    from core.tvrelay import Relay
    info = StreamInfo(url=site.base + "/v/master.m3u8", referrer=None, title="x",
                      subtitle_url=site.base + "/subs/en.vtt")
    relay = Relay(host="127.0.0.1")
    try:
        url = relay.start(info)
        master = _get(url)[2].decode()
        subs_url = [ln for ln in master.splitlines() if "TYPE=SUBTITLES" in ln][0].split('URI="')[1].rstrip('"')
        pl = _get(subs_url)[2].decode()
        assert "#EXTINF:4.000," in pl                                     # the 360p one is first: 4 s
        vtt_url = [ln for ln in pl.splitlines() if not ln.startswith("#")][0]
        st, hd, body = _get(vtt_url)
        assert hd["Content-Type"] == "text/vtt" and body.startswith(b"WEBVTT")   # header added
    finally:
        relay.stop()


def test_relay_serves_only_its_own_signed_links(site):
    from core.ani_cli import StreamInfo
    from core.tvrelay import Relay
    relay = Relay(host="127.0.0.1")
    try:
        url = relay.start(StreamInfo(url=site.base + "/v/master.m3u8", referrer=None, title="x"))
        kind, sig, payload, name = url[len(relay.base) + 1:].split("/")
        with pytest.raises(urllib.error.HTTPError) as e:
            _get(f"{relay.base}/{kind}/{'0' * 24}/{payload}/{name}")
        assert e.value.code == 404
        other = Relay(host="127.0.0.1")
        with pytest.raises(urllib.error.HTTPError):
            _get(f"{relay.base}/{kind}/{other._sign(kind, payload)}/{payload}/{name}")
        with pytest.raises(urllib.error.HTTPError):
            _get(f"{relay.base}/anything")
        with pytest.raises(ValueError):
            Relay(host="127.0.0.1").start(StreamInfo(url="file:///etc/passwd", referrer=None, title="x"))
    finally:
        relay.stop()


def test_rewrite_and_duration_helpers():
    from core.tvrelay import playlist_duration, rewrite_playlist, subtitles_playlist
    text = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1,AUDIO=\"old\"\nv.m3u8\n"
    out = rewrite_playlist(text, "https://h/x/", lambda u, k: f"R:{k}:{u}", subtitles="S", audio="A")
    assert 'AUDIO="anigui-audio"' in out and 'SUBTITLES="anigui-subs"' in out and "R:m:https://h/x/v.m3u8" in out
    assert out.index("TYPE=SUBTITLES") < out.index("#EXT-X-STREAM-INF")
    assert playlist_duration("#EXTINF:4,\na\n#EXTINF:2.5,\nb\n") == 6.5
    assert "#EXTINF:6.500," in subtitles_playlist("V", 6.5) and "#EXT-X-ENDLIST" in subtitles_playlist("V", 6.5)


def test_lan_addresses_and_airplay_off_a_mac():
    from core.airplay import AirPlayer, CMTime
    from core.tvrelay import lan_addresses
    assert all(a.count(".") == 3 for a in lan_addresses())
    assert CMTime(1500, 1000, 1, 0).seconds == 1.5 and CMTime(0, 0, 0, 0).seconds is None
    if sys.platform != "darwin":
        ap = AirPlayer()
        assert not ap.ok and not ap.load("http://x/") and ap.status()["state"] == "none"
        assert not ap.attach_picker(1, 0, 0, 10, 10)
        ap.close()


def test_the_player_controls_have_an_airplay_button_that_knows_the_stream(win):
    play_inside(win)
    s = win.playback.session
    assert s.now.info is not None and s.now.info.url.startswith("http")
    host = win.player_host
    host.controls.resize(900, 120)
    host.controls.repaint()
    assert pump(lambda: "btn:tv" in host.controls._hits)
    host.controls.tv_button = False
    host.controls.repaint()
    assert pump(lambda: "btn:tv" not in host.controls._hits)
    host.controls.tv_button = True


def test_a_single_quality_stream_gets_wrapped_so_subtitles_come_along(site):
    """ani-cli hands over one quality's playlist (…/1080/index.m3u8), not a master: the TV
    only sees a subtitle track if the relay builds a master around it."""
    from core.ani_cli import StreamInfo
    from core.tvrelay import Relay
    info = StreamInfo(url=site.base + "/v/1080/index.m3u8", referrer=None, title="x",
                      subtitle_url=site.base + "/subs/en.vtt")
    relay = Relay(host="127.0.0.1")
    try:
        url = relay.start(info)
        master = _get(url)[2].decode()
        assert "#EXT-X-STREAM-INF" in master and 'TYPE=SUBTITLES' in master and 'SUBTITLES="anigui-subs"' in master
        inner = [ln for ln in master.splitlines() if not ln.startswith("#")][0]
        assert inner != url and inner.startswith(relay.base + "/m/")
        variant = _get(inner)[2].decode()
        assert "#EXTINF:4.000" in variant and variant.count(relay.base + "/s/") == 5   # the real pieces
        subs_url = [ln for ln in master.splitlines() if "TYPE=SUBTITLES" in ln][0].split('URI="')[1].rstrip('"')
        pl = _get(subs_url)[2].decode()
        assert "#EXTINF:9.750," in pl                                    # 4 + 3.5 + 2.25: the whole episode
        assert not any("#v" in p for p, _r, _g in site.seen)             # the marker never reaches the server
    finally:
        relay.stop()


# -- TV mode: the session on the TV ------------------------------------------------------------

from test_step4 import LANTERN, _show  # noqa: E402


def play_on_mac(w, episode="5"):
    if not w.ctx.store.get_show(LANTERN):
        _show(w, LANTERN, "The Lantern Keeper")
    return play_inside(w, LANTERN, episode)


class FakeAirPlayer:
    """Plays at normal speed once playing; a test flips `external` when the TV takes over."""
    ok = True

    def __init__(self):
        self.url = ""
        self.external = False
        self.playing = False
        self.time = 0.0
        self.duration = 1440.0
        self.volume = 1.0
        self.error = ""
        self.loads = []
        self.picker_attached = False
        self.pressed = 0
        self.closed = False
        self._t = None

    def _sync(self):
        import time as _t
        now = _t.monotonic()
        if self.playing and self._t is not None:
            self.time = min(self.duration, self.time + (now - self._t) * 60)      # 60x: tests are quick
        self._t = now

    def load(self, url, start=None, play=True):
        self.url = url
        self.loads.append((url, start))
        self.time = float(start or 0)
        self.playing = play
        self._t = None
        return True

    def replace(self, url, start=None):
        return self.load(url, start, play=False)

    def play(self):
        self._sync()
        self.playing = True

    def pause(self):
        self._sync()
        self.playing = False

    def seek(self, seconds):
        self._sync()
        self.time = float(seconds)

    def set_volume(self, level):
        self.volume = level

    def attach_picker(self, nsview, x, y, w, h):
        self.picker_attached = True
        return True

    def press_picker(self):
        self.pressed += 1
        return "fake"

    def status(self):
        self._sync()
        return {"external": self.external, "state": "playing" if self.playing else "paused", "time": self.time,
                "duration": self.duration, "rate": 1.0 if self.playing else 0.0, "waiting": "",
                "error": self.error, "item": "ready"}

    def close(self):
        self.closed = True
        self.playing = False

    def detach_picker(self):
        self.picker_attached = False


class FakeRelay:
    def __init__(self):
        self.streams = []
        self.running = False
        self.host = "127.0.0.1"
        self.base = "http://127.0.0.1:1"

    def start(self, info, title=""):
        self.streams.append(info)
        self.running = True
        return f"http://127.0.0.1:1/m/{len(self.streams)}/index.m3u8"

    def stop(self):
        self.running = False


@pytest.fixture
def tv(monkeypatch):
    from ui import tv_mode
    player, relay = FakeAirPlayer(), FakeRelay()
    monkeypatch.setattr(tv_mode, "AirPlayer", lambda: player)
    monkeypatch.setattr(tv_mode, "Relay", lambda: relay)
    monkeypatch.setattr(tv_mode, "airplay_receivers", lambda seconds=3.0: ["DevBook Pro", '75" Crystal UHD'])
    monkeypatch.setattr(tv_mode, "tv_name", lambda names: '75" Crystal UHD')
    return player, relay


def test_the_airplay_button_hands_the_episode_to_the_tv(win, tv):
    from ui.tv_mode import RemoteView
    player, relay = tv
    mpv = play_on_mac(win)
    mpv.set_prop("duration", 1440.0)
    mpv.set_prop("time-pos", 300.0)
    assert pump(lambda: win.playback.session.now.position == 300.0)
    host = win.player_host
    host._action("tv")
    assert pump(lambda: player.pressed == 1 and player.picker_attached)
    assert player.loads == [("http://127.0.0.1:1/m/1/index.m3u8", 300.0)] and not player.playing
    assert player.volume == 0.0 and relay.streams[0].url.startswith("https://cdn.example/")
    assert win.playback.session.kind == "anigui"                 # nothing moves until a TV is picked
    player.external = True                                       # the TV takes over
    assert pump(lambda: win.playback.session is not None and win.playback.session.kind == "tv", 3)
    s = win.playback.session
    assert player.playing and player.volume == 1.0 and abs(player.time - 300) < 5
    assert isinstance(host.video, RemoteView) and host.session is s and host.on_tv
    assert win.ctx.store.get_progress(LANTERN, "5").position == 300.0     # saved at the handoff
    assert win.ctx.pref("tv_used") is True
    assert pump(lambda: host.video.tv == '75" Crystal UHD')
    assert host.video.title == "Episode 5"
    # the controls drive the TV
    assert pump(lambda: s.now.position is not None and s.now.position > 300)
    host._action("play")
    assert pump(lambda: not player.playing and host.controls.paused)
    host._action("play")
    assert pump(lambda: player.playing)
    host._cmd("seek", "600", "absolute")
    assert abs(player.time - 600) < 5
    assert pump(lambda: win.ctx.store.get_progress(LANTERN, "5").position >= 600, 4)
    # the next episode plays on the TV by itself
    player.seek(player.duration - 1)
    player.pause()
    player.time = player.duration
    assert pump(lambda: s.next_info is not None or s._target is not None, 6)
    assert pump(lambda: s.now.episode == "6", 12)
    assert len(relay.streams) == 2 and player.loads[-1][0].endswith("/m/2/index.m3u8") and player.playing
    assert win.ctx.store.get_progress(LANTERN, "5").completed
    assert host.video.title == "Episode 6"


def test_bring_back_to_this_mac_resumes_where_the_tv_was(win, tv):
    player, relay = tv
    play_on_mac(win)
    host = win.player_host
    host._action("tv")
    player.external = True
    assert pump(lambda: win.playback.session.kind == "tv", 3)
    player.seek(777)
    assert pump(lambda: win.playback.session.now.position and win.playback.session.now.position >= 777)
    before = len(win.ctx.player.launched)
    host.bringBack.emit()
    assert pump(lambda: len(win.ctx.player.launched) > before)
    info, _title, start = win.ctx.player.launched[-1]
    assert start >= 777 and info.url == relay.streams[0].url
    assert player.closed and not relay.running
    assert pump(lambda: win.playback.session is not None and win.playback.session.kind == "anigui", 5)
    assert not host.on_tv


def test_no_tv_picked_changes_nothing(win, tv, monkeypatch):
    from ui import tv_mode
    player, relay = tv
    monkeypatch.setattr(tv_mode, "HANDOFF_TIMEOUT_S", 0.5)
    play_on_mac(win)
    host = win.player_host
    host._action("tv")
    assert pump(lambda: player.pressed == 1)
    host._action("tv")                                            # again: just reopens the menu
    assert player.pressed == 2 and len(player.loads) == 1
    assert pump(lambda: player.closed and not relay.running, 3)   # gave up quietly
    assert win.playback.session.kind == "anigui" and win.playback._handoff is None
    host._action("tv")                                            # and can try again
    assert pump(lambda: player.pressed == 3)


def test_on_the_tv_the_menu_has_no_moments_but_a_way_back(win, tv):
    player, relay = tv
    play_on_mac(win)
    host = win.player_host
    host._action("tv")
    player.external = True
    assert pump(lambda: win.playback.session.kind == "tv", 3)
    host.menu_test = True
    menu = host._menu()
    texts = {a.text(): a for a in menu.actions()}
    assert not texts["Save this moment  (B)"].isEnabled() and not texts["Sharper picture"].isEnabled()
    assert "Bring back to this Mac" in texts
    assert host.save_moment() is None
    host._action("tv")
    assert "on the TV" in host.controls.message[0]


def test_the_first_time_a_tv_is_on_the_wifi_the_player_points_at_the_button(win, tv, monkeypatch):
    from ui import tv_guide
    from ui.tv_guide import TvGuideDialog
    import core.tvrelay as relay_mod
    seen = lambda seconds=3.0: ["DevBook Pro", '75" Crystal UHD']  # noqa: E731
    monkeypatch.setattr(relay_mod, "airplay_receivers", seen)
    monkeypatch.setattr(tv_guide, "airplay_receivers", seen)
    monkeypatch.setattr(relay_mod, "this_mac_name", lambda: "devbook pro")
    play_on_mac(win)
    host = win.player_host
    assert pump(lambda: host.controls.pointer is not None, 4)
    assert '75" Crystal UHD' in host.controls.pointer and win.ctx.pref("tv_pointed") is True
    host.controls.resize(900, 120)
    host.controls.repaint()
    assert pump(lambda: "pointer" in host.controls._hits)
    assert host.controls.keep_visible()                      # the controls stay up while it shows
    opened = []
    monkeypatch.setattr(TvGuideDialog, "show", lambda self: opened.append(self))
    host._action("tv_guide")
    assert pump(lambda: opened)
    g = opened[0]
    assert g.send.isVisibleTo(g)                             # an episode is playing here: "Send this episode"
    assert pump(lambda: "Found on your Wi-Fi" in g.found.text(), 4)
    assert '75" Crystal UHD' in g.found.text()
    g.send.click()
    assert pump(lambda: tv[0].pressed == 1)
    host.controls.clear_pointer()
    assert host.controls.pointer is None
    # once only; and playing something else drops the picker that was waiting
    host._tv_scan = None
    play_on_mac(win, "6")
    assert pump(lambda: win.playback.session.now.episode == "6", 4)
    assert win.playback._handoff is None and tv[0].closed
    pump(lambda: False, 1.2)
    assert host.controls.pointer is None


def test_no_pointer_when_no_tv_answers(win, tv, monkeypatch):
    import core.tvrelay as relay_mod
    monkeypatch.setattr(relay_mod, "airplay_receivers", lambda seconds=3.0: ["DevBook Pro"])
    monkeypatch.setattr(relay_mod, "this_mac_name", lambda: "devbook pro")
    play_on_mac(win)
    pump(lambda: False, 1.2)
    assert win.player_host.controls.pointer is None and not win.ctx.pref("tv_pointed")


def test_the_guide_is_in_settings_and_privacy_knows_the_relay():
    from core import privacy
    from ui.settings_dialog import SettingsDialog
    assert any(d.name.startswith("Your TV") and not d.hosts for d in privacy.DESTINATIONS)
    assert "tvGuideRequested" in dir(SettingsDialog)


def test_bring_back_button_is_clickable_above_the_controls(win, tv):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    player, relay = tv
    play_on_mac(win)
    host = win.player_host
    host._action("tv")
    player.external = True
    assert pump(lambda: win.playback.session.kind == "tv", 3)
    pump(lambda: False, 0.3)
    back = host.video.back
    assert back.parentWidget() is host and back.isVisible()
    # the widget at the button's spot is the button, not the controls overlay
    center = back.geometry().center()
    assert host.childAt(center) is back or back.geometry().contains(center)
    before = len(win.ctx.player.launched)
    QTest.mouseClick(back, Qt.MouseButton.LeftButton, pos=QPoint(back.width() // 2, back.height() // 2))
    assert pump(lambda: len(win.ctx.player.launched) > before, 4)
    assert pump(lambda: win.playback.session is not None and win.playback.session.kind == "anigui", 5)
    assert player.closed
