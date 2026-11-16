"""TV mode (2.1): a small relay on this Mac so your TV can fetch an episode itself.

hianime's video servers only answer requests that say where they came from (a Referer), and a
TV playing over AirPlay sends none. So AniGUI listens on your Wi-Fi, hands the TV a playlist
that points back here, and fetches each piece from hianime on the TV's behalf, adding what the
server wants. The TV then plays the stream at full quality; this Mac only passes bytes along.

Only this Mac's own stream links are served: every relay address carries a signature, so the
relay can't be used to fetch anything else. It runs only while an episode is sent to a TV.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.server
import math
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from . import http as _http
from .ani_cli import StreamInfo, is_web_url

CHUNK = 128 * 1024
TYPES = {".m3u8": "application/vnd.apple.mpegurl", ".ts": "video/mp2t", ".m4s": "video/iso.segment",
         ".mp4": "video/mp4", ".m4a": "audio/mp4", ".aac": "audio/aac", ".vtt": "text/vtt",
         ".key": "application/octet-stream"}


# -- this Mac on the Wi-Fi ---------------------------------------------------------------------

def airplay_receivers(seconds: float = 3.0) -> list[str]:
    """Names of AirPlay receivers macOS can see on this network right now (Bonjour, via the
    dns-sd tool that ships with macOS). Empty off a Mac or when none answer."""
    if sys.platform != "darwin":
        return []
    try:
        proc = subprocess.Popen(["dns-sd", "-B", "_airplay._tcp", "local."], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return []
    names: list[str] = []
    try:
        proc.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
    out = proc.stdout.read() if proc.stdout else ""
    for line in out.splitlines():
        m = re.search(r"\s_airplay\._tcp\.\s+(.+?)\s*$", line)
        if m and " Add " in f" {line} ":
            name = m.group(1).replace("\\032", " ")
            if name not in names:
                names.append(name)
    return names


def lan_addresses() -> list[str]:
    """IPv4 addresses a TV on the same Wi-Fi could reach, best first. A VPN's own address
    (10.x on a utun interface, say) is left out: the TV can't reach it."""
    found: list[tuple[int, str]] = []
    if sys.platform != "darwin":
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                return [ip]
        except OSError:
            pass
        return []
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    iface = ""
    for line in out.splitlines():
        if line and not line[0].isspace():
            iface = line.split(":")[0]
        m = re.match(r"\s+inet (\d+\.\d+\.\d+\.\d+)", line)
        if not m or not iface:
            continue
        ip = m.group(1)
        if ip.startswith("127.") or ip.startswith("169.254."):
            continue
        if not (iface.startswith("en") or iface.startswith("bridge")):
            continue                       # utun (VPN), awdl, llw, lo: not the Wi-Fi
        private = ip.startswith("192.168.") or ip.startswith("10.") or re.match(r"172\.(1[6-9]|2\d|3[01])\.", ip)
        rank = (0 if iface == "en0" else 1) + (0 if private else 5)
        found.append((rank, ip))
    return [ip for _r, ip in sorted(found)]


# -- playlists ---------------------------------------------------------------------------------

_ATTR = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def _attrs(line: str) -> dict[str, str]:
    body = line.split(":", 1)[1] if ":" in line else ""
    return {k: v.strip('"') for k, v in _ATTR.findall(body)}


def _set_attr(line: str, key: str, value: str) -> str:
    if re.search(rf'(?<![A-Z-]){key}=', line):
        return re.sub(rf'(?<![A-Z-]){key}=("[^"]*"|[^,]*)', f'{key}="{value}"', line)
    return f'{line},{key}="{value}"'


def rewrite_playlist(text: str, base: str, link, subtitles: str | None = None,
                     audio: str | None = None) -> str:
    """Every address in an HLS playlist pointed back at the relay. link(url, kind) gives the
    relay address for an upstream one (kind: "m" playlist, "s" anything else). For a master
    playlist, subtitles/audio (relay playlist addresses) are added as selectable tracks."""
    out: list[str] = []
    master = "#EXT-X-STREAM-INF" in text
    added_tracks = False
    expect_uri = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if expect_uri and not line.startswith("#"):
            out.append(link(urljoin(base, line), "m"))
            expect_uri = False
            continue
        if line.startswith("#EXT-X-STREAM-INF"):
            if master and not added_tracks:
                if subtitles:
                    out.append('#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="anigui-subs",NAME="English",LANGUAGE="en",'
                               f'DEFAULT=YES,AUTOSELECT=YES,FORCED=NO,URI="{subtitles}"')
                if audio:
                    out.append('#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="anigui-audio",NAME="Audio",DEFAULT=YES,'
                               f'AUTOSELECT=YES,URI="{audio}"')
                added_tracks = True
            if subtitles:
                line = _set_attr(line, "SUBTITLES", "anigui-subs")
            if audio:
                line = _set_attr(line, "AUDIO", "anigui-audio")
            out.append(line)
            expect_uri = True
            continue
        if line.startswith("#EXT-X-I-FRAME-STREAM-INF"):
            continue                       # trick-play streams: not needed, and a second set of links
        if line.startswith(("#EXT-X-MEDIA:", "#EXT-X-KEY:", "#EXT-X-MAP:", "#EXT-X-SESSION-KEY:")):
            a = _attrs(line)
            if "URI" in a:
                kind = "m" if line.startswith("#EXT-X-MEDIA:") else "s"
                line = _set_attr(line, "URI", link(urljoin(base, a["URI"]), kind))
            out.append(line)
            continue
        if line.startswith("#"):
            out.append(line)
            continue
        out.append(link(urljoin(base, line), "s"))
    return "\n".join(out) + "\n"


def playlist_duration(text: str) -> float:
    total = 0.0
    for line in text.splitlines():
        if line.startswith("#EXTINF:"):
            try:
                total += float(line[8:].split(",", 1)[0])
            except ValueError:
                pass
    return total


def wrap_variant(variant_link: str, subtitles: str | None, audio: str | None) -> str:
    """A master playlist around a single-quality playlist (what ani-cli hands over), so a TV
    gets the subtitle (and audio) tracks as selectable tracks. BANDWIDTH is required by the
    format; the TV only uses it to pick between qualities, and there's one."""
    out = ["#EXTM3U", "#EXT-X-VERSION:3"]
    inf = "#EXT-X-STREAM-INF:BANDWIDTH=6000000"
    if subtitles:
        out.append('#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="anigui-subs",NAME="English",LANGUAGE="en",DEFAULT=YES,'
                   f'AUTOSELECT=YES,FORCED=NO,URI="{subtitles}"')
        inf += ',SUBTITLES="anigui-subs"'
    if audio:
        out.append('#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="anigui-audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,'
                   f'URI="{audio}"')
        inf += ',AUDIO="anigui-audio"'
    out += [inf, variant_link]
    return "\n".join(out) + "\n"


def subtitles_playlist(vtt_url: str, seconds: float) -> str:
    seconds = max(1.0, seconds)
    return ("#EXTM3U\n#EXT-X-VERSION:3\n"
            f"#EXT-X-TARGETDURATION:{math.ceil(seconds)}\n#EXT-X-MEDIA-SEQUENCE:0\n#EXT-X-PLAYLIST-TYPE:VOD\n"
            f"#EXTINF:{seconds:.3f},\n{vtt_url}\n#EXT-X-ENDLIST\n")


# -- the relay ---------------------------------------------------------------------------------

@dataclass
class Stats:
    requests: int = 0
    bytes: int = 0
    playlists: int = 0
    pieces: int = 0
    errors: list[str] = field(default_factory=list)
    clients: dict[str, int] = field(default_factory=dict)     # address -> requests
    last_at: float = 0.0


class Relay:
    """start(info) -> the playlist address to hand a TV; stop() when done."""

    def __init__(self, host: str | None = None, port: int = 0) -> None:
        self.secret = secrets.token_bytes(32)
        self.host = host
        self.port = port
        self.server: http.server.ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.info: StreamInfo | None = None
        self.title = ""
        self.stats = Stats()
        self._variant: str | None = None          # the first video playlist seen (for the length)
        self._length: float | None = None

    # addresses
    def _sign(self, kind: str, payload: str) -> str:
        return hmac.new(self.secret, f"{kind}:{payload}".encode(), hashlib.sha256).hexdigest()[:24]

    def _b64(self, url: str) -> str:
        return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")

    @staticmethod
    def _unb64(text: str) -> str:
        pad = "=" * (-len(text) % 4)
        return base64.urlsafe_b64decode(text + pad).decode()

    def link(self, url: str, kind: str) -> str:
        """The relay address for an upstream address (absolute, for the TV)."""
        payload = self._b64(url)
        ext = os.path.splitext(urlparse(url).path)[1].lower()
        name = "index.m3u8" if kind == "m" else f"piece{ext if ext in TYPES else ''}"
        return f"{self.base}/{kind}/{self._sign(kind, payload)}/{payload}/{name}"

    @property
    def base(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def running(self) -> bool:
        return self.server is not None

    def start(self, info: StreamInfo, title: str = "") -> str:
        for link in (info.url, info.audio_url, info.subtitle_url):
            if link is not None and not is_web_url(link):
                raise ValueError("The stream link didn't look right, so it wasn't sent.")
        if self.host is None:
            addrs = lan_addresses()
            if not addrs:
                raise OSError("This Mac doesn't seem to be on a Wi-Fi or Ethernet network.")
            self.host = addrs[0]
        self.info, self.title = info, title
        self.stats = Stats()
        relay = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            timeout = 20                   # an idle kept-alive connection lets go after this

            def log_message(self, *_a):
                pass

            def do_GET(self):
                relay._serve(self)

            def do_HEAD(self):
                relay._serve(self, head=True)

        self.server = http.server.ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        self.server.daemon_threads = True
        self.server.block_on_close = False   # stop() doesn't wait for a TV that's still connected
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, name="tv relay", daemon=True)
        self.thread.start()
        return self.link(info.url, "m")

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    # serving
    def _serve(self, h: http.server.BaseHTTPRequestHandler, head: bool = False) -> None:
        st = self.stats
        st.requests += 1
        st.last_at = time.time()
        client = h.client_address[0]
        st.clients[client] = st.clients.get(client, 0) + 1
        parts = h.path.split("?", 1)[0].strip("/").split("/")
        try:
            if len(parts) == 4 and parts[0] in ("m", "s", "subs") and \
                    hmac.compare_digest(parts[1], self._sign(parts[0], parts[2])):
                kind, payload = parts[0], parts[2]
                url = self._unb64(payload)
                if kind == "m":
                    self._playlist(h, url, head)
                elif kind == "subs":
                    self._subs(h, url, head)
                else:
                    self._piece(h, url, head)
                return
        except (OSError, ValueError) as exc:
            st.errors.append(f"{time.strftime('%H:%M:%S')} {parts[0] if parts else '?'}: {exc}")
            del st.errors[:-20]
            try:
                h.send_error(502, "Couldn't fetch that from the video server")
            except OSError:
                pass
            return
        h.send_error(404)

    def _send(self, h, body: bytes, ctype: str, head: bool) -> None:
        h.send_response(200)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Cache-Control", "no-store")
        h.send_header("Access-Control-Allow-Origin", "*")
        h.end_headers()
        if not head:
            h.wfile.write(body)
        self.stats.bytes += len(body)

    def _headers(self) -> dict[str, str]:
        return {"Referer": self.info.referrer} if self.info and self.info.referrer else {}

    def _fetch_text(self, url: str) -> tuple[str, str]:
        url = url.split("#", 1)[0]           # ("#v" marks the wrapped variant; servers never see it)
        with _http.open_stream(url, self._headers()) as resp:
            return resp.read().decode("utf-8", "replace"), resp.geturl()

    def _playlist(self, h, url: str, head: bool) -> None:
        text, final = self._fetch_text(url)
        if not text.lstrip().startswith("#EXTM3U"):
            raise ValueError("That wasn't a playlist")
        self.stats.playlists += 1
        subs = audio = None
        root = url == self.info.url and (self.info.subtitle_url or self.info.audio_url)
        if root:
            if self.info.subtitle_url:
                payload = self._b64(self.info.subtitle_url)
                subs = f"{self.base}/subs/{self._sign('subs', payload)}/{payload}/index.m3u8"
            if self.info.audio_url:
                audio = self.link(self.info.audio_url, "m")
        if "#EXT-X-STREAM-INF" not in text and self._variant is None:
            self._variant = final
            self._length = playlist_duration(text)
        if root and "#EXT-X-STREAM-INF" not in text:
            # ani-cli hands over one quality's playlist: wrap it so the tracks come along
            body = wrap_variant(self.link(final if final != url else url + "#v", "m"), subs, audio).encode()
        else:
            body = rewrite_playlist(text, final, self.link, subs, audio).encode()
        self._send(h, body, TYPES[".m3u8"], head)

    def _subs(self, h, vtt_url: str, head: bool) -> None:
        if self._length is None:
            text, final = self._fetch_text(self.info.url)
            if "#EXT-X-STREAM-INF" in text:
                m = re.search(r"^(?!#)(\S+)$", text, re.M)
                if m:
                    text, final = self._fetch_text(urljoin(final, m.group(1)))
            self._length = playlist_duration(text) or 24 * 60.0
        body = subtitles_playlist(self.link(vtt_url, "s"), self._length).encode()
        self._send(h, body, TYPES[".m3u8"], head)

    def _piece(self, h, url: str, head: bool) -> None:
        ext = os.path.splitext(urlparse(url).path)[1].lower()
        headers = self._headers()
        rng = h.headers.get("Range")
        if rng:
            headers["Range"] = rng
        try:
            resp = _http.open_stream(url, headers, timeout=60)
        except urllib.error.HTTPError as exc:
            h.send_error(exc.code)
            return
        with resp:
            status = resp.status
            h.send_response(status)
            ctype = resp.headers.get("Content-Type") or TYPES.get(ext, "application/octet-stream")
            if ext == ".vtt":
                ctype = TYPES[".vtt"]
            h.send_header("Content-Type", ctype)
            for name in ("Content-Length", "Content-Range", "Accept-Ranges"):
                if resp.headers.get(name):
                    h.send_header(name, resp.headers[name])
            if not resp.headers.get("Content-Length") and not head:
                h.send_header("Connection", "close")
            h.send_header("Cache-Control", "no-store")
            h.end_headers()
            self.stats.pieces += 1
            if head:
                return
            if ext == ".vtt":
                data = resp.read()
                if not data.lstrip().startswith(b"WEBVTT"):
                    data = b"WEBVTT\n\n" + data
                h.wfile.write(data)
                self.stats.bytes += len(data)
                return
            while chunk := resp.read(CHUNK):
                h.wfile.write(chunk)
                self.stats.bytes += len(chunk)
