"""v1.8.8: the publisher's background signing check is reloaded after an update, so macOS
never refuses to start the new app from the old one's registration (crash report)."""

from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from core import __version__, self_update, signer  # noqa: E402


class Launchctl:
    def __init__(self, loaded: bool = True) -> None:
        self.loaded = loaded
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **_kw):
        self.calls.append(cmd)
        rc = 0
        if cmd[:2] == ["launchctl", "print"]:
            rc = 0 if self.loaded else 113
        elif cmd[:2] == ["launchctl", "bootout"]:
            self.loaded = False
        elif cmd[:2] == ["launchctl", "bootstrap"]:
            self.loaded = True
        return subprocess.CompletedProcess(cmd, rc, "", "")

    def verbs(self) -> list[str]:
        return [c[1] for c in self.calls]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(signer.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    return tmp_path


def test_plist_names_the_version(home):
    data = plistlib.loads(signer.agent_plist())
    assert data["EnvironmentVariables"]["ANIGUI_VERSION"] == __version__


def test_nothing_happens_without_the_agent(home):
    lc = Launchctl()
    assert signer.refresh_agent(lc) is False and lc.calls == []      # friends' Macs
    signer.pause_agent(lc)
    assert lc.calls == []


def test_up_to_date_and_loaded_is_left_alone(home):
    lc = Launchctl()
    signer.install_agent(lc)
    lc.calls.clear()
    assert signer.refresh_agent(lc) is False
    assert lc.verbs() == ["print"]


def test_after_an_update_it_is_loaded_again_for_the_new_version(home):
    lc = Launchctl()
    path = signer.agent_path()
    path.parent.mkdir(parents=True)
    old = plistlib.loads(signer.agent_plist())
    old["EnvironmentVariables"]["ANIGUI_VERSION"] = "0.0.1"          # written by the old app
    path.write_bytes(plistlib.dumps(old))
    assert signer.refresh_agent(lc) is True
    assert lc.verbs() == ["print", "bootout", "bootstrap"]
    assert plistlib.loads(path.read_bytes())["EnvironmentVariables"]["ANIGUI_VERSION"] == __version__


def test_paused_for_an_update_is_started_again(home):
    lc = Launchctl()
    signer.install_agent(lc)
    signer.pause_agent(lc)
    assert not lc.loaded and signer.agent_path().exists()             # file kept
    assert signer.refresh_agent(lc) is True and lc.loaded


def test_running_from_source_never_touches_it(home, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False)
    lc = Launchctl()
    signer.agent_path().parent.mkdir(parents=True)
    signer.agent_path().write_bytes(b"x")
    assert signer.refresh_agent(lc) is False and lc.calls == []


def test_update_pauses_the_agent_before_swapping_the_app(home, tmp_path, monkeypatch):
    from test_update_now import FakeMac, make_app

    lc = Launchctl()
    signer.install_agent(lc)
    src = tmp_path / "src"
    make_app(src / "AniGUI.app", "9.9.9")
    app = make_app(tmp_path / "Applications" / "AniGUI.app", "1.0.0")
    mac = FakeMac(src)
    order: list[str] = []

    def run(cmd, **kw):
        if cmd[0] == "launchctl":
            order.append(f"launchctl {cmd[1]} (app is {self_update.bundle_version(app)})")
            return lc(cmd, **kw)
        return mac(cmd, **kw)

    dmg = tmp_path / "x.dmg"
    dmg.write_bytes(b"dmg")
    self_update.install(dmg, app, "9.9.9", run)
    assert order == ["launchctl bootout (app is 1.0.0)"]             # before the swap
    assert self_update.bundle_version(app) == "9.9.9"
