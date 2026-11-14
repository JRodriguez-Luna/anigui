"""Everything AniGUI needs outside itself, installed without Homebrew or Terminal.

- ani-cli: AniGUI keeps its own copy of the ani-cli script (one shell file that
  only needs tools every Mac has). The bundled pin is checksum-verified.
- Player: IINA is downloaded from its official GitHub release and copied into
  Applications. IINA is notarized by its developer, so macOS accepts it.
- Network: checks whether hianime is reachable, and tells "blocked here" apart
  from "offline" and from Cloudflare's bot check.

Functions block; call them from worker threads (core/tasks.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import http, paths
from .env import find_player
from .hianime import NETWORK_EXIT_CODES, SEARCH_URL, HianimeClient, parse_search

# The ani-cli build AniGUI is tested against (CI runs the suite on this exact file).
ANI_CLI_PIN_VERSION = "5.1.8"
ANI_CLI_PIN_COMMIT = "8527f185a12c6b5d0247a30b2217000dd65457fe"
ANI_CLI_PIN_SHA256 = "24ada974b567789da4ea51f9f92ec5b975b43fc0e999543f9053bcf5a628105c"
ANI_CLI_RAW = "https://raw.githubusercontent.com/pystardust/ani-cli/{ref}/ani-cli"

IINA_RELEASES = "https://api.github.com/repos/iina/iina/releases/latest"
IINA_RELEASES_WEB = "https://github.com/iina/iina/releases/latest"
IINA_ASSETS_WEB = "https://github.com/iina/iina/releases/expanded_assets/{tag}"
IINA_SITE = "https://iina.io/"
# IINA's Apple Developer team. Setup refuses an IINA.app signed by anyone else.
# (The release build prints the team of the IINA it installs, so a change shows up.)
IINA_TEAM_IDS = {"67CQ77V27R"}
WARP_URL = "https://one.one.one.one/"
CONTROL_URL = "https://www.apple.com/library/test/success.html"
PROBE_QUERY = "one+piece"   # always has results; a block page never parses as results

_VERSION_LINE = re.compile(r'^version_number="([^"]+)"', re.MULTILINE)

Fetch = Callable[[str], bytes]
Progress = Callable[[str], None]


class SetupError(RuntimeError):
    pass


def _fetch(url: str) -> bytes:
    headers = {"Accept": "application/vnd.github+json"} if "api.github.com" in url else {}
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:  # CI: shared runners hit the anonymous rate limit
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = http.request(url, headers=headers, timeout=60)
    except OSError as exc:
        raise SetupError(f"Couldn't download {url}: {exc}") from exc
    if resp.status != 200:
        raise SetupError(f"Download failed (HTTP {resp.status}): {url}")
    return resp.body


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text)
    return tuple(int(n) for n in nums[:3]) or (0,)


def script_version(script: bytes | str) -> str | None:
    text = script.decode("utf-8", "replace") if isinstance(script, bytes) else script
    m = _VERSION_LINE.search(text)
    return m.group(1) if m else None


# -- ani-cli --------------------------------------------------------------------------

def managed_ani_cli() -> Path:
    return paths.bin_dir() / "ani-cli"


def managed_ani_cli_version() -> str | None:
    path = managed_ani_cli()
    if not path.is_file():
        return None
    try:
        return script_version(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None


def install_ani_cli(script: bytes | None = None, *, fetch: Fetch = _fetch,
                    expected_sha256: str | None = None) -> str:
    """Install ani-cli into AniGUI's own bin folder. Returns the installed version.

    With no `script`, downloads the pinned, checksum-verified build.
    """
    if script is None:
        script = fetch(ANI_CLI_RAW.format(ref=ANI_CLI_PIN_COMMIT))
        expected_sha256 = ANI_CLI_PIN_SHA256
    if expected_sha256 and hashlib.sha256(script).hexdigest() != expected_sha256:
        raise SetupError("The downloaded ani-cli didn't match its checksum, so it wasn't installed.")
    version = script_version(script)
    if not script.startswith(b"#!") or not version:
        raise SetupError("The download doesn't look like the ani-cli script.")

    target = managed_ani_cli()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".ani-cli-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(script)
        os.chmod(tmp, 0o755)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return version


ANI_CLI_RELEASES = "https://api.github.com/repos/pystardust/ani-cli/releases/latest"
ANI_CLI_RELEASES_WEB = "https://github.com/pystardust/ani-cli/releases/latest"
_ANI_TAG_IN_PAGE = re.compile(r"/pystardust/ani-cli/releases/tag/(v?[\d.]+)")


def latest_ani_cli_tag(fetch: Fetch = _fetch) -> str:
    """ani-cli's newest official release tag (API first, the release page if rate-limited)."""
    try:
        tag = str(json.loads(fetch(ANI_CLI_RELEASES)).get("tag_name") or "")
        if tag:
            return tag
    except (SetupError, ValueError):
        pass
    m = _ANI_TAG_IN_PAGE.search(fetch(ANI_CLI_RELEASES_WEB).decode("utf-8", "replace"))
    if not m:
        raise SetupError("Couldn't find ani-cli's latest release.")
    return m.group(1)


def ensure_pinned_ani_cli(fetch: Fetch = _fetch) -> str | None:
    """ani-cli updates arrive inside (signed) AniGUI updates: each AniGUI release pins a
    tested, checksum-verified ani-cli. If AniGUI's own copy is older than this build's
    pin, install the pin. Returns the new version, or None if nothing changed."""
    current = managed_ani_cli_version()
    if current is None or parse_version(current) >= parse_version(ANI_CLI_PIN_VERSION):
        return None
    return install_ani_cli(fetch=fetch)


def latest_ani_cli(fetch: Fetch = _fetch) -> tuple[str, bytes]:
    """The script from ani-cli's newest *tagged release* (never the moving main branch).

    The version written inside the script must match the release tag.
    """
    tag = latest_ani_cli_tag(fetch)
    if not re.fullmatch(r"v?\d+(\.\d+){1,3}", tag):
        raise SetupError(f"ani-cli's latest release has an unexpected name ({tag[:40]}).")
    script = fetch(ANI_CLI_RAW.format(ref=tag))
    version = script_version(script)
    tag_parts = parse_version(tag)
    if not version or parse_version(version)[:len(tag_parts)] != tag_parts or not script.startswith(b"#!"):
        raise SetupError(f"The ani-cli script for {tag} doesn't match its release, so it wasn't offered.")
    return version, script


# -- Player -----------------------------------------------------------------------------

def applications_dir() -> Path:
    system = Path("/Applications")
    return system if os.access(system, os.W_OK) else Path.home() / "Applications"


def install_iina(*, fetch: Fetch = _fetch, run=subprocess.run, progress: Progress = lambda _m: None) -> Path:
    """Download the latest IINA release and copy IINA.app into Applications."""
    progress("Finding the latest IINA…")
    tag, dmg_url = latest_iina(fetch)

    progress(f"Downloading IINA {tag}…".replace("  ", " "))
    work = Path(tempfile.mkdtemp(prefix="anigui-iina-"))
    mount = work / "mnt"
    mount.mkdir()
    dmg = work / "IINA.dmg"
    try:
        dmg.write_bytes(fetch(dmg_url))
        progress("Installing IINA…")
        attach = run(["hdiutil", "attach", str(dmg), "-nobrowse", "-readonly", "-mountpoint", str(mount)],
                     capture_output=True, text=True)
        if attach.returncode != 0:
            raise SetupError(f"Couldn't open the IINA download: {attach.stderr.strip()[:200]}")
        try:
            app = next((p for p in mount.iterdir() if p.suffix == ".app"), None)
            if app is None:
                raise SetupError("The IINA download didn't contain IINA.app.")
            progress("Checking IINA's signature…")
            verify_iina(app, run)
            dest_dir = applications_dir()
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / app.name
            if dest.exists():
                shutil.rmtree(dest)
            copy = run(["ditto", str(app), str(dest)], capture_output=True, text=True)
            if copy.returncode != 0:
                raise SetupError(f"Couldn't copy IINA into {dest_dir}: {copy.stderr.strip()[:200]}")
        finally:
            run(["hdiutil", "detach", str(mount), "-quiet"], capture_output=True, text=True)
        return dest
    finally:
        shutil.rmtree(work, ignore_errors=True)


def signing_team(app: Path, run=subprocess.run) -> str | None:
    """The Apple Developer team that signed an app, from `codesign -dv`."""
    info = run(["codesign", "-dv", "--verbose=2", str(app)], capture_output=True, text=True)
    m = re.search(r"^TeamIdentifier=(\w+)", (info.stderr or "") + (info.stdout or ""), re.MULTILINE)
    return m.group(1) if m else None


def verify_iina(app: Path, run=subprocess.run) -> None:
    """IINA.app must be intact, signed by IINA's own team, and accepted by Gatekeeper."""
    check = run(["codesign", "--verify", "--deep", "--strict", str(app)], capture_output=True, text=True)
    if check.returncode != 0:
        raise SetupError("The IINA download's signature is broken, so it wasn't installed. You can download "
                         "IINA yourself from iina.io.")
    team = signing_team(app, run)
    if team not in IINA_TEAM_IDS:
        raise SetupError(f"The IINA download is signed by someone else (team {team or 'none'}), so it wasn't "
                         "installed. You can download IINA yourself from iina.io.")
    gate = run(["spctl", "--assess", "--type", "execute", "-vv", str(app)], capture_output=True, text=True)
    verdict = (gate.stderr or "") + (gate.stdout or "")
    if gate.returncode != 0 and "override" not in verdict:   # "override": Gatekeeper is switched off here
        raise SetupError("macOS Gatekeeper didn't accept the IINA download, so it wasn't installed. You can "
                         "download IINA yourself from iina.io.")


_TAG_IN_PAGE = re.compile(r"/iina/iina/releases/(?:expanded_assets|tag)/([\w.\-]+)")
_DMG_IN_PAGE = re.compile(r'href="(/iina/iina/releases/download/[^"]+\.dmg)"')


def latest_iina(fetch: Fetch = _fetch) -> tuple[str, str]:
    """(tag, .dmg URL) of IINA's latest release.

    GitHub's API first. It allows 60 anonymous requests an hour per address, so if
    it refuses, read the same release from GitHub's web pages instead.
    """
    try:
        release = json.loads(fetch(IINA_RELEASES))
        dmg = next((a["browser_download_url"] for a in release.get("assets", [])
                    if a.get("name", "").endswith(".dmg")), None)
        if dmg:
            return str(release.get("tag_name", "")), dmg
    except (SetupError, ValueError, KeyError):
        pass
    return latest_iina_web(fetch)


def latest_iina_web(fetch: Fetch = _fetch) -> tuple[str, str]:
    try:
        page = fetch(IINA_RELEASES_WEB).decode("utf-8", "replace")      # redirects to the newest tag
        m = _TAG_IN_PAGE.search(page)
        if not m:
            raise SetupError("Couldn't find IINA's latest release.")
        tag = m.group(1)
        assets = fetch(IINA_ASSETS_WEB.format(tag=tag)).decode("utf-8", "replace")
    except SetupError as exc:
        raise SetupError(f"{exc} You can also download IINA yourself from iina.io.") from exc
    dmg = _DMG_IN_PAGE.search(assets)
    if not dmg:
        raise SetupError("IINA's latest release has no .dmg to install. You can download it from iina.io.")
    return tag, "https://github.com" + dmg.group(1)


# -- Network ----------------------------------------------------------------------------

@dataclass(frozen=True)
class NetworkStatus:
    state: str     # ok | blocked | cloudflare | offline
    message: str

    @property
    def ok(self) -> bool:
        return self.state == "ok"


def check_network(client: HianimeClient | None = None,
                  control: Callable[[], bool] | None = None,
                  stream_probe: Callable[[HianimeClient, list], str | None] | None = None) -> NetworkStatus:
    """Search first; then resolve a real episode and load its stream.

    Blocks can hit any hop: hianime itself, its video (embed) server, or the video CDN.
    """
    client = client or HianimeClient()
    # A real search, counted: an internet provider's "this site is blocked" page can
    # mention hianime, but it never contains search results.
    r = client.fetch(SEARCH_URL.format(PROBE_QUERY))
    body = r.body[:20000].lower()
    if "just a moment" in body:
        return NetworkStatus("cloudflare", "hianime answered with Cloudflare's bot check. Searches may fail until "
                                           "you install curl-impersonate (brew install curl-impersonate).")
    results = parse_search(r.body) if r.curl_exit == 0 and r.status and 200 <= r.status < 300 else []
    if not results:
        online = (control or _internet_ok)()
        if not online:
            return NetworkStatus("offline", "You seem to be offline. Check your internet connection.")
        if r.curl_exit in NETWORK_EXIT_CODES or r.status in (None, 403, 451) or r.curl_exit == 0:
            return NetworkStatus("blocked", "hianime is blocked on this network. Some internet providers block it; "
                                            "a VPN such as Cloudflare WARP gets around that.")
        return NetworkStatus("blocked", f"hianime didn't respond normally (HTTP {r.status}).")

    problem = (stream_probe or stream_check)(client, results)
    if problem == SKIPPED:
        return NetworkStatus("ok", "Search works. Video playback is tested once ani-cli is installed.")
    if problem:
        return NetworkStatus("blocked", problem)
    return NetworkStatus("ok", "hianime and its video servers are reachable.")


SKIPPED = "skipped"


def stream_check(client: HianimeClient, results: list) -> str | None:
    """Resolve the first episode of a search result with ani-cli and load its playlist.

    Returns None when everything loads, SKIPPED when it can't be tested (no ani-cli,
    no episodes), or a message naming the blocked server.
    """
    from .ani_cli import AniCliError, ResolveRequest, blocked_message, find_ani_cli, resolve_stream

    try:
        find_ani_cli()
    except AniCliError:
        return SKIPPED
    first = results[0]
    try:
        episodes = client.episodes(first.anime_id)
    except Exception:  # noqa: BLE001 - search worked, so don't call this a block
        return SKIPPED
    if not episodes:
        return SKIPPED
    try:
        info = resolve_stream(ResolveRequest(PROBE_QUERY.replace("+", " "), first.index, episodes[0].number),
                              timeout=45)
    except AniCliError as exc:
        message = str(exc)
        return message if "VPN" in message else SKIPPED
    playlist = client.fetch(info.url, info.referrer)
    # Only "no answer at all" (or a refusal) counts as a block; any other HTTP reply
    # means the server is reachable, which is what this check is about.
    if playlist.curl_exit in NETWORK_EXIT_CODES or playlist.status in (403, 451) or (
            playlist.curl_exit != 0 and playlist.status is None):
        return blocked_message(info.url).replace("hianime's video server", "the video stream server")
    return None


def _internet_ok() -> bool:
    try:
        return http.request(CONTROL_URL, timeout=8).status == 200
    except OSError:
        return False


# -- Overall status ---------------------------------------------------------------------

@dataclass(frozen=True)
class SetupStatus:
    ani_cli_path: str | None
    ani_cli_version: str | None
    ani_cli_managed: bool
    ani_cli_supported: bool
    player: tuple[str, str] | None
    iina: bool = False

    @property
    def ready(self) -> bool:
        return bool(self.ani_cli_path and self.ani_cli_supported and self.player)


def current_status() -> SetupStatus:
    from .ani_cli import AniCliError, ani_cli_version, find_ani_cli, is_supported

    path = version = None
    try:
        path = find_ani_cli()
        version = ani_cli_version(path)
    except AniCliError:
        pass
    managed = bool(path) and Path(path) == managed_ani_cli()
    return SetupStatus(path, version, managed, bool(version and is_supported(version)),
                       find_player() or (("anigui", "built-in") if builtin_player() else None),
                       bool(find_player("iina")))


def builtin_player() -> bool:
    """AniGUI's own player (libmpv inside the app, or IINA's / Homebrew's). Mac only."""
    if sys.platform != "darwin":
        return False
    from . import libmpv
    try:
        libmpv.load()
        return True
    except libmpv.LibMpvError:
        return False
