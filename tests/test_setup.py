"""v1.1 tests: managed ani-cli, IINA install, network checks, update checks, Setup assistant."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QCoreApplication  # noqa: E402

import fake_site  # noqa: E402
import ui_fakes  # noqa: E402
from core import ani_cli, setup, updates  # noqa: E402
from core.hianime import FetchResult, HianimeClient, SiteUnreachable  # noqa: E402
from core.store import Store  # noqa: E402

SCRIPT = b'#!/bin/sh\n\nversion_number="5.1.6"\necho hi\n'
SCRIPT_SHA = hashlib.sha256(SCRIPT).hexdigest()


def pump(cond=lambda: False, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIGUI_HOME", str(tmp_path / "anigui"))
    return tmp_path


# -- ani-cli -------------------------------------------------------------------------------

def test_versions():
    assert setup.script_version(SCRIPT) == "5.1.6"
    assert setup.script_version(b"#!/bin/sh\necho nope\n") is None
    assert setup.parse_version("5.1.6") > setup.parse_version("5.1.0") > setup.parse_version("4.10")
    assert setup.parse_version("v5.2") == (5, 2)


def test_install_ani_cli_verifies_and_installs(home):
    version = setup.install_ani_cli(SCRIPT, expected_sha256=SCRIPT_SHA)
    path = setup.managed_ani_cli()
    assert version == "5.1.6" and path.read_bytes() == SCRIPT
    assert path.stat().st_mode & stat.S_IXUSR
    assert setup.managed_ani_cli_version() == "5.1.6"
    assert ani_cli.find_ani_cli() == str(path)  # AniGUI's copy wins over PATH


def test_install_rejects_bad_checksum_and_junk(home):
    with pytest.raises(setup.SetupError, match="checksum"):
        setup.install_ani_cli(SCRIPT, expected_sha256="0" * 64)
    with pytest.raises(setup.SetupError, match="doesn't look like"):
        setup.install_ani_cli(b"<html>rate limited</html>")
    assert not setup.managed_ani_cli().exists()


def test_pinned_install_downloads_pinned_commit(home):
    urls = []

    def fetch(url):
        urls.append(url)
        return SCRIPT  # not the real pinned file, so the checksum must fail

    with pytest.raises(setup.SetupError, match="checksum"):
        setup.install_ani_cli(fetch=fetch)
    assert urls == [setup.ANI_CLI_RAW.format(ref=setup.ANI_CLI_PIN_COMMIT)]


def test_pinned_file_matches_checksum_if_available():
    """When the real ani-cli 5.1.6 script is on PATH (CI installs it), the pin must match it."""
    path = shutil.which("ani-cli")
    if not path:
        pytest.skip("ani-cli not installed")
    data = Path(path).read_bytes()
    if setup.script_version(data) != setup.ANI_CLI_PIN_VERSION:
        pytest.skip("different ani-cli version installed")
    assert hashlib.sha256(data).hexdigest() == setup.ANI_CLI_PIN_SHA256


def test_friendly_errors():
    assert "VPN" in ani_cli.friendly("Connection error: could not fetch https://hianime.at (no HTTP response; curl exit 6)")
    assert "curl-impersonate" in ani_cli.friendly("Blocked by cloudflare.")
    assert ani_cli.friendly("Invalid episode!") == "Invalid episode!"


@pytest.mark.skipif(not shutil.which("ani-cli"), reason="ani-cli not installed")
def test_real_ani_cli_runs_without_fzf(tmp_path, monkeypatch):
    for key, value in fake_site.build(tmp_path).items():
        monkeypatch.setenv(key, value)
    (tmp_path / "bin" / "fzf").unlink()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANI_CLI_HIST_DIR", str(tmp_path / "hist"))
    (tmp_path / "home").mkdir()
    real_which = ani_cli.which
    monkeypatch.setattr(ani_cli, "which", lambda name: None if name == "fzf" else real_which(name))
    info = ani_cli.resolve_stream(ani_cli.ResolveRequest(query="frieren", index=1, episode="2"))
    assert info.url.endswith("/102/sub/1080/index.m3u8")


# -- Network -----------------------------------------------------------------------------

class FakeClient:
    def __init__(self, result: FetchResult) -> None:
        self.result = result

    def fetch(self, url, referer=None):
        return self.result


@pytest.mark.parametrize("result, online, state", [
    (FetchResult(0, 200, fake_site._search_page()), True, "ok"),
    (FetchResult(0, 200, "<title>HiAnime</title> hianime.at is blocked in your region"), True, "blocked"),
    (FetchResult(6, None, ""), True, "blocked"),                         # DNS blocked
    (FetchResult(56, None, ""), True, "blocked"),                        # connection reset
    (FetchResult(0, 200, "<html>This site is blocked by your ISP</html>"), True, "blocked"),
    (FetchResult(0, 403, "<title>Just a moment...</title>"), True, "cloudflare"),
    (FetchResult(6, None, ""), False, "offline"),
])
def test_check_network(result, online, state):
    status = setup.check_network(FakeClient(result), control=lambda: online, stream_probe=lambda c, r: None)
    assert status.state == state
    if state == "blocked":
        assert "VPN" in status.message


def test_hianime_client_raises_site_unreachable(tmp_path):
    curl = tmp_path / "curl"
    curl.write_text("#!/bin/sh\nexit 6\n")
    curl.chmod(0o755)
    with pytest.raises(SiteUnreachable, match="VPN"):
        HianimeClient(curl=str(curl)).search("frieren")


# -- IINA ----------------------------------------------------------------------------------

def test_install_iina(tmp_path, monkeypatch):
    apps = tmp_path / "Applications"
    monkeypatch.setattr(setup, "applications_dir", lambda: apps)
    release = {"tag_name": "v1.4.2", "assets": [
        {"name": "IINA.v1.4.2.dmg", "browser_download_url": "https://dl.example/IINA.dmg"}]}
    fetched, calls = [], []

    def fetch(url):
        fetched.append(url)
        return json.dumps(release).encode() if url == setup.IINA_RELEASES else b"DMGBYTES"

    class Done:
        def __init__(self, code=0):
            self.returncode, self.stdout, self.stderr = code, "", ""

    def run(cmd, **_kw):
        calls.append(cmd[0])
        if cmd[:2] == ["hdiutil", "attach"]:
            mnt = Path(cmd[cmd.index("-mountpoint") + 1])
            (mnt / "IINA.app" / "Contents" / "MacOS").mkdir(parents=True)
            (mnt / "IINA.app" / "Contents" / "MacOS" / "iina-cli").write_text("#!/bin/sh\n")
        elif cmd[0] == "ditto":
            shutil.copytree(cmd[1], cmd[2])
        return Done()

    dest = setup.install_iina(fetch=fetch, run=run)
    assert dest == apps / "IINA.app"
    assert (dest / "Contents" / "MacOS" / "iina-cli").exists()
    assert fetched == [setup.IINA_RELEASES, "https://dl.example/IINA.dmg"]
    assert calls == ["hdiutil", "ditto", "hdiutil"]  # attach, copy, detach


def test_install_iina_without_dmg_asset():
    with pytest.raises(setup.SetupError, match="no .dmg"):
        setup.install_iina(fetch=lambda url: json.dumps({"assets": []}).encode(), run=None)


# -- Updates -------------------------------------------------------------------------------

def test_ani_cli_update_checks(tmp_path):
    store = Store(tmp_path / "u.db")
    newer = b'#!/bin/sh\nversion_number="5.1.7"\n'
    upd = updates.check_ani_cli("5.1.6", store, fetch=lambda url: newer)
    assert (upd.current, upd.latest, upd.compatible) == ("5.1.6", "5.1.7", True)
    assert upd.script == newer
    assert updates.check_ani_cli("5.1.6", store, fetch=lambda url: newer) is None  # checked today already
    major = b'#!/bin/sh\nversion_number="5.2.0"\n'
    assert updates.check_ani_cli("5.1.6", None, fetch=lambda url: major).compatible is False
    assert updates.check_ani_cli("5.1.6", None, fetch=lambda url: SCRIPT) is None   # same version
    assert updates.check_ani_cli(None, None, fetch=lambda url: newer) is None


def test_anigui_update_checks(tmp_path):
    def release(tag, **extra):
        return lambda url: json.dumps({"tag_name": tag, "html_url": "https://gh/r", "body": "notes", **extra}).encode()

    upd = updates.check_anigui(None, fetch=release("v1.2.0"), current="1.1.0")
    assert (upd.latest, upd.url) == ("1.2.0", "https://gh/r")
    assert updates.check_anigui(None, fetch=release("v1.1.0"), current="1.1.0") is None
    assert updates.check_anigui(None, fetch=release("v9.0.0", prerelease=True), current="1.1.0") is None

    def offline(url):
        raise setup.SetupError("offline")
    assert updates.check_anigui(None, fetch=offline) is None


# -- Setup assistant UI -------------------------------------------------------------------

@pytest.fixture
def fake_setup(monkeypatch, home):
    state = {"ani_cli": None, "player": None, "net": "blocked"}

    def status():
        return setup.SetupStatus(
            ani_cli_path="/x/ani-cli" if state["ani_cli"] else None, ani_cli_version=state["ani_cli"],
            ani_cli_managed=bool(state["ani_cli"]), ani_cli_supported=bool(state["ani_cli"]),
            player=(state["player"], f"/Applications/{state['player']}") if state["player"] else None,
            iina=state["player"] == "iina")

    def install_ani(*_a, **_k):
        state["ani_cli"] = "5.1.6"
        return "5.1.6"

    def install_iina(*_a, **_k):
        state["player"] = "iina"
        return Path("/Applications/IINA.app")

    monkeypatch.setattr(setup, "current_status", status)
    monkeypatch.setattr(setup, "install_ani_cli", install_ani)
    monkeypatch.setattr(setup, "install_iina", install_iina)
    monkeypatch.setattr(setup, "check_network", lambda *a, **k: (
        setup.NetworkStatus("ok", "hianime is reachable.") if state["net"] == "ok"
        else setup.NetworkStatus("blocked", "hianime is blocked on this network. Some internet providers block it; "
                                            "a VPN such as Cloudflare WARP gets around that.")))
    return state


def test_setup_dialog_sets_up_everything(fake_setup, tmp_path):
    from ui.setup_dialog import SetupDialog

    ctx = ui_fakes.fake_context(tmp_path, with_history=False)
    dlg = SetupDialog(ctx)
    dlg.show()
    assert pump(lambda: dlg.status is not None and dlg.network is not None)
    assert dlg.ani_cli.button.text() == "Install" and dlg.player.button.text() == "Install IINA"
    assert dlg.vpn_box.isVisible() and dlg.everything.isVisible()

    dlg.everything.click()
    assert pump(lambda: dlg.status and dlg.status.ready)
    assert "5.1.6" in dlg.ani_cli.detail.text() and "IINA" in dlg.player.detail.text()
    assert not dlg.everything.isVisible()
    assert "isn't reachable" in dlg.footer_note.text()

    own = next(b for b in dlg.vpn_group.buttons() if b.property("choice") == "own")
    own.click()
    assert ctx.pref("vpn_choice", "") == "own" and not dlg.get_warp.isVisible()

    fake_setup["net"] = "ok"
    assert pump(lambda: dlg.net.button.isEnabled())  # disabled while a check is running
    dlg.net.button.click()  # Test again
    assert pump(lambda: dlg.network.ok)
    assert not dlg.vpn_box.isVisible() and dlg.footer_note.text() == "All set."
    dlg.done_btn.click()
    assert ctx.pref("setup_done", False) is True
    ctx.shutdown()


def test_main_window_opens_setup_when_not_ready(fake_setup, tmp_path):
    from ui.main_window import MainWindow
    from ui.setup_dialog import SetupDialog

    ctx = ui_fakes.fake_context(tmp_path, with_history=False)
    win = MainWindow(ctx)
    win.show()
    win.start()
    assert pump(lambda: isinstance(getattr(win, "_setup_dialog", None), SetupDialog), timeout=4)
    assert win.banner.isVisible() and "Open Setup" in win.banner.text()
    win._setup_dialog.close()
    win.close()
    ctx.shutdown()


def test_search_blocked_offers_connection_check(tmp_path):
    from ui.main_window import MainWindow

    ctx = ui_fakes.fake_context(tmp_path, with_history=False)

    def blocked(_q):
        raise SiteUnreachable("Can't reach hianime from your network. Some internet providers block it. "
                              "Turn on a VPN such as Cloudflare WARP, then try again.")
    ctx.catalog.hianime.search = blocked
    win = MainWindow(ctx)
    win.go(win.search)
    win.search.box.setText("frieren")
    win.search._search()
    assert pump(lambda: "VPN" in win.search.empty.text())
    assert "Check the connection" in win.search.empty.text()
    opened = []
    win.open_setup = lambda: opened.append(True)  # noqa: E731
    win.search.setupRequested.disconnect()
    win.search.setupRequested.connect(win.open_setup)
    win.search.empty.linkActivated.emit("#setup")
    assert opened
    win.close()
    ctx.shutdown()


def test_check_network_runs_a_real_search():
    urls = []

    class Recorder(FakeClient):
        def fetch(self, url, referer=None):
            urls.append(url)
            return super().fetch(url, referer)

    setup.check_network(Recorder(FetchResult(0, 200, fake_site._search_page())), control=lambda: True,
                        stream_probe=lambda c, r: None)
    assert urls == ["https://hianime.at/search?keyword=one+piece"]


def test_dub_falls_back_to_sub(tmp_path):
    from ui.main_window import MainWindow

    ctx = ui_fakes.fake_context(tmp_path, with_history=False)
    ctx.set_pref("dub", True)
    bridge = ctx.bridge
    original = bridge.resolve

    def resolve(req):
        if req.dub:  # hianime has no dub for this one
            bridge._n += 1
            rid = f"nodub{bridge._n}"
            bridge.requests.append(req)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(20, lambda: bridge.failed.emit(rid, "No sources found for dub!"))
            return rid
        return original(req)

    bridge.resolve = resolve
    win = MainWindow(ctx)
    lantern = ui_fakes.slug("The Lantern Keeper", 1)
    ctx.store.upsert_show(lantern, "The Lantern Keeper")
    win.open_item(ctx.store.get_show(lantern))
    assert pump(lambda: win.detail.grid.model_.items)
    win.detail.play("2")
    assert pump(lambda: ctx.player.launched)
    assert [r.dub for r in bridge.requests] == [True, False]
    assert pump(lambda: "playing subbed" in win.toast.text())
    assert ctx.pref("dub", False) is True  # the preference itself is untouched
    win.close()
    ctx.shutdown()


# -- Blocked video servers (search works, playback doesn't) --------------------------------

def test_error_message_names_the_blocked_server():
    stderr = ("Connection error: could not fetch https://zokoanime.video/stream/mal/21/1/sub "
              "(no HTTP response; curl exit 35)\nNo sources found for sub!\n")
    msg = ani_cli.error_message("", stderr, 1)
    assert "zokoanime.video" in msg and "VPN" in msg
    assert "No sources" not in msg
    # a genuine missing dub (no connection error) is left alone, so the sub fallback still applies
    assert ani_cli.error_message("", "No sources found for dub!\n", 1) == "No sources found for dub!"


def test_check_network_reports_stream_block():
    ok_search = FakeClient(FetchResult(0, 200, fake_site._search_page()))
    blocked = setup.check_network(ok_search, control=lambda: True,
                                  stream_probe=lambda c, r: "Can't reach zokoanime.video (hianime's video server)… VPN")
    assert blocked.state == "blocked" and "zokoanime.video" in blocked.message
    skipped = setup.check_network(ok_search, control=lambda: True, stream_probe=lambda c, r: setup.SKIPPED)
    assert skipped.ok and "once ani-cli is installed" in skipped.message
    full = setup.check_network(ok_search, control=lambda: True, stream_probe=lambda c, r: None)
    assert full.ok and "video servers are reachable" in full.message


@pytest.fixture
def fake_net(tmp_path, monkeypatch):
    for key, value in fake_site.build(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANIGUI_HOME", str(tmp_path / "anigui"))
    monkeypatch.setenv("ANI_CLI_HIST_DIR", str(tmp_path / "hist"))
    (tmp_path / "home").mkdir()
    # fake_site serves "frieren"; point the probe at it
    monkeypatch.setattr(setup, "PROBE_QUERY", "frieren")
    return tmp_path


@pytest.mark.skipif(not shutil.which("ani-cli"), reason="ani-cli not installed")
def test_stream_check_end_to_end(fake_net):
    client = HianimeClient()
    results = client.search("frieren")
    assert setup.stream_check(client, results) is None
    status = setup.check_network(client, control=lambda: True)
    assert status.ok and "video servers are reachable" in status.message


@pytest.mark.skipif(not shutil.which("ani-cli"), reason="ani-cli not installed")
def test_stream_check_finds_blocked_embed_server(fake_net, monkeypatch):
    monkeypatch.setenv("FAKE_BLOCKED_HOSTS", "embed.example")
    client = HianimeClient()
    status = setup.check_network(client, control=lambda: True)
    assert status.state == "blocked"
    assert "embed.example" in status.message and "VPN" in status.message


@pytest.mark.skipif(not shutil.which("ani-cli"), reason="ani-cli not installed")
def test_stream_check_finds_blocked_cdn(fake_net, monkeypatch):
    monkeypatch.setenv("FAKE_BLOCKED_HOSTS", "cdn.example/hls")
    client = HianimeClient()
    status = setup.check_network(client, control=lambda: True)
    assert status.state == "blocked" and "cdn.example" in status.message


@pytest.mark.skipif(not shutil.which("ani-cli"), reason="ani-cli not installed")
def test_playback_error_names_blocked_server(fake_net, monkeypatch):
    monkeypatch.setenv("FAKE_BLOCKED_HOSTS", "embed.example")
    with pytest.raises(ani_cli.AniCliError, match="embed.example"):
        ani_cli.resolve_stream(ani_cli.ResolveRequest(query="frieren", index=1, episode="1"))


def test_setup_offers_iina_when_chosen_but_only_mpv_installed(fake_setup, tmp_path):
    from ui.setup_dialog import SetupDialog

    fake_setup.update(ani_cli="5.1.6", player="mpv", net="ok")
    ctx = ui_fakes.fake_context(tmp_path, with_history=False)
    ctx.set_pref("player", "iina")
    dlg = SetupDialog(ctx)
    dlg.show()
    assert pump(lambda: dlg.status is not None)
    assert dlg.player.button.isVisible() and dlg.player.button.text() == "Install IINA"
    assert "only mpv" in dlg.player.detail.text()
    assert pump(lambda: dlg.player.button.isEnabled())
    dlg.player.button.click()
    assert pump(lambda: dlg.status.iina)
    assert "IINA" in dlg.player.detail.text() and not dlg.player.button.isVisible()

    ctx.set_pref("player", "auto")  # Auto with mpv only: nothing to do
    fake_setup["player"] = "mpv"
    dlg2 = SetupDialog(ctx)
    assert pump(lambda: dlg2.status is not None)
    assert not dlg2.player.button.isVisible()


def test_player_falls_back_when_chosen_one_is_missing(monkeypatch):
    from core import player as player_mod
    from core.ani_cli import StreamInfo

    launched = []
    monkeypatch.setattr(player_mod, "find_player",
                        lambda pref=None: None if pref == "iina" else ("mpv", "/opt/homebrew/bin/mpv"))
    monkeypatch.setattr(player_mod.subprocess, "Popen", lambda cmd, **_k: launched.append(cmd))
    info = StreamInfo(url="https://cdn.example/a.m3u8", referrer=None, title="T")
    assert player_mod.Player("/tmp/x.sock").launch(info, "T", preferred="iina", track=False) == "mpv"
    assert launched[0][0] == "/opt/homebrew/bin/mpv"

    monkeypatch.setattr(player_mod, "find_player", lambda pref=None: None)
    with pytest.raises(player_mod.PlayerError, match="Open Setup"):
        player_mod.Player().launch(info, "T", preferred="iina")
