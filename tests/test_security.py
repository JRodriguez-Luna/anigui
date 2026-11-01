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
    with pytest.raises(setup.SetupError, match="unexpected name"):
        setup.latest_ani_cli(lambda url: json.dumps({"tag_name": "main; rm -rf"}).encode())
