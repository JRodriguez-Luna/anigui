"""v1.3: Update Now (download, verify, swap, restart). macOS tools are simulated here;
the release workflow runs the real thing on a Mac."""

from __future__ import annotations

import hashlib
import json
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QCoreApplication  # noqa: E402

import ui_fakes  # noqa: E402
from core import self_update, updates  # noqa: E402


def pump(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


def make_app(path: Path, version: str) -> Path:
    (path / "Contents" / "MacOS").mkdir(parents=True)
    with open(path / "Contents" / "Info.plist", "wb") as fh:
        plistlib.dump({"CFBundleShortVersionString": version}, fh)
    (path / "Contents" / "MacOS" / "AniGUI").write_text(f"v{version}")
    return path


class FakeMac:
    """hdiutil/ditto/xattr/codesign stand-ins. The 'dmg' is a folder holding AniGUI.app."""

    def __init__(self, contents: Path, codesign_ok=True):
        self.calls = []
        self.contents = contents          # what the mounted disk image holds
        self.codesign_ok = codesign_ok

    def __call__(self, cmd, **_kw):
        self.calls.append(cmd[0])
        rc = 0
        if cmd[0] == "hdiutil" and cmd[1] == "attach":
            mount = Path(cmd[cmd.index("-mountpoint") + 1])
            shutil.copytree(self.contents, mount, dirs_exist_ok=True)
        elif cmd[0] == "ditto":
            shutil.copytree(cmd[1], cmd[2])
        elif cmd[0] == "codesign":
            rc = 0 if self.codesign_ok else 1
        return subprocess.CompletedProcess(cmd, rc, "", "")


@pytest.fixture
def release(tmp_path):
    src = tmp_path / "new.src"
    make_app(src / "AniGUI.app", "1.4.0")
    dmg = tmp_path / "new.dmg"
    dmg.write_bytes(b"pretend this is a disk image")
    apps = tmp_path / "Applications"
    app = make_app(apps / "AniGUI.app", "1.3.0")
    digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
    upd = updates.AppUpdate("1.3.0", "1.4.0", "https://github.com/x/releases/tag/v1.4.0", "",
                            dmg_url=dmg.as_uri(), sha256=digest)
    FakeMac.default_contents = src
    return upd, dmg, app


def test_install_swaps_and_cleans_up(release):
    upd, _dmg, app = release
    stages = []
    mac = FakeMac(FakeMac.default_contents)
    self_update.download_and_install(upd, app, stage=stages.append, run=mac)
    assert self_update.bundle_version(app) == "1.4.0"
    assert sorted(p.name for p in app.parent.iterdir()) == ["AniGUI.app"]       # no leftovers
    assert stages == ["Checking the release…", "Downloading AniGUI 1.4.0…", "Verifying…", "Installing…"]
    assert mac.calls == ["hdiutil", "ditto", "hdiutil", "xattr", "codesign"]


def test_wrong_checksum_touches_nothing(release):
    upd, _dmg, app = release
    bad = updates.AppUpdate(**{**upd.__dict__, "sha256": "0" * 64})
    mac = FakeMac(FakeMac.default_contents)
    with pytest.raises(self_update.UpdateError, match="checksum"):
        self_update.download_and_install(bad, app, run=mac)
    assert self_update.bundle_version(app) == "1.3.0" and mac.calls == []


def test_bad_signature_or_version_keeps_old_app(release):
    upd, _dmg, app = release
    with pytest.raises(self_update.UpdateError, match="signature"):
        self_update.download_and_install(upd, app, run=FakeMac(FakeMac.default_contents, codesign_ok=False))
    assert self_update.bundle_version(app) == "1.3.0"
    wrong = updates.AppUpdate(**{**upd.__dict__, "latest": "9.9.9"})
    with pytest.raises(self_update.UpdateError, match="not 9.9.9"):
        self_update.download_and_install(wrong, app, run=FakeMac(FakeMac.default_contents))
    assert self_update.bundle_version(app) == "1.3.0"
    assert sorted(p.name for p in app.parent.iterdir()) == ["AniGUI.app"]


def test_checksum_from_sha256_file(release, tmp_path):
    upd, dmg, app = release
    sha_file = tmp_path / "new.dmg.sha256"
    sha_file.write_text(f"{hashlib.sha256(dmg.read_bytes()).hexdigest()}  AniGUI-1.4.0.dmg\n")
    via_file = updates.AppUpdate(**{**upd.__dict__, "sha256": None, "sha256_url": sha_file.as_uri()})
    self_update.download_and_install(via_file, app, run=FakeMac(FakeMac.default_contents),
                                     fetch=lambda url: Path(url.removeprefix("file://")).read_bytes())
    assert self_update.bundle_version(app) == "1.4.0"
    with pytest.raises(self_update.UpdateError, match="no checksum"):
        self_update.expected_sha256(None, None)


def test_cancel_during_download(release):
    upd, _dmg, app = release
    with pytest.raises(self_update.Cancelled):
        self_update.download_and_install(upd, app, cancelled=lambda: True, run=FakeMac(FakeMac.default_contents))
    assert self_update.bundle_version(app) == "1.3.0"


def test_supported_and_running_app(tmp_path):
    exe = make_app(tmp_path / "Apps" / "AniGUI.app", "1.3.0") / "Contents" / "MacOS" / "AniGUI"
    app = self_update.running_app(str(exe))
    assert app == tmp_path / "Apps" / "AniGUI.app"
    assert self_update.supported(app) == (True, "")
    assert self_update.supported(None)[0] is False
    trans = Path("/private/var/folders/x/AppTranslocation/ABC/d/AniGUI.app")
    assert "temporary location" in self_update.supported(trans)[1]
    assert self_update.running_app() is None            # tests don't run as an app


def test_relaunch_waits_for_this_process():
    cmd = self_update.relaunch_command(Path("/Applications/AniGUI.app"), pid=4321)
    assert cmd[:2] == ["/bin/sh", "-c"] and "kill -0 4321" in cmd[2] and 'open "/Applications/AniGUI.app"' in cmd[2]


def test_update_check_reads_installer_and_checksum():
    release_json = {
        "tag_name": "v9.0.0", "html_url": "https://github.com/x/releases/tag/v9.0.0", "body": "",
        "assets": [
            {"name": "AniGUI-9.0.0-macOS-AppleSilicon.dmg", "browser_download_url": "https://dl/AniGUI.dmg",
             "digest": "sha256:" + "ab" * 32},
            {"name": "AniGUI-9.0.0-macOS-AppleSilicon.dmg.sha256", "browser_download_url": "https://dl/AniGUI.dmg.sha256"},
        ],
    }
    upd = updates.check_anigui(fetch=lambda url: json.dumps(release_json).encode())
    assert upd.installable and upd.dmg_url == "https://dl/AniGUI.dmg" and upd.sha256 == "ab" * 32
    assert upd.sha256_url == "https://dl/AniGUI.dmg.sha256"
    old = {**release_json, "assets": [{"name": "AniGUI.dmg", "browser_download_url": "https://dl/x.dmg"}]}
    assert not updates.check_anigui(fetch=lambda url: json.dumps(old).encode()).installable   # 1.2-era release


# -- the pop-up -------------------------------------------------------------------------------

@pytest.fixture
def win(tmp_path):
    from ui.main_window import MainWindow
    ctx = ui_fakes.fake_context(tmp_path)
    w = MainWindow(ctx)
    yield w
    w.close()
    ctx.shutdown()


def test_update_now_flow(win, release, monkeypatch):
    upd, _dmg, app = release
    restarted = []
    monkeypatch.setattr(self_update, "running_app", lambda: app)
    monkeypatch.setattr(self_update, "download_and_install",
                        lambda u, a, progress, cancelled, stage: (stage("Downloading AniGUI 1.4.0…"),
                                                                  progress(5, 10), a)[-1])
    monkeypatch.setattr(win, "_restart_into", lambda a: restarted.append(a))
    asked = []
    monkeypatch.setattr(win, "_ask", lambda title, text, primary: asked.append(primary) or "yes")
    win._offer_app_update(upd)
    assert asked == ["Update Now"]
    assert pump(lambda: restarted == [app])


def test_falls_back_to_download_page(win, release, monkeypatch):
    upd, _dmg, _app = release
    opened, asked = [], []
    monkeypatch.setattr(self_update, "running_app", lambda: None)          # e.g. running from source
    monkeypatch.setattr(win, "_ask", lambda title, text, primary: asked.append(primary) or "yes")
    from ui import main_window
    monkeypatch.setattr(main_window.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    win._offer_app_update(upd)
    assert asked == ["Download"] and opened == [upd.url]


def test_failed_update_offers_download_page(win, release, monkeypatch):
    upd, _dmg, app = release
    failures = []
    monkeypatch.setattr(self_update, "download_and_install",
                        lambda *a, **k: (_ for _ in ()).throw(self_update.UpdateError("disk full")))
    monkeypatch.setattr(win, "_update_failed", lambda u, msg: failures.append(msg))
    win.install_update(upd, app)
    assert pump(lambda: failures == ["disk full"])
