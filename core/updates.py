"""Once-a-day checks for newer ani-cli and AniGUI releases.

Results are cached in the Store so launching AniGUI repeatedly doesn't hit GitHub.
Network errors return None: an update check must never get in the way.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import __version__
from .ani_cli import is_supported
from .setup import Fetch, SetupError, _fetch, latest_ani_cli, parse_version

ANIGUI_RELEASES = "https://api.github.com/repos/JRodriguez-Luna/anigui/releases/latest"
CHECK_EVERY_S = 24 * 3600


@dataclass(frozen=True)
class AniCliUpdate:
    current: str
    latest: str
    compatible: bool       # same major.minor AniGUI is tested with
    script: bytes          # ready to install


@dataclass(frozen=True)
class AppUpdate:
    current: str
    latest: str
    url: str               # release page
    notes: str


def check_ani_cli(installed: str | None, store=None, fetch: Fetch = _fetch,
                  force: bool = False) -> AniCliUpdate | None:
    if not installed:
        return None
    key = "update:ani-cli"
    if store is not None and not force and store.cache_get(key):
        return None
    try:
        latest, script = latest_ani_cli(fetch)
    except SetupError:
        return None
    if store is not None:
        store.cache_put(key, latest, CHECK_EVERY_S)
    if parse_version(latest) <= parse_version(installed):
        return None
    return AniCliUpdate(installed, latest, is_supported(latest), script)


def check_anigui(store=None, fetch: Fetch = _fetch, force: bool = False,
                 current: str = __version__) -> AppUpdate | None:
    key = "update:anigui"
    if store is not None and not force and store.cache_get(key):
        return None
    try:
        release = json.loads(fetch(ANIGUI_RELEASES))
    except (SetupError, ValueError):
        return None
    if store is not None:
        store.cache_put(key, "checked", CHECK_EVERY_S)
    tag = str(release.get("tag_name", "")).lstrip("v")
    if not tag or release.get("draft") or release.get("prerelease"):
        return None
    if parse_version(tag) <= parse_version(current):
        return None
    return AppUpdate(current, tag, release.get("html_url", ""), release.get("body") or "")
