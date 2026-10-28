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
ANI_CLI_PIN_VERSION = "5.1.6"
ANI_CLI_PIN_COMMIT = "0301d67d5768d332b049821a30082ad43d9a215a"
ANI_CLI_PIN_SHA256 = "585ecc18d36104053d55ebabde905af207ca12cca19c43d3457920925f3959be"
ANI_CLI_RAW = "https://raw.githubusercontent.com/pystardust/ani-cli/{ref}/ani-cli"

IINA_RELEASES = "https://api.github.com/repos/iina/iina/releases/latest"
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


def latest_ani_cli(fetch: Fetch = _fetch) -> tuple[str, bytes]:
    """The current ani-cli script on GitHub (what `ani-cli -U` would install)."""
    script = fetch(ANI_CLI_RAW.format(ref="master"))
    version = script_version(script)
    if not version:
        raise SetupError("Couldn't read the latest ani-cli version.")
    return version, script


# -- Player -----------------------------------------------------------------------------

def applications_dir() -> Path:
    system = Path("/Applications")
    return system if os.access(system, os.W_OK) else Path.home() / "Applications"


def install_iina(*, fetch: Fetch = _fetch, run=subprocess.run, progress: Progress = lambda _m: None) -> Path:
    """Download the latest IINA release and copy IINA.app into Applications."""
    progress("Finding the latest IINA…")
    release = json.loads(fetch(IINA_RELEASES))
    dmg_url = next((a["browser_download_url"] for a in release.get("assets", [])
                    if a.get("name", "").endswith(".dmg")), None)
    if not dmg_url:
        raise SetupError("IINA's latest release has no .dmg to install.")

    progress(f"Downloading IINA {release.get('tag_name', '')}…".replace("  ", " "))
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
    return SetupStatus(path, version, managed, bool(version and is_supported(version)), find_player(),
                       bool(find_player("iina")))
