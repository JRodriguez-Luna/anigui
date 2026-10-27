"""Step 1 tests. Offline: a fake curl serves fixtures; the real ani-cli script runs.

End-to-end tests need ani-cli on PATH (brew install ani-cli) and are skipped otherwise.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_site  # noqa: E402
from core.ani_cli import (  # noqa: E402
    AniCliError,
    ResolveRequest,
    build_command,
    error_message,
    parse_capture,
    resolve_stream,
)
from core.hianime import (  # noqa: E402
    CloudflareBlocked,
    HianimeClient,
    normalize_query,
    parse_episodes,
    parse_search,
)

HAS_ANI_CLI = shutil.which("ani-cli") is not None
needs_ani_cli = pytest.mark.skipif(not HAS_ANI_CLI, reason="ani-cli not installed")


@pytest.fixture
def site(tmp_path, monkeypatch):
    for key, value in fake_site.build(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANI_CLI_HIST_DIR", str(tmp_path / "hist"))
    (tmp_path / "home").mkdir()
    return tmp_path


# -- Pure parsing -----------------------------------------------------------------

def test_parse_search_order_posters_and_sidebar_cut():
    results = parse_search(fake_site._search_page())
    assert [r.anime_id for r in results] == [fake_site.ANIME_ID, "frieren-mini-anime-19001"]
    assert results[0].index == 1 and results[1].index == 2
    assert results[0].title == fake_site.TITLE
    assert results[1].title == "Frieren Mini & Friends"
    assert results[0].poster == f"https://img.example/{fake_site.ANIME_ID}.jpg"
    assert all(r.anime_id != "one-piece-100" for r in results)  # sidebar excluded


def test_parse_episodes():
    eps = parse_episodes(fake_site._episodes_json(fake_site.ANIME_ID, ["1", "2", "12.5"]), fake_site.ANIME_ID)
    assert [e.number for e in eps] == ["1", "2", "12.5"]
    assert [e.episode_id for e in eps] == ["101", "102", "103"]
    assert eps[0].title == "Episode 1 title"


def test_parse_episodes_ignores_other_slugs():
    page = fake_site._episodes_json("some-other-show-5", ["1"])
    assert parse_episodes(page, fake_site.ANIME_ID) == []


def test_normalize_query():
    assert normalize_query("  Frieren:  Beyond&Journey ") == "Frieren Beyond Journey"
    assert normalize_query("re:zero") == "re zero"


def test_parse_capture():
    data = b"\0".join([
        b"--referrer=https://embed.example/",
        b"--audio-file=https://cdn/a.m3u8",
        b"--sub-file=https://cdn/en.vtt",
        b"--script-opts=skip-op_start=10",
        b"--force-media-title=Show Episode 1",
        b"https://cdn/1080/index.m3u8",
    ]) + b"\0"
    info = parse_capture(data)
    assert info.url == "https://cdn/1080/index.m3u8"
    assert info.referrer == "https://embed.example/"
    assert info.audio_url == "https://cdn/a.m3u8"
    assert info.subtitle_url == "https://cdn/en.vtt"
    assert info.title == "Show Episode 1"
    assert info.extra_args == ("--script-opts=skip-op_start=10",)


def test_parse_capture_rejects_empty_and_bad_url():
    with pytest.raises(AniCliError):
        parse_capture(b"")
    with pytest.raises(AniCliError):
        parse_capture(b"--referrer=x\0not-a-url\0")


def test_build_command():
    req = ResolveRequest(query="-frieren!!", index=2, episode="3", dub=True, quality="720", skip_intro=True)
    cmd, env = build_command(req, "/bin/ani-cli", "/x/anigui-mpv-shim", "/tmp/cap")
    assert cmd == ["/bin/ani-cli", "-S", "2", "-e", "3", "-q", "720", "--exit-after-play", "--dub", "--skip", "frieren!!"]
    assert env["ANI_CLI_PLAYER"] == "/x/anigui-mpv-shim"
    assert env["ANIGUI_CAPTURE"] == "/tmp/cap"
    assert "/opt/homebrew/bin" in env["PATH"]


def test_error_message_strips_ansi():
    msg = error_message("", "\x1b[2K\r\x1b[1;31mInvalid episode!\x1b[0m\n", 1)
    assert msg == "Invalid episode!"


# -- Python client against the fake site -----------------------------------------

def test_client_search_and_episodes(site):
    client = HianimeClient()
    results = client.search("Frieren")
    assert results[0].anime_id == fake_site.ANIME_ID
    eps = client.episodes(results[0].anime_id)
    assert [e.number for e in eps] == ["1", "2", "3"]


def test_client_detects_cloudflare(tmp_path, monkeypatch):
    for key, value in fake_site.build(tmp_path, cloudflare=True).items():
        monkeypatch.setenv(key, value)
    with pytest.raises(CloudflareBlocked):
        HianimeClient().search("frieren")


# -- Real ani-cli end to end ------------------------------------------------------

@needs_ani_cli
def test_resolve_sub_best(site):
    info = resolve_stream(ResolveRequest(query="frieren", index=1, episode="1"))
    assert info.url == "https://cdn.example/hls/101/sub/1080/index.m3u8"
    assert info.referrer == "https://embed.example/"
    assert info.subtitle_url == "https://cdn.example/subs/101-en.vtt"
    # Separate audio tracks depend on the ani-cli version; only check it when present.
    assert info.audio_url in (None, "https://cdn.example/hls/101/sub/audio/eng.m3u8")
    assert info.title == f"{fake_site.TITLE} Episode 1"


@needs_ani_cli
def test_resolve_dub_720_episode2(site):
    info = resolve_stream(ResolveRequest(query="frieren", index=1, episode="2", dub=True, quality="720"))
    assert info.url == "https://cdn.example/hls/102/dub/720/index.m3u8"


@needs_ani_cli
def test_search_parity_with_ani_cli(site):
    """Index 2 in our results must be what ani-cli -S 2 picks."""
    ours = HianimeClient().search("frieren")
    info = resolve_stream(ResolveRequest(query="frieren", index=2, episode="1"))
    assert ours[1].title in (info.title or "")


@needs_ani_cli
def test_resolve_invalid_episode_reports_ani_cli_error(site):
    with pytest.raises(AniCliError, match="Invalid episode"):
        resolve_stream(ResolveRequest(query="frieren", index=1, episode="99"))


@needs_ani_cli
def test_qprocess_bridge(site):
    from PySide6.QtCore import QCoreApplication, QTimer

    from core.cli_bridge import CliBridge

    app = QCoreApplication.instance() or QCoreApplication([])
    bridge = CliBridge()
    got: dict = {"progress": []}

    def finish(key, value):
        got[key] = value
        if "ok" in got and "err" in got:
            app.quit()

    bridge.streamResolved.connect(lambda rid, info: finish("ok", (rid, info)))
    bridge.failed.connect(lambda rid, msg: finish("err", (rid, msg)))
    bridge.progress.connect(lambda rid, line: got["progress"].append(line))

    good = bridge.resolve(ResolveRequest(query="frieren", index=1, episode="3"))
    bad = bridge.resolve(ResolveRequest(query="frieren", index=1, episode="99"))
    QTimer.singleShot(30000, app.quit)
    app.exec()

    assert got["ok"][0] == good
    assert got["ok"][1].url == "https://cdn.example/hls/103/sub/1080/index.m3u8"
    assert got["err"] == (bad, "Invalid episode!")
    assert any("links fetched" in line for line in got["progress"])
    assert bridge.active() == []
    assert not list(Path(tempfile.gettempdir()).glob("anigui-*.args"))
