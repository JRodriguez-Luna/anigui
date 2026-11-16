"""TV mode (2.1): the relay that lets a TV fetch an episode itself, and the AirPlay bridge."""

import http.server
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_step4 import pump, win  # noqa: E402,F401
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


def test_send_to_tv_is_in_the_player_menu_and_knows_the_stream(win, monkeypatch):
    from ui.tv_test import TvTestWindow
    mpv = play_inside(win)
    s = win.playback.session
    assert s.now.info is not None and s.now.info.url.startswith("http")
    host = win.player_host
    host.menu_test = True
    menu = host._menu()
    act = next(a for a in menu.actions() if a.text().startswith("Send to TV"))
    opened = []
    monkeypatch.setattr(TvTestWindow, "show", lambda self: opened.append(self))
    act.trigger()
    assert pump(lambda: opened, 3)
    assert pump(lambda: ["set_property", "pause", True] in mpv.commands)
    w = opened[0]
    pump(lambda: w.step.text(), 2)
    if sys.platform != "darwin":
        assert "isn't available here" in w.step.text() and not w.relay.running
    assert "episode" in w.report().lower()
    w.close()
    assert not w.relay.running


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
