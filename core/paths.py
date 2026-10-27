"""Standard macOS locations for AniGUI data. Override the root with ANIGUI_HOME (tests use this)."""

from __future__ import annotations

import os
from pathlib import Path


def _root(kind: str) -> Path:
    override = os.environ.get("ANIGUI_HOME")
    if override:
        return Path(override) / kind
    home = Path.home()
    if kind == "data":
        return home / "Library" / "Application Support" / "AniGUI"
    return home / "Library" / "Caches" / "AniGUI"


def data_dir() -> Path:
    path = _root("data")
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = _root("cache")
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_dir() / "anigui.db"


def covers_dir() -> Path:
    path = cache_dir() / "covers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ani_cli_history_file() -> Path:
    """Same resolution order as ani-cli: ANI_CLI_HIST_DIR, then XDG_STATE_HOME, then ~/.local/state."""
    hist_dir = os.environ.get("ANI_CLI_HIST_DIR")
    if not hist_dir:
        state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
        hist_dir = os.path.join(state, "ani-cli")
    return Path(hist_dir) / "ani-hsts"
