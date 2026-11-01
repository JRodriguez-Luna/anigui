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
