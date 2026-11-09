"""Downloads (2.0): save an episode to your Mac and watch it with no internet.

The stream ani-cli finds is either one video file or an HLS playlist (many short pieces, the
usual case). Pieces are fetched in order and joined into one file the player reads like any
other; encrypted pieces (AES-128) are decrypted on your Mac. A separate audio
track and the subtitles are saved beside it. Nothing but the stream itself is fetched, from the
same servers playing it would use.
"""

from __future__ import annotations

import ctypes
import os
import re
import sys
import time
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

from . import http
from .ani_cli import MEDIA_EXTS, StreamInfo, is_download, is_web_url  # noqa: F401

CHUNK = 256 * 1024
TRIES = 4


class DownloadError(Exception):
    pass


class Cancelled(DownloadError):
    pass


@dataclass(frozen=True)
class Saved:
    video: Path
    audio: Path | None
    subtitles: Path | None

    @property
    def size(self) -> int:
        return sum(p.stat().st_size for p in (self.video, self.audio, self.subtitles) if p and p.exists())


def safe_name(text: str, limit: int = 80) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", text)
    name = " ".join(name.split()).strip(" .")
    return (name[:limit].rstrip(" .") or "Episode")


# -- AES-128 (HLS) -------------------------------------------------------------------------------

def _decrypt_commoncrypto(key: bytes, iv: bytes, data: bytes) -> bytes:
    lib = ctypes.CDLL("/usr/lib/system/libcommonCrypto.dylib")
    out = ctypes.create_string_buffer(len(data) + 16)
    moved = ctypes.c_size_t(0)
    # CCCrypt(kCCDecrypt, kCCAlgorithmAES, kCCOptionPKCS7Padding, key, 16, iv, in, len, out, cap, &moved)
    status = lib.CCCrypt(1, 0, 1, key, ctypes.c_size_t(len(key)), iv, data, ctypes.c_size_t(len(data)),
                         out, ctypes.c_size_t(len(out)), ctypes.byref(moved))
    if status != 0:
        raise DownloadError(f"Couldn't decrypt a piece of the video (CommonCrypto {status}).")
    return out.raw[:moved.value]


def _decrypt_python(key: bytes, iv: bytes, data: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:
        raise DownloadError("This video is encrypted, and this computer can't decrypt it.") from exc
    d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    raw = d.update(data) + d.finalize()
    pad = raw[-1] if raw else 0
    if not 1 <= pad <= 16 or raw[-pad:] != bytes([pad]) * pad:
        raise DownloadError("Couldn't decrypt a piece of the video.")
    return raw[:-pad]


def decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-128-CBC with PKCS#7 padding (HLS). cryptography (bundled with AniGUI), else macOS's
    CommonCrypto."""
    try:
        import cryptography  # noqa: F401
    except ImportError:
        if sys.platform == "darwin":
            return _decrypt_commoncrypto(key, iv, data)
    return _decrypt_python(key, iv, data)


# -- HLS playlists -------------------------------------------------------------------------------

_ATTR = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def attributes(line: str) -> dict[str, str]:
    body = line.split(":", 1)[1] if ":" in line else ""
    return {k: v.strip('"') for k, v in _ATTR.findall(body)}


@dataclass
class Segment:
    url: str
    key_url: str | None
    iv: bytes | None


@dataclass
class MediaPlaylist:
    segments: list[Segment]
    init_url: str | None
    init_key: tuple[str | None, bytes | None] = (None, None)


def parse_master(text: str, base: str) -> tuple[str, str | None]:
    """(the best video playlist, its audio playlist if the audio is separate)."""
    lines = [ln.strip() for ln in text.splitlines()]
    audio: dict[str, list[dict[str, str]]] = {}
    best: tuple[int, str, str | None] | None = None
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-MEDIA:"):
            a = attributes(line)
            if a.get("TYPE") == "AUDIO" and a.get("URI"):
                audio.setdefault(a.get("GROUP-ID", ""), []).append(a)
        elif line.startswith("#EXT-X-STREAM-INF:"):
            a = attributes(line)
            uri = next((ln for ln in lines[i + 1:] if ln and not ln.startswith("#")), None)
            if uri is None:
                continue
            bw = int(a.get("BANDWIDTH", "0") or 0)
            if best is None or bw > best[0]:
                best = (bw, urljoin(base, uri), a.get("AUDIO"))
    if best is None:
        raise DownloadError("The stream's playlist had no video in it.")
    audio_url = None
    group = audio.get(best[2] or "", [])
    if group:
        pick = next((a for a in group if a.get("DEFAULT") == "YES"), group[0])
        audio_url = urljoin(base, pick["URI"])
    return best[1], audio_url


def parse_media(text: str, base: str) -> MediaPlaylist:
    seq = 0
    key_url: str | None = None
    key_iv: bytes | None = None
    init_url: str | None = None
    init_key: tuple[str | None, bytes | None] = (None, None)
    segments: list[Segment] = []
    for line in (ln.strip() for ln in text.splitlines()):
        if not line:
            continue
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            seq = int(line.split(":", 1)[1] or 0)
        elif line.startswith("#EXT-X-KEY:"):
            a = attributes(line)
            method = a.get("METHOD", "NONE")
            if method == "NONE":
                key_url, key_iv = None, None
            elif method == "AES-128":
                key_url = urljoin(base, a["URI"])
                iv = a.get("IV")
                key_iv = bytes.fromhex(iv[2:] if iv.lower().startswith("0x") else iv).rjust(16, b"\0") if iv else None
            else:
                raise DownloadError("This stream uses protection AniGUI can't save. You can still watch it.")
        elif line.startswith("#EXT-X-MAP:"):
            a = attributes(line)
            if "BYTERANGE" in a:
                raise DownloadError("This stream's format can't be saved yet. You can still watch it.")
            init_url = urljoin(base, a["URI"])
            init_key = (key_url, key_iv)
        elif line.startswith("#EXT-X-BYTERANGE"):
            raise DownloadError("This stream's format can't be saved yet. You can still watch it.")
        elif not line.startswith("#"):
            iv = key_iv if key_iv is not None else (seq + len(segments)).to_bytes(16, "big")
            segments.append(Segment(urljoin(base, line), key_url, iv if key_url else None))
    if not segments:
        raise DownloadError("The stream's playlist was empty.")
    return MediaPlaylist(segments, init_url, init_key)


# -- downloading ---------------------------------------------------------------------------------

class Downloader:
    """download(info, folder, name) -> Saved. progress(fraction 0..1) and cancelled() are
    called from the same (worker) thread."""

    def __init__(self, progress: Callable[[float], None] | None = None,
                 cancelled: Callable[[], bool] | None = None) -> None:
        self.progress = progress or (lambda _f: None)
        self.cancelled = cancelled or (lambda: False)
        self._keys: dict[str, bytes] = {}
        self._headers: dict[str, str] = {}
        self._done = 0
        self._total = 1

    def _check(self) -> None:
        if self.cancelled():
            raise Cancelled("Cancelled")

    def _get(self, url: str) -> bytes:
        last: Exception | None = None
        for attempt in range(TRIES):
            self._check()
            try:
                with http.open_stream(url, self._headers) as resp:
                    parts = []
                    while chunk := resp.read(CHUNK):
                        self._check()
                        parts.append(chunk)
                    return b"".join(parts)
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in (401, 403, 404, 410):
                    break
            except OSError as exc:
                last = exc
            time.sleep(min(4.0, 0.5 * 2 ** attempt))
        raise DownloadError(f"The video server stopped answering ({last}). Try again later.")

    def _text(self, url: str) -> str:
        return self._get(url).decode("utf-8", "replace")

    def _key(self, url: str) -> bytes:
        if url not in self._keys:
            key = self._get(url)
            if len(key) != 16:
                raise DownloadError("The stream's key didn't look right.")
            self._keys[url] = key
        return self._keys[url]

    def _tick(self) -> None:
        self._done += 1
        self.progress(min(1.0, self._done / max(1, self._total)))

    def _hls(self, playlist: MediaPlaylist, out) -> None:
        if playlist.init_url:
            data = self._get(playlist.init_url)
            k_url, k_iv = playlist.init_key
            if k_url:
                data = decrypt(self._key(k_url), k_iv or bytes(16), data)
            out.write(data)
        for seg in playlist.segments:
            data = self._get(seg.url)
            if seg.key_url:
                data = decrypt(self._key(seg.key_url), seg.iv or bytes(16), data)
            out.write(data)
            self._tick()

    def _direct(self, url: str, out) -> None:
        for attempt in range(TRIES):
            self._check()
            try:
                written = out.tell()
                headers = dict(self._headers)
                if written:
                    headers["Range"] = f"bytes={written}-"
                with http.open_stream(url, headers) as resp:
                    if written and resp.status != 206:
                        out.seek(0)
                        out.truncate()
                        written = 0
                    total = int(resp.headers.get("Content-Length") or 0) + written
                    while chunk := resp.read(CHUNK):
                        self._check()
                        out.write(chunk)
                        written += len(chunk)
                        if total:
                            self.progress(min(1.0, written / total))
                    return
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403, 404, 410):
                    raise DownloadError(f"The video server said no ({exc.code}).") from exc
            except OSError:
                pass
            time.sleep(min(4.0, 0.5 * 2 ** attempt))
        raise DownloadError("The video server stopped answering. Try again later.")

    def _playlist(self, url: str) -> tuple[str | None, str]:
        """(playlist text or None for a plain file, the final url)."""
        self._check()
        try:
            with http.open_stream(url, self._headers) as resp:
                head = resp.read(7)
                if head != b"#EXTM3U":
                    return None, resp.geturl()
                return (head + resp.read()).decode("utf-8", "replace"), resp.geturl()
        except OSError as exc:
            raise DownloadError(f"Couldn't reach the video server ({exc}).") from exc

    def download(self, info: StreamInfo, folder: Path, name: str) -> Saved:
        for link in (info.url, info.audio_url, info.subtitle_url):
            if link is not None and not is_web_url(link):
                raise DownloadError("The stream link didn't look right, so it wasn't saved.")
        self._headers = {"Referer": info.referrer} if info.referrer else {}
        folder.mkdir(parents=True, exist_ok=True)
        name = safe_name(name)
        parts: list[Path] = []
        try:
            text, final = self._playlist(info.url)
            audio_pl: MediaPlaylist | None = None
            audio_url = info.audio_url
            if text is None:
                ext = Path(urlparse(final).path).suffix.lower()
                video = folder / f"{name}{ext if ext in ('.mp4', '.mkv', '.ts') else '.mp4'}"
                parts.append(video)
                with open(video.with_name(video.name + ".part"), "wb") as out:
                    self._direct(final, out)
            else:
                if "#EXT-X-STREAM-INF" in text:
                    media_url, hls_audio = parse_master(text, final)
                    text = self._text(media_url)
                    final = media_url
                    if hls_audio and not audio_url:
                        audio_pl = parse_media(self._text(hls_audio), hls_audio)
                video_pl = parse_media(text, final)
                if audio_url:
                    a_text, a_final = self._playlist(audio_url)
                    audio_pl = parse_media(a_text, a_final) if a_text else None
                    if a_text is None:
                        audio_pl = MediaPlaylist([Segment(a_final, None, None)], None)
                self._total = len(video_pl.segments) + (len(audio_pl.segments) if audio_pl else 0)
                video = folder / f"{name}{'.mp4' if video_pl.init_url else '.ts'}"
                parts.append(video)
                with open(video.with_name(video.name + ".part"), "wb") as out:
                    self._hls(video_pl, out)
            audio = None
            if audio_pl is not None:
                audio = folder / f"{name} (audio){'.m4a' if audio_pl.init_url else '.ts'}"
                parts.append(audio)
                with open(audio.with_name(audio.name + ".part"), "wb") as out:
                    self._hls(audio_pl, out)
            elif audio_url and text is None:
                audio = folder / f"{name} (audio).m4a"
                parts.append(audio)
                with open(audio.with_name(audio.name + ".part"), "wb") as out:
                    self._direct(audio_url, out)
            subs = None
            if info.subtitle_url:
                ext = Path(urlparse(info.subtitle_url).path).suffix.lower()
                subs = folder / f"{name}{ext if ext in ('.vtt', '.ass', '.srt') else '.vtt'}"
                try:
                    data = self._get(info.subtitle_url)
                    subs.with_name(subs.name + ".part").write_bytes(data)
                    parts.append(subs)
                except DownloadError:
                    subs = None          # the episode is still worth keeping
            for p in parts:
                os.replace(p.with_name(p.name + ".part"), p)
            self.progress(1.0)
            return Saved(video, audio, subs)
        except BaseException:
            for p in parts:
                for q in (p, p.with_name(p.name + ".part")):
                    try:
                        q.unlink()
                    except OSError:
                        pass
            raise
