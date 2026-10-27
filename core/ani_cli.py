"""Running ani-cli headlessly to resolve stream links.

How it works: ANI_CLI_PLAYER points at a small shim whose path contains "mpv".
ani-cli then calls it exactly like a real mpv (URL, Referer, audio, subtitles,
ani-skip flags), and the shim writes those arguments to a capture file instead
of playing anything. `--exit-after-play` makes ani-cli exit right after, so it
never opens its interactive fzf menu.

This module has no Qt dependency; cli_bridge.py wraps it in QProcess for the UI.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .env import child_env, find_curl, find_player, which
from .hianime import normalize_query

SUPPORTED_VERSIONS = ("5.1",)  # major.minor prefixes this parser was verified against
DEFAULT_TIMEOUT = 60.0

_SHIM_SOURCE = Path(__file__).parent / "bin" / "anigui-mpv-shim"
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[78]|\r")


class AniCliError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolveRequest:
    query: str             # the search the user ran (normalized before use)
    index: int             # 1-based position in that search's results
    episode: str           # episode number as listed, e.g. "1" or "12.5"
    dub: bool = False
    quality: str = "best"  # best | worst | 1080 | 720 | 480 ...
    skip_intro: bool = False


@dataclass(frozen=True)
class StreamInfo:
    url: str
    referrer: str | None
    title: str | None
    audio_url: str | None = None
    subtitle_url: str | None = None
    extra_args: tuple[str, ...] = field(default_factory=tuple)  # e.g. ani-skip flags


# -- Discovery ------------------------------------------------------------------

def find_ani_cli() -> str:
    path = which("ani-cli")
    if not path:
        raise AniCliError("ani-cli not found. Install it with: brew install ani-cli")
    return path


def ani_cli_version(path: str | None = None) -> str:
    path = path or find_ani_cli()
    # ANI_CLI_PLAYER=debug: without it ani-cli dies on "no player found" before -V runs.
    proc = subprocess.run(
        [path, "-V"], capture_output=True, text=True, timeout=15,
        stdin=subprocess.DEVNULL, env=child_env(ANI_CLI_PLAYER="debug"),
    )
    version = clean_output(proc.stdout).strip().splitlines()
    if proc.returncode != 0 or not version:
        raise AniCliError(f"Could not read ani-cli version: {error_message(proc.stdout, proc.stderr)}")
    return version[-1].strip()


def is_supported(version: str) -> bool:
    return any(version == v or version.startswith(v + ".") for v in SUPPORTED_VERSIONS)


def install_shim() -> str:
    """Copy the shim somewhere whose path has no spaces.

    ani-cli expands $player_function unquoted, so a path with spaces would split.
    """
    candidates = [Path.home() / ".local" / "share" / "anigui" / "bin", Path(tempfile.gettempdir()) / "anigui-bin"]
    for directory in candidates:
        target = directory / "anigui-mpv-shim"
        if any(ch.isspace() for ch in str(target)) or "flatpak" in str(target):
            continue
        directory.mkdir(parents=True, exist_ok=True)
        src = _SHIM_SOURCE.read_bytes()
        if not target.exists() or target.read_bytes() != src:
            target.write_bytes(src)
        target.chmod(0o755)
        return str(target)
    raise AniCliError("No space-free location available for the player shim")


def doctor() -> list[tuple[str, bool, str]]:
    """Startup self-test. Returns (check, ok, detail) rows."""
    rows: list[tuple[str, bool, str]] = []
    try:
        path = find_ani_cli()
        rows.append(("ani-cli", True, path))
        try:
            version = ani_cli_version(path)
            ok = is_supported(version)
            detail = version if ok else f"{version} (tested with {', '.join(SUPPORTED_VERSIONS)}.x; may still work)"
            rows.append(("ani-cli version", ok, detail))
        except AniCliError as exc:
            rows.append(("ani-cli version", False, str(exc)))
    except AniCliError as exc:
        rows.append(("ani-cli", False, str(exc)))

    try:
        curl = find_curl()
        impersonating = not os.path.basename(curl) == "curl"
        rows.append(("curl", True, curl + ("" if impersonating else " (plain curl; install curl-impersonate if Cloudflare blocks)")))
    except FileNotFoundError as exc:
        rows.append(("curl", False, str(exc)))

    rows.append(("fzf (required by ani-cli)", bool(which("fzf")), which("fzf") or "brew install fzf"))
    player = find_player()
    rows.append(("player", bool(player), f"{player[0]} at {player[1]}" if player else "brew install --cask iina  (or: brew install mpv)"))
    rows.append(("ani-skip (optional)", bool(which("ani-skip")), which("ani-skip") or "not installed; skip-intro disabled"))
    return rows


# -- Command building and parsing ----------------------------------------------

def build_command(
    req: ResolveRequest, ani_cli: str, shim: str, capture_path: str
) -> tuple[list[str], dict[str, str]]:
    query = normalize_query(req.query).lstrip("-").strip()
    if not query:
        raise AniCliError("Empty search query")
    if req.index < 1:
        raise AniCliError("Result index must be 1 or higher")

    args = [
        "-S", str(req.index),
        "-e", req.episode,
        "-q", req.quality,
        "--exit-after-play",
    ]
    if req.dub:
        args.append("--dub")
    if req.skip_intro:
        args.append("--skip")
    args.append(query)

    env = child_env(
        ANI_CLI_PLAYER=shim,
        ANIGUI_CAPTURE=capture_path,
        ANI_CLI_LOG="0",
        ANI_CLI_EXACT="0",
        ANI_CLI_PLAYER_FLAGS="",
        ANI_CLI_SKIP_INTRO="0",
    )
    env.pop("ANI_CLI_MODE", None)
    env.pop("ANI_CLI_QUALITY", None)
    return [ani_cli, *args], env


def parse_capture(data: bytes) -> StreamInfo:
    args = [a.decode("utf-8", "replace") for a in data.split(b"\0") if a]
    if not args:
        raise AniCliError("ani-cli did not hand a stream to the player")

    url = args[-1]
    referrer = title = audio = subs = None
    extra: list[str] = []
    for arg in args[:-1]:
        if arg.startswith("--referrer="):
            referrer = arg.split("=", 1)[1] or None
        elif arg.startswith("--force-media-title="):
            title = arg.split("=", 1)[1] or None
        elif arg.startswith("--audio-file="):
            audio = arg.split("=", 1)[1] or None
        elif arg.startswith("--sub-file="):
            subs = arg.split("=", 1)[1] or None
        else:
            extra.append(arg)

    if not url.startswith(("http://", "https://")):
        raise AniCliError(f"Unexpected stream URL from ani-cli: {url[:120]}")
    return StreamInfo(url, referrer, title, audio, subs, tuple(extra))


def clean_output(text: str) -> str:
    return _ANSI.sub("", text)


def error_message(stdout: str, stderr: str, code: int | None = None) -> str:
    for stream in (stderr, stdout):
        lines = [ln.strip() for ln in clean_output(stream).splitlines() if ln.strip()]
        lines = [ln for ln in lines if not ln.startswith("tput:")]
        if lines:
            return lines[-1]
    return f"ani-cli exited with code {code}" if code is not None else "ani-cli failed"


# -- Synchronous resolve (used by tests and the terminal tool) -----------------

def resolve_stream(req: ResolveRequest, timeout: float = DEFAULT_TIMEOUT) -> StreamInfo:
    ani_cli = find_ani_cli()
    shim = install_shim()
    fd, capture = tempfile.mkstemp(prefix="anigui-", suffix=".args")
    os.close(fd)
    try:
        cmd, env = build_command(req, ani_cli, shim, capture)
        try:
            proc = subprocess.run(
                cmd, env=env, capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise AniCliError(f"ani-cli timed out after {timeout:.0f}s") from exc

        data = Path(capture).read_bytes()
        if proc.returncode != 0 or not data:
            raise AniCliError(error_message(proc.stdout, proc.stderr, proc.returncode))
        return parse_capture(data)
    finally:
        try:
            os.unlink(capture)
        except OSError:
            pass


__all__ = [
    "AniCliError", "ResolveRequest", "StreamInfo", "SUPPORTED_VERSIONS",
    "find_ani_cli", "ani_cli_version", "is_supported", "install_shim", "doctor",
    "build_command", "parse_capture", "clean_output", "error_message", "resolve_stream",
]
