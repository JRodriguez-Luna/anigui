"""Starts IINA or mpv for a resolved stream, with mpv's IPC socket for tracking."""

from __future__ import annotations

import os
import subprocess
import tempfile

from .ani_cli import StreamInfo
from .env import child_env, find_player

INSTALL_HINT = "No video player found. Open Setup in AniGUI to install IINA."
PLAYER_NAMES = {"iina": "IINA", "mpv": "mpv"}


class PlayerError(RuntimeError):
    pass


def default_ipc_path() -> str:
    # macOS caps socket paths at 104 bytes; /tmp keeps it short and predictable.
    base = "/tmp" if os.path.isdir("/tmp") else tempfile.gettempdir()
    return os.path.join(base, f"anigui-{os.getuid()}-mpv.sock")


def build_player_command(kind: str, path: str, info: StreamInfo, title: str,
                         ipc_path: str | None = None, start: float | None = None) -> list[str]:
    """IINA takes mpv options with an --mpv- prefix; mpv takes them directly."""
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

        cmd = [path, "--no-stdin", "--keep-running"]
        if info.audio_url:
            cmd.append(f"--mpv-audio-files={esc(info.audio_url)}")
        if info.subtitle_url:
            cmd.append(f"--mpv-sub-files={esc(info.subtitle_url)}")
        cmd += [f"--mpv-{a[2:]}" if a.startswith("--") else a for a in info.extra_args]
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
    cmd += list(info.extra_args)
    cmd += [f"--{k}={v}" for k, v in opts]
    cmd.append(info.url)
    return cmd


class Player:
    def __init__(self, ipc_path: str | None = None) -> None:
        self.ipc_path = ipc_path or default_ipc_path()

    def available(self, preferred: str | None = None) -> tuple[str, str] | None:
        return find_player(None if preferred in (None, "", "auto") else preferred)

    def launch(self, info: StreamInfo, title: str | None = None, *, start: float | None = None,
               preferred: str | None = None, track: bool = True) -> str:
        """Start playback detached from AniGUI. Returns the player kind ("iina" or "mpv").

        If the chosen player isn't installed, the other one is used.
        """
        pref = None if preferred in (None, "", "auto") else preferred
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
