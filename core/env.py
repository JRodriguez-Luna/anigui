"""Locating external programs on macOS.

Apps launched from Finder or the Dock get a minimal PATH without Homebrew, so
every lookup here adds the Homebrew prefixes explicitly.
"""

from __future__ import annotations

import os
import platform
import shutil

_EXTRA_PATHS = ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"]

# Same preference order as ani-cli's dep_ch_failover for curl.
_CURL_CANDIDATES = ["curl_firefox135", "curl_chrome136", "curl_chrome116", "curl_ff117", "curl"]


def is_macos() -> bool:
    return platform.system() == "Darwin"


def search_path() -> str:
    parts = os.environ.get("PATH", "").split(os.pathsep)
    for extra in _EXTRA_PATHS:
        if extra not in parts:
            parts.append(extra)
    return os.pathsep.join(p for p in parts if p)


def which(name: str) -> str | None:
    if os.path.isabs(name):
        return name if os.access(name, os.X_OK) else None
    return shutil.which(name, path=search_path())


def find_curl() -> str:
    for name in _CURL_CANDIDATES:
        found = which(name)
        if found:
            return found
    raise FileNotFoundError("curl not found")


def find_player(preferred: str | None = None) -> tuple[str, str] | None:
    """Return (kind, path). `preferred` is "iina", "mpv", or None/"auto" for IINA then mpv."""
    found = {
        "iina": which("iina") or which("/Applications/IINA.app/Contents/MacOS/iina-cli"),
        "mpv": which("mpv") or which("/Applications/mpv.app/Contents/MacOS/mpv"),
    }
    if preferred in found:
        return (preferred, found[preferred]) if found[preferred] else None
    for kind in ("iina", "mpv"):
        if found[kind]:
            return kind, found[kind]
    return None


def child_env(**overrides: str) -> dict[str, str]:
    """Environment for subprocesses: Homebrew on PATH, no terminal assumptions."""
    env = dict(os.environ)
    env["PATH"] = search_path()
    env["TERM"] = "dumb"
    env.update(overrides)
    return env
