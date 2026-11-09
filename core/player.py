"""Starts IINA or mpv for a resolved stream, with mpv's IPC socket for tracking."""

from __future__ import annotations

import os
import subprocess
import tempfile

from . import privacy
from .ani_cli import StreamInfo, is_playable, is_web_url
from .env import child_env, find_player

INSTALL_HINT = "No video player found. Open Setup in AniGUI to install IINA."
PLAYER_NAMES = {"anigui": "AniGUI", "iina": "IINA", "mpv": "mpv"}


class PlayerError(RuntimeError):
    pass


_IPC_DIR: str | None = None


def default_ipc_path() -> str:
    """The player's control socket, in a folder only this user can open.

    macOS caps socket paths at 104 bytes, so it's under /tmp (short) but in a
    fresh mkdtemp folder (mode 0700): nobody else can create or connect to it.
    """
    global _IPC_DIR
    if _IPC_DIR is None or not os.path.isdir(_IPC_DIR):
        base = "/tmp" if os.path.isdir("/tmp") else tempfile.gettempdir()
        _IPC_DIR = tempfile.mkdtemp(prefix="anigui-", dir=base)   # created 0700
    return os.path.join(_IPC_DIR, "mpv.sock")


def build_player_command(kind: str, path: str, info: StreamInfo, title: str,
                         ipc_path: str | None = None, start: float | None = None) -> list[str]:
    """IINA takes mpv options with an --mpv- prefix; mpv takes them directly.

    Every link is checked again here (http(s) only), so nothing from a website can
    be read by the player as an option.
    """
    for link in (info.url, info.audio_url, info.subtitle_url):
        if link is not None and not is_playable(link):
            raise PlayerError("The stream link didn't look right, so it wasn't opened.")
    if info.referrer is not None and not is_web_url(info.referrer):
            raise PlayerError("The stream link didn't look right, so it wasn't opened.")
    opts: list[tuple[str, str]] = []
    if info.referrer:
        opts.append(("referrer", info.referrer))
    if ipc_path:
        opts.append(("input-ipc-server", ipc_path))
    if start:
        opts.append(("start", f"{start:.0f}"))
    opts.append(("force-media-title", title))

    if kind == "iina":
        def esc(value: str) -> str:  # mpv splits file lists on ':'
            return value.replace(":", "\\:")

        # keep-open: stay on the last frame at the end, so auto-next loads into this window
        cmd = [path, "--no-stdin", "--keep-running", "--mpv-keep-open=yes"]
        if info.audio_url:
            cmd.append(f"--mpv-audio-files={esc(info.audio_url)}")
        if info.subtitle_url:
            cmd.append(f"--mpv-sub-files={esc(info.subtitle_url)}")
        if info.subtitle_url and not info.show_subtitles:
            cmd.append("--mpv-sid=no")   # loaded (Subtitles menu) but off
        cmd += [f"--mpv-{k}={v}" for k, v in opts]
        cmd.append(info.url)
        return cmd

    cmd = [path]
    if ipc_path:
        cmd += ["--idle=yes", "--force-window=yes"]  # stay open after EOF so auto-next can load
    if info.audio_url:
        cmd.append(f"--audio-file={info.audio_url}")
    if info.subtitle_url:
        cmd.append(f"--sub-file={info.subtitle_url}")
        if not info.show_subtitles:
            cmd.append("--sid=no")       # loaded (press v / j to show) but off
    cmd += [f"--{k}={v}" for k, v in opts]
    cmd += ["--", info.url]   # mpv: everything after -- is a file, never an option
    return cmd


def embedded_options(info: StreamInfo, title: str, ipc_path: str | None = None,
                     start: float | None = None) -> tuple[dict[str, str], str]:
    """libmpv options and the link, for playing inside AniGUI's window (same checks and the
    same choices as the mpv command line)."""
    for link in (info.url, info.audio_url, info.subtitle_url):
        if link is not None and not is_playable(link):
            raise PlayerError("The stream link didn't look right, so it wasn't opened.")
    if info.referrer is not None and not is_web_url(info.referrer):
            raise PlayerError("The stream link didn't look right, so it wasn't opened.")
    opts = {
        "vo": "libmpv", "hwdec": "auto-safe", "idle": "yes", "keep-open": "no",
        "input-default-bindings": "no", "osc": "no", "osd-level": "0",
        "force-media-title": title, "volume-max": "100",
    }
    if info.referrer:
        opts["referrer"] = info.referrer
    if ipc_path:
        opts["input-ipc-server"] = ipc_path
    if start:
        opts["start"] = f"{start:.0f}"
    return opts, info.url


def embedded_tracks(info: StreamInfo) -> list[tuple[str, str, str]]:
    """Separate audio and subtitle links, added once the video has loaded (as commands, so
    a ':' in a link is never read as a list separator): (command, url, flag)."""
    tracks = []
    if info.audio_url:
        tracks.append(("audio-add", info.audio_url, "select"))
    if info.subtitle_url:
        tracks.append(("sub-add", info.subtitle_url, "select" if info.show_subtitles else "auto"))
    return tracks


class Player:
    def __init__(self, ipc_path: str | None = None) -> None:
        self.ipc_path = ipc_path or default_ipc_path()
        # Set by the window: embed(options, url) starts the built-in player; None = not available
        self.embed = None
        self.embed_available = lambda: False

    def available(self, preferred: str | None = None) -> tuple[str, str] | None:
        return find_player(None if preferred in (None, "", "auto") else preferred)

    def launch(self, info: StreamInfo, title: str | None = None, *, start: float | None = None,
               preferred: str | None = None, track: bool = True) -> str:
        """Start playback detached from AniGUI. Returns the player kind ("iina" or "mpv").

        If the chosen player isn't installed, the other one is used.
        """
        privacy.LOG.record(info.url)
        if preferred == "anigui" and self.embed is not None and self.embed_available():
            ipc = self.ipc_path if track else None
            if ipc and os.path.exists(ipc):
                try:
                    os.unlink(ipc)
                except OSError:
                    pass
            opts, url = embedded_options(info, title or info.title or "AniGUI", ipc, start)
            self.embed(opts, url, embedded_tracks(info))
            return "anigui"
        pref = None if preferred in (None, "", "auto", "anigui") else preferred
        found = find_player(pref) or find_player(None)
        if not found:
            raise PlayerError(INSTALL_HINT)
        kind, path = found
        ipc = self.ipc_path if track else None
        if ipc and os.path.exists(ipc):
            try:
                os.unlink(ipc)  # stale socket from an old session
            except OSError:
                pass
        cmd = build_player_command(kind, path, info, title or info.title or "AniGUI", ipc, start)
        try:
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True, env=child_env())
        except OSError as exc:
            raise PlayerError(f"Could not start {kind}: {exc}") from exc
        return kind
