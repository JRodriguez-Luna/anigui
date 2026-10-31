"""Update Now: download the new AniGUI, verify it, swap it in, restart.

Safe by construction:
- The .dmg must match the SHA-256 published with the release, or nothing is touched.
- The new app is copied next to the old one first and checked (code signature,
  version); only then are the two swapped with renames on the same disk.
- If the swap fails half way, the old app is put back.
- AniGUI downloads the file itself, so macOS doesn't mark it as "downloaded from
  the internet", and the updated app opens without the Gatekeeper prompt.

Anything that can't be done (app not in a writable folder, running translocated
from Downloads, no checksum) means `supported()` says no, and the UI falls back
to opening the release page.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

from . import http
from .setup import SetupError

Progress = Callable[[int, int], None]     # bytes done, total (0 if unknown)
Run = Callable[..., subprocess.CompletedProcess]


class UpdateError(RuntimeError):
    pass


class Cancelled(UpdateError):
    pass


def running_app(executable: str | None = None) -> Path | None:
    """The .app bundle AniGUI is running from, or None when not running as an app."""
    exe = Path(executable or sys.executable)
    if not getattr(sys, "frozen", False) and executable is None:
        return None
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent
    return None


def supported(app: Path | None) -> tuple[bool, str]:
    """(can Update Now work here, why not)."""
    if app is None:
        return False, "AniGUI isn't running as an app (running from source)."
    if "AppTranslocation" in str(app):
        return False, "AniGUI is running from a temporary location. Move it to Applications first."
    if not os.access(app.parent, os.W_OK) or not os.access(app, os.W_OK):
        return False, f"AniGUI can't write to {app.parent}."
    return True, ""


# -- download and verify --------------------------------------------------------------

def download(url: str, dest: Path, progress: Progress = lambda _d, _t: None,
             cancelled: Callable[[], bool] = lambda: False, opener=None) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": http.USER_AGENT})
    try:
        resp = (opener or (lambda r: urllib.request.urlopen(r, timeout=60, context=http._SSL)))(req)
    except OSError as exc:
        raise UpdateError(f"Couldn't download the update: {exc}") from exc
    with resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as fh:
            while True:
                if cancelled():
                    raise Cancelled("Update cancelled.")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                progress(done, total)
    if total and done != total:
        raise UpdateError("The download was cut off. Try again.")
    return dest


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def expected_sha256(sha256: str | None, sha256_url: str | None, fetch=None) -> str:
    if sha256:
        return sha256.lower()
    if not sha256_url:
        raise UpdateError("This release has no checksum, so it can't be installed automatically.")
    from .setup import _fetch
    try:
        text = (fetch or _fetch)(sha256_url).decode("utf-8", "replace")
    except SetupError as exc:
        raise UpdateError(f"Couldn't get the checksum: {exc}") from exc
    value = text.split()[0].lower() if text.split() else ""
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise UpdateError("The release's checksum file is unreadable.")
    return value


def verify(path: Path, expected: str) -> None:
    if sha256_of(path) != expected.lower():
        raise UpdateError("The download didn't match its checksum, so it wasn't installed.")


# -- install ----------------------------------------------------------------------------

def bundle_version(app: Path) -> str | None:
    try:
        with open(app / "Contents" / "Info.plist", "rb") as fh:
            return plistlib.load(fh).get("CFBundleShortVersionString")
    except (OSError, plistlib.InvalidFileException):
        return None


def install(dmg: Path, app: Path, expected_version: str | None = None, run: Run = subprocess.run) -> Path:
    """Replace `app` with the AniGUI.app inside `dmg`. Returns the installed path."""
    mount = Path(tempfile.mkdtemp(prefix="anigui-update-"))
    staged = app.with_name(f".{app.stem}-update{app.suffix}")
    old = app.with_name(f".{app.stem}-old{app.suffix}")
    for leftover in (staged, old):
        shutil.rmtree(leftover, ignore_errors=True)

    attach = run(["hdiutil", "attach", str(dmg), "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", str(mount)],
                 capture_output=True, text=True)
    if attach.returncode != 0:
        raise UpdateError(f"Couldn't open the update: {attach.stderr.strip()[:200]}")
    try:
        source = mount / app.name
        if not source.is_dir():
            source = next((p for p in mount.iterdir() if p.suffix == ".app"), None)
        if source is None:
            raise UpdateError("The update doesn't contain AniGUI.app.")
        copy = run(["ditto", str(source), str(staged)], capture_output=True, text=True)
        if copy.returncode != 0:
            raise UpdateError(f"Couldn't copy the update: {copy.stderr.strip()[:200]}")
    finally:
        run(["hdiutil", "detach", str(mount), "-quiet", "-force"], capture_output=True, text=True)
        shutil.rmtree(mount, ignore_errors=True)

    try:
        # Downloaded by AniGUI, so there's no quarantine flag; clear one anyway if present.
        run(["xattr", "-dr", "com.apple.quarantine", str(staged)], capture_output=True, text=True)
        check = run(["codesign", "--verify", "--deep", "--strict", str(staged)], capture_output=True, text=True)
        if check.returncode != 0:
            raise UpdateError("The new version's code signature didn't check out, so it wasn't installed.")
        if expected_version and bundle_version(staged) != expected_version:
            raise UpdateError(f"The download is version {bundle_version(staged)}, not {expected_version}.")
        os.replace(app, old)            # same folder, so these are instant renames
        try:
            os.replace(staged, app)
        except OSError:
            os.replace(old, app)        # put the old one back
            raise
    except BaseException:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    shutil.rmtree(old, ignore_errors=True)
    return app


def relaunch_command(app: Path, pid: int | None = None) -> list[str]:
    """A detached shell that waits for this AniGUI to quit, then opens the new one."""
    pid = pid or os.getpid()
    script = f'while kill -0 {pid} 2>/dev/null; do sleep 0.2; done; open "{app}"'
    return ["/bin/sh", "-c", script]


def relaunch(app: Path) -> None:
    subprocess.Popen(relaunch_command(app), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def download_and_install(update, app: Path, progress: Progress = lambda _d, _t: None,
                         cancelled: Callable[[], bool] = lambda: False, stage: Callable[[str], None] = lambda _s: None,
                         run: Run = subprocess.run, opener=None, fetch=None) -> Path:
    """Everything up to (not including) the restart. Raises UpdateError with a readable message."""
    if not update.dmg_url:
        raise UpdateError("This release has no installer to download.")
    stage("Checking the release…")
    expected = expected_sha256(update.sha256, update.sha256_url, fetch)
    work = Path(tempfile.mkdtemp(prefix="anigui-dl-"))
    try:
        dmg = work / "AniGUI.dmg"
        stage(f"Downloading AniGUI {update.latest}…")
        download(update.dmg_url, dmg, progress, cancelled, opener)
        stage("Verifying…")
        verify(dmg, expected)
        if cancelled():
            raise Cancelled("Update cancelled.")
        stage("Installing…")
        return install(dmg, app, update.latest, run)
    finally:
        shutil.rmtree(work, ignore_errors=True)
