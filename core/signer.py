"""The publisher's release signer. Runs only on the publisher's Mac.

    AniGUI --signer-init        create the signing key (stored in the macOS Keychain)
    AniGUI --signer-install     check for releases to sign every 5 minutes (LaunchAgent)
    AniGUI --signer-check       look once (what the LaunchAgent runs)
    AniGUI --signer-backup      print the private key, to keep in a password manager
    AniGUI --signer-restore     put a backed-up key into the Keychain (reads stdin)
    AniGUI --signer-uninstall   stop the background checks

The private key lives in the login Keychain with no app trusted to read it, so
macOS asks for your password every time it's used: that prompt is the approval.
Users of AniGUI never run any of this; their copy only has the public key.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import plistlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import paths, signing
from .env import which
from .self_update import download, sha256_of
from .setup import SetupError, _fetch

REPO = "JRodriguez-Luna/anigui"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=10"
KEYCHAIN_SERVICE = "AniGUI release signing key"
KEYCHAIN_ACCOUNT = "anigui-release"
AGENT_LABEL = "io.github.jrodriguez-luna.anigui.signer"
CHECK_EVERY_S = 300
RECENT_DAYS = 30
SNOOZE_S = 3600

Run = Callable[..., subprocess.CompletedProcess]


class SignerError(RuntimeError):
    pass


# -- Keychain -------------------------------------------------------------------------------

def has_key(run: Run = subprocess.run) -> bool:
    found = run(["security", "find-generic-password", "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE],
                capture_output=True, text=True)
    return found.returncode == 0


def store_key(private_b64: str, run: Run = subprocess.run) -> None:
    # -T "" trusts no app: every read asks for your Mac password.
    done = run(["security", "add-generic-password", "-U", "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE,
                "-l", KEYCHAIN_SERVICE, "-T", "", "-w", private_b64], capture_output=True, text=True)
    if done.returncode != 0:
        raise SignerError(f"Couldn't save the key in the Keychain: {done.stderr.strip()[:200]}")


def read_key(run: Run = subprocess.run) -> str:
    """Asks macOS for the key; macOS asks you for your password first."""
    got = run(["security", "find-generic-password", "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE, "-w"],
              capture_output=True, text=True)
    if got.returncode != 0:
        raise SignerError("The signing key wasn't released (the Keychain prompt was cancelled, "
                          "or there's no key: run AniGUI --signer-init).")
    return got.stdout.strip()


def public_key_file() -> Path:
    return paths.data_dir() / "signer-public-key.txt"


def init(run: Run = subprocess.run) -> str:
    """Create and store a new key. Returns the public key to build into AniGUI."""
    if has_key(run):
        if public_key_file().is_file():
            return public_key_file().read_text().strip()
        raise SignerError("A signing key already exists in your Keychain. Use --signer-backup to see it.")
    private = signing.new_private_key()
    store_key(private, run)
    public = signing.public_key_of(private)
    public_key_file().write_text(public + "\n")
    return public


# -- What needs signing ---------------------------------------------------------------------

@dataclass
class Pending:
    tag: str
    version: str
    published_at: str
    author: str
    notes: str
    page: str
    dmg_name: str
    dmg_url: str
    size: int
    digest: str | None              # GitHub's sha256 for the .dmg
    sha256_url: str | None


@dataclass
class State:
    signed: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    snoozed: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "State":
        try:
            data = json.loads(state_file().read_text())
            return cls(data.get("signed", []), data.get("rejected", []), data.get("snoozed", {}))
        except (OSError, ValueError):
            return cls()

    def save(self) -> None:
        state_file().write_text(json.dumps(self.__dict__, indent=2))


def state_file() -> Path:
    return paths.data_dir() / "signer-state.json"


def pending_releases(fetch=_fetch, state: State | None = None, now: dt.datetime | None = None) -> list[Pending]:
    state = state or State.load()
    now = now or dt.datetime.now(dt.timezone.utc)
    releases = json.loads(fetch(RELEASES_API))
    found = []
    for r in releases:
        tag = str(r.get("tag_name") or "")
        if not tag or r.get("draft") or r.get("prerelease") or tag in state.signed or tag in state.rejected:
            continue
        if state.snoozed.get(tag, 0) > now.timestamp():
            continue
        try:
            published = dt.datetime.fromisoformat(str(r.get("published_at")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if now - published > dt.timedelta(days=RECENT_DAYS):
            continue
        assets = r.get("assets") or []
        dmg = next((a for a in assets if str(a.get("name", "")).endswith(".dmg")), None)
        if dmg is None or any(a.get("name") == f"{dmg['name']}.sig" for a in assets):
            continue  # not built yet, or already signed
        checksum = next((a for a in assets if a.get("name") == f"{dmg['name']}.sha256"), None)
        digest = str(dmg.get("digest") or "")
        found.append(Pending(tag, tag.lstrip("v"), published.astimezone().strftime("%b %-d, %-I:%M %p"),
                             str((r.get("author") or {}).get("login") or "?"), str(r.get("body") or ""),
                             str(r.get("html_url") or ""), dmg["name"], dmg["browser_download_url"],
                             int(dmg.get("size") or 0),
                             digest.removeprefix("sha256:") if digest.startswith("sha256:") else None,
                             (checksum or {}).get("browser_download_url")))
    return found


@dataclass
class Review:
    """What the publisher sees before signing."""
    pending: Pending
    path: Path
    sha256: str
    problems: list[str]

    @property
    def safe(self) -> bool:
        return not self.problems


def prepare(p: Pending, fetch=_fetch, progress=lambda _d, _t: None) -> Review:
    """Download the release's .dmg and check it against what GitHub says it is."""
    folder = Path(tempfile.mkdtemp(prefix="anigui-sign-"))
    path = folder / p.dmg_name
    download(p.dmg_url, path, progress)
    actual = sha256_of(path)
    problems = []
    if p.digest and p.digest.lower() != actual:
        problems.append("The file doesn't match GitHub's checksum for it.")
    if p.sha256_url:
        try:
            published = fetch(p.sha256_url).decode("utf-8", "replace").split()[0].lower()
        except (SetupError, IndexError):
            published = ""
        if published != actual:
            problems.append("The file doesn't match the .sha256 published with it.")
    if not (p.digest or p.sha256_url):
        problems.append("The release has no checksum to compare against.")
    return Review(p, path, actual, problems)


def sign_and_upload(review: Review, run: Run = subprocess.run, key_reader=None) -> Path:
    """Ask the Keychain for the key (you approve), sign, and attach the signature to the release."""
    if not review.safe:
        raise SignerError("Not signing: " + " ".join(review.problems))
    gh = which("gh")
    if not gh:
        raise SignerError("GitHub's gh tool isn't installed. Run: brew install gh, then: gh auth login")
    private = (key_reader or (lambda: read_key(run)))()
    if signing.PUBLIC_KEYS and signing.public_key_of(private) not in signing.PUBLIC_KEYS:
        raise SignerError("The key in your Keychain isn't one this AniGUI trusts, so users would refuse "
                          "the signature. Was the key replaced?")
    signature = signing.sign(private, review.pending.version, review.sha256)
    sig_path = review.path.with_name(f"{review.pending.dmg_name}.sig")
    sig_path.write_text(signature + "\n")
    up = run([gh, "release", "upload", review.pending.tag, str(sig_path), "--repo", REPO, "--clobber"],
             capture_output=True, text=True)
    if up.returncode != 0:
        raise SignerError(f"Signed, but the upload to GitHub failed: {up.stderr.strip()[:300]}\n"
                          "Is gh signed in? Run: gh auth status")
    state = State.load()
    state.signed.append(review.pending.tag)
    state.save()
    return sig_path


def reject(tag: str) -> None:
    state = State.load()
    state.rejected.append(tag)
    state.save()


def snooze(tag: str, seconds: float = SNOOZE_S) -> None:
    state = State.load()
    state.snoozed[tag] = dt.datetime.now(dt.timezone.utc).timestamp() + seconds
    state.save()


# -- Background checks (LaunchAgent) ------------------------------------------------------

def agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"


def agent_program() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--signer-check"]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py"), "--signer-check"]


def agent_plist() -> bytes:
    logs = Path.home() / "Library" / "Logs" / "AniGUI"
    logs.mkdir(parents=True, exist_ok=True)
    return plistlib.dumps({
        "Label": AGENT_LABEL,
        "ProgramArguments": agent_program(),
        "StartInterval": CHECK_EVERY_S,
        "RunAtLoad": True,
        "ProcessType": "Interactive",
        "StandardOutPath": str(logs / "signer.log"),
        "StandardErrorPath": str(logs / "signer.log"),
    })


def install_agent(run: Run = subprocess.run) -> Path:
    path = agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    run(["launchctl", "bootout", f"{domain}/{AGENT_LABEL}"], capture_output=True, text=True)
    path.write_bytes(agent_plist())
    done = run(["launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True)
    if done.returncode != 0:
        raise SignerError(f"Couldn't start the background check: {done.stderr.strip()[:200]}")
    return path


def uninstall_agent(run: Run = subprocess.run) -> None:
    run(["launchctl", "bootout", f"gui/{os.getuid()}/{AGENT_LABEL}"], capture_output=True, text=True)
    agent_path().unlink(missing_ok=True)
