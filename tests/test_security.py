"""v1.5 security hardening."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from core.ani_cli import AniCliError, StreamInfo, is_web_url, parse_capture  # noqa: E402
from core.player import PlayerError, build_player_command  # noqa: E402


def capture(*args: str) -> bytes:
    return b"\0".join(a.encode() for a in args) + b"\0"


# -- 1. Player links ---------------------------------------------------------------------------

def test_is_web_url():
    assert is_web_url("https://cdn.example/a/index.m3u8?t=1&x=%20")
    for bad in ("--script=/tmp/evil.lua", "file:///etc/passwd", "ytdl://x", "https://a b", "https://a\nb",
                "https://a\"b", "-https://x", "", "http://" + "a" * 5000, "javascript:alert(1)"):
        assert not is_web_url(bad), bad


def test_capture_drops_player_options_and_bad_side_links():
    info = parse_capture(capture("--referrer=https://embed.example/", "--script=/tmp/evil.lua",
                                 "--audio-file=file:///tmp/x", "--sub-file=--script=/tmp/evil.lua",
                                 "--force-media-title=Show", "https://cdn/1080/index.m3u8"))
    assert info.url == "https://cdn/1080/index.m3u8" and info.extra_args == ()
    assert info.audio_url is None and info.subtitle_url is None and info.referrer == "https://embed.example/"
    with pytest.raises(AniCliError):
        parse_capture(capture("--referrer=https://e/", "--script=/tmp/evil.lua"))   # option where the URL goes


def test_player_commands_end_options_and_refuse_bad_links():
    info = StreamInfo("https://cdn/v.m3u8", "https://embed/", "T", "https://cdn/a.m3u8", "https://cdn/s.vtt")
    mpv = build_player_command("mpv", "/x/mpv", info, "T", "/tmp/s.sock")
    assert mpv[-2:] == ["--", "https://cdn/v.m3u8"]
    iina = build_player_command("iina", "/x/iina", info, "T")
    assert iina[-1] == "https://cdn/v.m3u8" and not any("script" in a for a in iina)
    for field in ("url", "audio_url", "subtitle_url", "referrer"):
        bad = StreamInfo(**{**info.__dict__, field: "--script=/tmp/evil.lua"})
        with pytest.raises(PlayerError):
            build_player_command("mpv", "/x/mpv", bad, "T")


# -- 5-7. Text, commands, temp files --------------------------------------------------------

def test_ipc_socket_in_private_folder():
    import os
    import stat
    from core import player
    path = player.default_ipc_path()
    folder = os.path.dirname(path)
    assert len(path) < 104 and stat.S_IMODE(os.stat(folder).st_mode) == 0o700
    assert player.default_ipc_path() == path      # same folder for the whole run


def test_notification_fallback_passes_text_as_arguments(monkeypatch):
    from ui import alerts
    seen = []
    monkeypatch.setattr(alerts.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    monkeypatch.setattr(alerts.sys, "platform", "darwin")
    monkeypatch.setattr(alerts.subprocess, "Popen", lambda cmd, **k: seen.append(cmd))
    alerts.Notifier().notify('-e do shell script "touch /tmp/pwned"', 'x" & (do shell script "id") & "')
    cmd = seen[0]
    assert cmd[-3] == "anigui"                                  # stops option parsing before user text
    assert cmd[-2].startswith("-e do shell") and all("pwned" not in part for part in cmd[:-3])


def test_web_text_is_shown_as_plain_text(tmp_path):
    from PySide6.QtCore import Qt
    import ui_fakes
    from ui.main_window import MainWindow
    ctx = ui_fakes.fake_context(tmp_path)
    win = MainWindow(ctx)
    for label in (win.detail.title, win.detail.synopsis, win.detail.meta, win.home.hero.title, win.toast,
                  win.search.status):
        assert label.textFormat() == Qt.TextFormat.PlainText
    win.close()
    ctx.shutdown()


def test_theme_images_not_in_shared_temp():
    import tempfile
    from ui import theme
    assert not theme._chevron_path().startswith(tempfile.gettempdir())


# -- 3-4. Third-party downloads ---------------------------------------------------------------

import json  # noqa: E402

from core import setup  # noqa: E402


class _Run:
    def __init__(self, team="67CQ77V27R", verify=0, gate=0, gate_text="accepted\nsource=Notarized Developer ID"):
        self.team, self.verify, self.gate, self.gate_text = team, verify, gate, gate_text

    def __call__(self, cmd, **_kw):
        import subprocess
        if cmd[:2] == ["codesign", "--verify"]:
            return subprocess.CompletedProcess(cmd, self.verify, "", "")
        if cmd[:2] == ["codesign", "-dv"]:
            return subprocess.CompletedProcess(cmd, 0, "", f"TeamIdentifier={self.team}\n" if self.team else "")
        if cmd[0] == "spctl":
            return subprocess.CompletedProcess(cmd, self.gate, "", self.gate_text)
        raise AssertionError(cmd)


def test_verify_iina_requires_iinas_team_and_gatekeeper(tmp_path):
    app = tmp_path / "IINA.app"
    setup.verify_iina(app, _Run())                                   # the real thing passes
    for bad, why in ((_Run(team="EVIL123456"), "someone else"), (_Run(team=None), "someone else"),
                     (_Run(verify=1), "broken"), (_Run(gate=3, gate_text="rejected"), "Gatekeeper")):
        with pytest.raises(setup.SetupError, match=why):
            setup.verify_iina(app, bad)
    setup.verify_iina(app, _Run(gate=3, gate_text="accepted (override=security disabled)"))  # Gatekeeper off


def released_as(tag, script):
    def fetch(url):
        if url == setup.ANI_CLI_RELEASES:
            return json.dumps({"tag_name": tag}).encode()
        return script
    return fetch


def test_ani_cli_updates_come_from_tagged_releases():
    script = b'#!/bin/sh\nversion_number="5.2.0"\n'
    urls = []

    def fetch(url):
        urls.append(url)
        if url == setup.ANI_CLI_RELEASES:
            raise setup.SetupError("HTTP 403")                       # rate-limited: use the release page
        if url == setup.ANI_CLI_RELEASES_WEB:
            return b'<a href="/pystardust/ani-cli/releases/tag/v5.2.0">v5.2.0</a>'
        return script

    assert setup.latest_ani_cli(fetch) == ("5.2.0", script)
    assert urls[-1] == setup.ANI_CLI_RAW.format(ref="v5.2.0") and not any("master" in u for u in urls)
    short_tag = released_as("v5.1", b'#!/bin/sh\nversion_number="5.1.0"\n')
    assert setup.latest_ani_cli(short_tag)[0] == "5.1.0"          # "v5.1" is the 5.1.0 release
    with pytest.raises(setup.SetupError, match="doesn't match"):
        setup.latest_ani_cli(released_as("v5.1", b'#!/bin/sh\nversion_number="5.2.0"\n'))
    with pytest.raises(setup.SetupError, match="unexpected name"):
        setup.latest_ani_cli(lambda url: json.dumps({"tag_name": "main; rm -rf"}).encode())


# -- 2. Signed updates --------------------------------------------------------------------------

import hashlib  # noqa: E402
import subprocess  # noqa: E402

from core import self_update, signer, signing, updates  # noqa: E402


@pytest.fixture
def keypair():
    private = signing.new_private_key()
    return private, signing.public_key_of(private)


def test_signature_binds_version_and_file(keypair):
    private, public = keypair
    sha = "ab" * 32
    sig = signing.sign(private, "1.5.0", sha)
    assert signing.verify("1.5.0", sha, sig, (public,))
    assert not signing.verify("1.6.0", sha, sig, (public,))           # an old release passed off as newer
    assert not signing.verify("1.5.0", "cd" * 32, sig, (public,))     # a different file
    other = signing.public_key_of(signing.new_private_key())
    assert not signing.verify("1.5.0", sha, sig, (other,))            # someone else's key
    assert not signing.verify("1.5.0", sha, "not base64!!", (public,))
    assert not signing.enforced(()) and signing.enforced((public,))


def _release(tmp_path, private, version="1.5.0", sign_version=None):
    dmg = tmp_path / "AniGUI.dmg"
    dmg.write_bytes(b"pretend disk image")
    digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
    sig = tmp_path / "AniGUI.dmg.sig"
    sig.write_text(signing.sign(private, sign_version or version, digest))
    upd = updates.AppUpdate("1.4.1", version, "https://x/releases/v1.5.0", "", dmg_url=dmg.as_uri(),
                            sha256=digest, sig_url=sig.as_uri())
    return upd


def _read(url):
    return Path(url.removeprefix("file://")).read_bytes()


def test_update_now_refuses_unsigned_or_wrongly_signed(tmp_path, keypair, monkeypatch):
    private, public = keypair
    installs = []
    monkeypatch.setattr(self_update, "install", lambda dmg, app, version, run: installs.append(version) or app)
    good = _release(tmp_path, private)
    assert self_update.download_and_install(good, tmp_path / "AniGUI.app", fetch=_read, keys=(public,))
    assert installs == ["1.5.0"]

    stranger = signing.new_private_key()
    forged = _release(tmp_path, stranger)
    with pytest.raises(self_update.UpdateError, match="isn't signed by AniGUI's publisher"):
        self_update.download_and_install(forged, tmp_path / "AniGUI.app", fetch=_read, keys=(public,))
    replay = _release(tmp_path, private, version="1.6.0", sign_version="1.5.0")
    with pytest.raises(self_update.UpdateError, match="isn't signed"):
        self_update.download_and_install(replay, tmp_path / "AniGUI.app", fetch=_read, keys=(public,))
    unsigned = updates.AppUpdate(**{**good.__dict__, "sig_url": None})
    with pytest.raises(self_update.UpdateError, match="isn't signed by AniGUI's publisher yet"):
        self_update.download_and_install(unsigned, tmp_path / "AniGUI.app", fetch=_read, keys=(public,))
    assert installs == ["1.5.0"]                                       # nothing else got installed


def test_unsigned_release_not_offered_once_signing_is_on(monkeypatch, keypair):
    _private, public = keypair
    release = {"tag_name": "v9.0.0", "html_url": "u", "body": "", "assets": [
        {"name": "A.dmg", "browser_download_url": "https://d/A.dmg", "digest": "sha256:" + "ab" * 32}]}
    fetch = lambda url: json.dumps(release).encode()  # noqa: E731
    monkeypatch.setattr(signing, "PUBLIC_KEYS", ())
    assert updates.check_anigui(fetch=fetch).installable                # no key built in: offered
    monkeypatch.setattr(signing, "PUBLIC_KEYS", (public,))
    assert updates.check_anigui(fetch=fetch) is None                    # signing on: waits for the .sig
    release["assets"].append({"name": "A.dmg.sig", "browser_download_url": "https://d/A.dmg.sig"})
    upd = updates.check_anigui(fetch=fetch)
    assert upd.installable and upd.sig_url == "https://d/A.dmg.sig"


# -- the publisher's signer ---------------------------------------------------------------------

class FakeMac:
    """`security` keeps one item; `gh` records uploads."""

    def __init__(self):
        self.keychain: str | None = None
        self.uploads = []

    def __call__(self, cmd, **_kw):
        ok = subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:2] == ["security", "add-generic-password"]:
            assert cmd[cmd.index("-T") + 1] == ""                      # no app may read it without asking
            self.keychain = cmd[cmd.index("-w") + 1]
            return ok
        if cmd[:2] == ["security", "find-generic-password"]:
            if self.keychain is None:
                return subprocess.CompletedProcess(cmd, 44, "", "not found")
            return subprocess.CompletedProcess(cmd, 0, self.keychain + "\n" if "-w" in cmd else "", "")
        if cmd[1:3] == ["release", "upload"]:
            self.uploads.append((cmd[3], Path(cmd[4]).read_text().strip()))
            return ok
        raise AssertionError(cmd)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIGUI_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(signer, "which", lambda name: "/opt/homebrew/bin/gh")
    return tmp_path


def _github(tmp_path, digest, tag="v1.5.0", signed=False, published="2026-11-01T08:00:00Z"):
    assets = [{"name": "AniGUI-1.5.0.dmg", "browser_download_url": (tmp_path / "rel.dmg").as_uri(), "size": 10,
               "digest": f"sha256:{digest}"}]
    if signed:
        assets.append({"name": "AniGUI-1.5.0.dmg.sig", "browser_download_url": "x"})
    return [{"tag_name": tag, "published_at": published, "author": {"login": "JRodriguez-Luna"},
             "body": "## What's new\n- Security", "html_url": "u", "assets": assets}]


def test_signer_init_review_sign_upload(home, monkeypatch):
    import datetime as dt
    mac = FakeMac()
    public = signer.init(mac)
    assert mac.keychain and signing.public_key_of(mac.keychain) == public
    assert signer.init(mac) == public                                   # doesn't replace an existing key

    (home / "rel.dmg").write_bytes(b"the real release")
    digest = hashlib.sha256(b"the real release").hexdigest()
    now = dt.datetime(2026, 11, 1, 9, tzinfo=dt.timezone.utc)
    releases = _github(home, digest)
    pending = signer.pending_releases(lambda url: json.dumps(releases).encode(), signer.State(), now)
    assert [p.tag for p in pending] == ["v1.5.0"]
    review = signer.prepare(pending[0], fetch=_read)
    assert review.safe and review.sha256 == digest

    monkeypatch.setattr(signing, "PUBLIC_KEYS", (public,))
    signer.sign_and_upload(review, run=mac)
    tag, sig = mac.uploads[0]
    assert tag == "v1.5.0" and signing.verify("1.5.0", digest, sig)     # users would accept it
    assert signer.pending_releases(lambda url: json.dumps(releases).encode(), now=now) == []  # remembered


def test_signer_refuses_mismatched_files_and_wrong_key(home, monkeypatch):
    import datetime as dt
    mac = FakeMac()
    signer.init(mac)
    (home / "rel.dmg").write_bytes(b"swapped file")
    now = dt.datetime(2026, 11, 1, 9, tzinfo=dt.timezone.utc)
    releases = _github(home, "00" * 32)
    review = signer.prepare(signer.pending_releases(lambda url: json.dumps(releases).encode(), signer.State(),
                                                    now)[0], fetch=_read)
    assert not review.safe and "checksum" in review.problems[0]
    with pytest.raises(signer.SignerError, match="Not signing"):
        signer.sign_and_upload(review, run=mac)

    (home / "rel.dmg").write_bytes(b"ok")
    good = signer.prepare(signer.pending_releases(lambda url: json.dumps(_github(home, hashlib.sha256(b"ok").hexdigest())).encode(),
                                                  signer.State(), now)[0], fetch=_read)
    monkeypatch.setattr(signing, "PUBLIC_KEYS", (signing.public_key_of(signing.new_private_key()),))
    with pytest.raises(signer.SignerError, match="isn't one this AniGUI trusts"):
        signer.sign_and_upload(good, run=mac)
    assert mac.uploads == []


def test_signer_skips_old_signed_rejected_and_snoozed(home):
    import datetime as dt
    now = dt.datetime(2026, 11, 1, 9, tzinfo=dt.timezone.utc)
    fetch = lambda r: (lambda url: json.dumps(r).encode())  # noqa: E731
    assert signer.pending_releases(fetch(_github(home, "a" * 64, signed=True)), signer.State(), now) == []
    assert signer.pending_releases(fetch(_github(home, "a" * 64, published="2026-08-01T00:00:00Z")),
                                   signer.State(), now) == []
    assert signer.pending_releases(fetch(_github(home, "a" * 64)), signer.State(rejected=["v1.5.0"]), now) == []
    later = signer.State(snoozed={"v1.5.0": now.timestamp() + 60})
    assert signer.pending_releases(fetch(_github(home, "a" * 64)), later, now) == []


def test_launch_agent_plist(home, monkeypatch):
    import plistlib
    monkeypatch.setattr(signer.Path, "home", staticmethod(lambda: home))
    data = plistlib.loads(signer.agent_plist())
    assert data["Label"] == signer.AGENT_LABEL and data["StartInterval"] == 300
    assert data["ProgramArguments"][-1] == "--signer-check"


def test_sign_dialog_blocks_signing_when_something_is_off(tmp_path):
    from PySide6.QtWidgets import QApplication
    from ui.signer_dialog import SignDialog
    QApplication.instance() or QApplication([])
    p = signer.Pending("v1.5.0", "1.5.0", "Nov 1, 1:00 AM", "JRodriguez-Luna", "- Security <b>x</b>", "u",
                       "AniGUI-1.5.0.dmg", "file:///x", 1048576, "ab" * 32, None)
    ok = SignDialog(signer.Review(p, tmp_path / "a.dmg", "ab" * 32, []))
    assert ok.sign_btn.isEnabled() and not ok.problem.isVisibleTo(ok)
    bad = SignDialog(signer.Review(p, tmp_path / "a.dmg", "cd" * 32, ["The file doesn't match GitHub's checksum for it."]))
    assert not bad.sign_btn.isEnabled() and bad.problem.isVisibleTo(bad)


def test_ani_cli_updates_arrive_with_anigui(tmp_path, monkeypatch):
    """Option C: AniGUI brings its own copy up to the version this build pinned and tested."""
    monkeypatch.setenv("ANIGUI_HOME", str(tmp_path / "home"))
    installed = []
    monkeypatch.setattr(setup, "install_ani_cli", lambda fetch=None: installed.append(1) or setup.ANI_CLI_PIN_VERSION)
    assert setup.ensure_pinned_ani_cli() is None                      # no AniGUI copy (Terminal one is left alone)
    target = setup.managed_ani_cli()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('#!/bin/sh\nversion_number="5.0.0"\n')
    assert setup.ensure_pinned_ani_cli() == setup.ANI_CLI_PIN_VERSION and installed == [1]
    target.write_text(f'#!/bin/sh\nversion_number="{setup.ANI_CLI_PIN_VERSION}"\n')
    assert setup.ensure_pinned_ani_cli() is None and installed == [1]   # already current


def test_publisher_key_is_built_in_and_enforced():
    import base64
    assert signing.PUBLIC_KEYS and signing.enforced()
    for key in signing.PUBLIC_KEYS:
        assert len(base64.b64decode(key, validate=True)) == 32
    # A signature from any other key is refused by the real, built-in key list
    other = signing.new_private_key()
    assert not signing.verify("9.9.9", "ab" * 32, signing.sign(other, "9.9.9", "ab" * 32))
