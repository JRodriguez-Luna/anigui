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
    dmg_url: str | None = None       # the installer, for Update Now
    sha256: str | None = None        # from GitHub's asset digest, if it has one
    sha256_url: str | None = None    # or the .sha256 file published next to the .dmg

    @property
    def installable(self) -> bool:
        """Update Now needs the .dmg and a checksum to verify it against."""
        return bool(self.dmg_url and (self.sha256 or self.sha256_url))


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
    assets = release.get("assets") or []
    dmg = next((a for a in assets if str(a.get("name", "")).endswith(".dmg")), None)
    digest = str((dmg or {}).get("digest") or "")
    checksum = next((a for a in assets if dmg and a.get("name") == f"{dmg.get('name')}.sha256"), None)
    return AppUpdate(current, tag, release.get("html_url", ""), release.get("body") or "",
                     dmg_url=(dmg or {}).get("browser_download_url"),
                     sha256=digest.removeprefix("sha256:") if digest.startswith("sha256:") else None,
                     sha256_url=(checksum or {}).get("browser_download_url"))
