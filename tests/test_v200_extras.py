"""2.0 stage 3c: Sharper picture, subtitle style settings, Now Playing, Downloads, Welcome."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_step4 import STARFALL, pump, win  # noqa: E402,F401
from test_v1110 import play_inside  # noqa: E402


# -- Sharper picture -----------------------------------------------------------------------------

def test_anime4k_shaders_are_bundled_with_their_license():
    from core import sharper
    assert sharper.available()
    value = sharper.shaders_value(True)
    assert value.count(":") == len(sharper.SHADERS) - 1 and "Anime4K_Upscale_CNN_x2_M.glsl" in value
    assert sharper.shaders_value(False) == ""
    assert "MIT License" in (sharper.folder() / "LICENSE").read_text()
    spec = (ROOT / "packaging" / "AniGUI.spec").read_text()
    assert '"assets" / "anime4k"' in spec


def test_sharper_picture_is_off_until_you_switch_it_on(win):
    from core import sharper
    assert win.ctx.pref("sharper") is False
    mpv = play_inside(win)
    mpv.send_event("file-loaded")
    pump(lambda: False, 0.3)
    assert not any(c[:2] == ["set_property", "glsl-shaders"] for c in mpv.commands)
    host = win.player_host
    host.menu_test = True
    menu = host._menu()
    act = next(a for a in menu.actions() if a.text() == "Sharper picture")
    assert act.isCheckable() and not act.isChecked()
    act.trigger()
    assert win.ctx.pref("sharper") is True
    assert pump(lambda: ["set_property", "glsl-shaders", sharper.shaders_value(True)] in mpv.commands)
    mpv.commands.clear()
    mpv.send_event("file-loaded")                     # the next episode keeps it
    assert pump(lambda: ["set_property", "glsl-shaders", sharper.shaders_value(True)] in mpv.commands)
    host.set_sharper(False)
    assert pump(lambda: ["set_property", "glsl-shaders", ""] in mpv.commands)
    assert win.ctx.pref("sharper") is False


def test_playback_settings_has_sharper_and_subtitle_style(win):
    from ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(win.ctx, win)
    for key in ("sharper", "sub_size", "sub_color", "sub_box"):
        assert key in dlg.controls
    mpv = play_inside(win)
    mpv.send_event("file-loaded")
    assert pump(lambda: not win.playback.session.loading)
    mpv.commands.clear()
    combo = dlg.controls["sub_size"]
    combo.setCurrentIndex(next(i for i in range(combo.count()) if combo.itemData(i) == "huge"))
    assert win.ctx.pref("sub_size") == "huge"
    assert pump(lambda: ["set_property", "sub-scale", 1.55] in mpv.commands)   # right away, mid-episode
    win.ctx.set_pref("sub_size", "normal")
    dlg.deleteLater()


# -- Now Playing and media keys ------------------------------------------------------------------

class FakeNowPlaying:
    ok = True

    def __init__(self):
        self.started, self.shown, self.cleared, self.on_command = False, [], 0, None

    def start(self, on_command):
        self.started, self.on_command = True, on_command
        return True

    def stop(self):
        self.started = False
        self.cleared += 1

    def show(self, *args):
        self.shown.append(args)


def test_core_now_playing_does_nothing_off_macos():
    from core.nowplaying import NowPlaying
    np_ = NowPlaying()
    if sys.platform != "darwin":
        assert not np_.ok and not np_.start(lambda *_: None)
        np_.show("Episode 1", "x", 0, 10, True)
        np_.clear()
        np_.stop()


def test_media_keys_control_the_built_in_player(win):
    from ui.now_playing import NowPlayingBridge
    fake = FakeNowPlaying()
    bridge = NowPlayingBridge(win.ctx, win.playback, win.player_host, win, core=fake)
    assert win.ctx.pref("media_keys") is True
    bridge.refresh()
    assert not fake.started                           # nothing playing: the keys stay with Music
    mpv = play_inside(win)
    mpv.send_event("file-loaded")
    assert pump(lambda: not win.playback.session.loading)
    bridge.refresh()
    assert fake.started and fake.shown
    title, show, _pos, _dur, playing, _poster = fake.shown[-1]
    assert title == "Episode 5" and show and playing
    bridge.refresh()
    assert len(fake.shown) == 1                       # nothing changed: macOS isn't told again
    for name, value, expect in (("toggle", None, ["cycle", "pause"]),
                                ("pause", None, ["set_property", "pause", True]),
                                ("play", None, ["set_property", "pause", False]),
                                ("previous", None, ["seek", "0", "absolute"]),
                                ("seek", 600.0, ["seek", "600.0", "absolute"])):
        fake.on_command(name, value)                  # macOS calls this; handled right after
        assert pump(lambda e=expect: e in mpv.commands), name
    win.playback.session.now.paused = True
    bridge.refresh()
    assert fake.shown[-1][4] is False
    win.ctx.set_pref("media_keys", False)
    bridge.refresh()
    assert not fake.started and fake.cleared == 1     # handed back
    win.ctx.set_pref("media_keys", True)


# -- Downloads -----------------------------------------------------------------------------------

import contextlib  # noqa: E402
import http.server  # noqa: E402
import threading  # noqa: E402

import pytest  # noqa: E402


def _encrypt(key, iv, data):
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    padder = padding.PKCS7(128).padder()
    raw = padder.update(data) + padder.finalize()
    e = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return e.update(raw) + e.finalize()


class _Site:
    """A tiny HLS server: master → video (AES-128) + separate audio, subtitles, and a plain mp4."""

    KEY = bytes(range(16))

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.seen: list[tuple[str, str | None]] = []   # (path, Referer)
        self.video = [f"video-{i}-".encode() * 500 for i in range(5)]
        self.audio = [f"audio-{i}-".encode() * 300 for i in range(3)]
        self.files["/key.bin"] = self.KEY
        media = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-MEDIA-SEQUENCE:7",
                 '#EXT-X-KEY:METHOD=AES-128,URI="/key.bin"']
        for i, chunk in enumerate(self.video):
            iv = (7 + i).to_bytes(16, "big")
            self.files[f"/v/seg{i}.ts"] = _encrypt(self.KEY, iv, chunk)
            media += ["#EXTINF:4.0,", f"seg{i}.ts"]
        media.append("#EXT-X-ENDLIST")
        self.files["/v/index.m3u8"] = "\n".join(media).encode()
        amedia = ["#EXTM3U", "#EXT-X-MAP:URI=\"init.mp4\""]
        self.files["/a/init.mp4"] = b"INIT"
        for i, chunk in enumerate(self.audio):
            self.files[f"/a/{i}.m4s"] = chunk
            amedia += ["#EXTINF:4.0,", f"{i}.m4s"]
        self.files["/a/index.m3u8"] = "\n".join(amedia).encode()
        self.files["/master.m3u8"] = "\n".join([
            "#EXTM3U",
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="Japanese",DEFAULT=YES,URI="a/index.m3u8"',
            '#EXT-X-STREAM-INF:BANDWIDTH=800000,AUDIO="aud"', "low/index.m3u8",
            '#EXT-X-STREAM-INF:BANDWIDTH=4000000,AUDIO="aud"', "v/index.m3u8",
        ]).encode()
        self.files["/subs/en.vtt"] = b"WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n"
        self.files["/movie.mp4"] = b"MP4DATA" * 100000

    def handler(self):
        site = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_GET(self):
                site.seen.append((self.path, self.headers.get("Referer")))
                body = site.files.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                start = 0
                rng = self.headers.get("Range")
                if rng and rng.startswith("bytes="):
                    start = int(rng[6:].split("-")[0])
                    self.send_response(206)
                else:
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body) - start))
                self.end_headers()
                self.wfile.write(body[start:])
        return H


@pytest.fixture
def site():
    s = _Site()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), s.handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    s.base = f"http://127.0.0.1:{server.server_address[1]}"
    yield s
    server.shutdown()
    server.server_close()


def test_hls_download_decrypts_and_joins_the_pieces(site, tmp_path):
    from core.ani_cli import StreamInfo
    from core.downloads import Downloader
    seen = []
    info = StreamInfo(url=site.base + "/master.m3u8", referrer="https://ref.example/", title="x",
                      subtitle_url=site.base + "/subs/en.vtt")
    saved = Downloader(progress=seen.append).download(info, tmp_path / "Show", "Show: Ep/1")
    assert saved.video.name == "Show Ep 1.ts"                   # no / or : in file names
    assert saved.video.read_bytes() == b"".join(site.video)    # decrypted, in order
    assert saved.audio.read_bytes() == b"INIT" + b"".join(site.audio)
    assert saved.audio.suffix == ".m4a" and saved.subtitles.read_text().startswith("WEBVTT")
    assert seen and seen[-1] == 1.0 and seen == sorted(seen)
    assert all(ref == "https://ref.example/" for _p, ref in site.seen)   # same as playing it
    assert not any("low/" in p for p, _r in site.seen)         # the best quality only
    assert not list((tmp_path / "Show").glob("*.part"))
    assert saved.size == sum(p.stat().st_size for p in (saved.video, saved.audio, saved.subtitles))


def test_plain_video_downloads_and_cancel_leaves_nothing(site, tmp_path):
    from core.ani_cli import StreamInfo
    from core.downloads import Cancelled, Downloader
    info = StreamInfo(url=site.base + "/movie.mp4", referrer=None, title="x")
    saved = Downloader().download(info, tmp_path, "Movie")
    assert saved.video.read_bytes() == site.files["/movie.mp4"] and saved.audio is None
    flag = {"stop": False}

    def progress(f):
        if f > 0.2:
            flag["stop"] = True
    with pytest.raises(Cancelled):
        Downloader(progress=progress, cancelled=lambda: flag["stop"]).download(info, tmp_path / "c", "Movie")
    assert list((tmp_path / "c").iterdir()) == []


def test_bad_streams_say_why(site, tmp_path):
    from core.ani_cli import StreamInfo
    from core.downloads import DownloadError, Downloader, parse_media
    with pytest.raises(DownloadError):
        parse_media("#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI=\"k\"\n#EXTINF:4,\na.ts\n", "http://x/")
    with pytest.raises(DownloadError):
        Downloader().download(StreamInfo(url="file:///etc/passwd", referrer=None, title="x"), tmp_path, "x")
    with pytest.raises(DownloadError):
        Downloader().download(StreamInfo(url=site.base + "/missing.m3u8", referrer=None, title="x"), tmp_path, "x")


def test_only_saved_media_files_count_as_playable(tmp_path):
    from core.ani_cli import is_download, is_playable
    f = tmp_path / "Ep 1.ts"
    f.write_bytes(b"x")
    assert is_download(str(f)) and is_playable(str(f)) and is_playable("https://a.example/x.m3u8")
    assert not is_download("relative.ts") and not is_download(str(tmp_path / "nope.ts"))
    sh = tmp_path / "run.sh"
    sh.write_text("x")
    assert not is_download(str(sh)) and not is_download(str(f) + "\n--script=x")


def test_download_an_episode_then_watch_it_offline(win, site, monkeypatch, tmp_path):
    from core.ani_cli import StreamInfo
    win.ctx.set_pref("downloads_folder", str(tmp_path / "dl"))
    dl = win.ctx.downloads
    store = win.ctx.store
    win.open_item(store.get_show(STARFALL))
    assert pump(lambda: win.detail.grid.model_.items)
    resolved = []

    def prepare(anime_id, title, episode, on_ready, on_fail, on_status=None, online=False):
        resolved.append((episode, online))
        on_ready(StreamInfo(url=site.base + "/master.m3u8", referrer=None, title=title,
                            subtitle_url=site.base + "/subs/en.vtt"))
        return None
    monkeypatch.setattr(dl.resolver, "prepare", prepare)
    grid = win.detail.grid
    grid.menu_test = True
    row = next(i for i, it in enumerate(grid.model_.items) if it.number == "5")
    grid._menu(grid.visualRect(grid.model_.index(row)).center())
    act = next(a for a in grid.last_menu.actions() if a.text() == "Download")
    act.trigger()
    assert resolved == [("5", True)]                     # always the real stream for a download
    assert pump(lambda: store.download(STARFALL, "5") is not None, 10)
    d = store.download(STARFALL, "5")
    assert d.present and d.size > 0 and d.subtitles and d.video.startswith(str(tmp_path / "dl"))
    assert pump(lambda: grid.model_.items[row].saved == "saved")
    grid._menu(grid.visualRect(grid.model_.index(row)).center())
    assert "Remove download" in [a.text() for a in grid.last_menu.actions()]
    # My Library → Downloads
    win.open_library() if hasattr(win, "open_library") else None
    win.library.show_overview("downloads")
    assert win.library.stack.currentWidget() is win.library.downloads
    assert win.library.downloads.model_.rowCount() == 1
    # plays from the Mac, no stream lookup
    monkeypatch.undo()
    mpv = play_inside(win)
    assert any(c[:2] == ["loadfile", d.video] for c in mpv.commands) or \
        win.ctx.player.launched[-1][0].url == d.video
    dl.remove(STARFALL, "5")
    assert store.download(STARFALL, "5") is None and not Path(d.video).exists()
    win.ctx.set_pref("downloads_folder", "")


# -- Welcome -------------------------------------------------------------------------------------

def test_welcome_is_for_new_installs_only(win):
    from ui.welcome import should_welcome
    store = win.ctx.store
    assert store.all_progress() or store.library_all()       # the test window has history
    win.ctx.set_pref("welcomed", False)
    assert not should_welcome(win.ctx) and win.ctx.pref("welcomed") is True


def test_welcome_pages_set_name_and_color_and_import(win, monkeypatch):
    from ui.welcome import WelcomeDialog
    win.ctx.set_pref("welcomed", False)
    asked = []
    dlg = WelcomeDialog(win.ctx, win)
    dlg.importAniList.connect(asked.append)
    assert dlg.pages.currentIndex() == 0 and not dlg.back.isVisible()
    dlg.next.click()
    dlg.name.setText("  Chuy ")
    teal = next(b for b in dlg.accents.buttons() if b.property("accent") != win.ctx.pref("accent"))
    teal.click()
    assert win.ctx.pref("accent") == teal.property("accent")
    dlg.next.click()
    assert win.ctx.pref("your_name") == "Chuy" and dlg.pages.currentIndex() == 2
    dlg.user.setText("someone")
    dlg._import_anilist()
    assert asked == ["someone"] and dlg.pages.currentIndex() == 3
    assert dlg.next.text() == "Start watching" and not dlg.skip.isVisible()
    dlg.next.click()
    assert win.ctx.pref("welcomed") is True and dlg.result() == 1
    win.ctx.set_pref("your_name", "")
    win.ctx.set_pref("accent", "ember")


def test_welcome_skip_and_escape_both_count(win):
    from ui.welcome import WelcomeDialog
    for close in ("skip", "reject"):
        win.ctx.set_pref("welcomed", False)
        dlg = WelcomeDialog(win.ctx, win)
        dlg.skip.click() if close == "skip" else dlg.reject()
        assert win.ctx.pref("welcomed") is True


# -- Stage 4: the upgrade to 2.0 -----------------------------------------------------------------

def test_upgrading_a_1x_database_backs_it_up_first(tmp_path):
    import sqlite3
    import zipfile
    from core.store import SCHEMA_VERSION, Store
    db = tmp_path / "anigui.db"
    s = Store(db)
    s.upsert_show("a", "A")
    s.set_in_library("a", True)                     # My List in 1.x
    s.record_progress("a", "3", 600, 1400)
    assert s.upgraded_from is None and s.upgrade_backup is None      # a new database: nothing to back up
    s._conn().execute("PRAGMA user_version=2")      # what 1.11 left behind
    s.close()
    s2 = Store(db)
    assert s2.upgraded_from == 2 and s2.upgrade_backup.is_file()
    assert s2.upgrade_backup.parent == tmp_path / "Backups"
    with zipfile.ZipFile(s2.upgrade_backup) as z:
        assert {"manifest.json", "anigui.db"} <= set(z.namelist())
        z.extract("anigui.db", tmp_path / "x")
    old = sqlite3.connect(tmp_path / "x" / "anigui.db")
    assert old.execute("PRAGMA user_version").fetchone()[0] == 2           # as it was before
    assert s2._conn().execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert [sh.anime_id for sh in s2.list_shows(0)] == ["a"]              # My List → Saved
    assert s2.get_progress("a", "3").position == 600
    from core.backup import read_manifest
    assert read_manifest(s2.upgrade_backup)["reason"] == "before upgrade"  # Restore can use it
    s3 = Store(db)
    assert s3.upgraded_from is None                                        # only once


def test_new_features_start_off():
    from ui.context import DEFAULTS
    for key in ("lock_app", "lock_mature", "auto_backup", "spoiler_shield", "sharper", "sub_box"):
        assert DEFAULTS[key] is False, key
    assert DEFAULTS["weekly_goal"] == 0 and DEFAULTS["your_name"] == "" and DEFAULTS["accent"] == "ember"
    assert DEFAULTS["app_icon"] == "classic" and DEFAULTS["home_rows"] == ""


def test_updating_from_1x_shows_the_tour_once(win, monkeypatch):
    from core import __version__
    from ui.tour import TourDialog
    assert __version__.startswith("2.")
    win.ctx.set_pref("setup_done", True)
    win.ctx.set_pref("last_version", "1.11.1")
    dlg = win._maybe_show_whats_new()
    assert isinstance(dlg, TourDialog)
    opened = []
    monkeypatch.setattr(win, "open_settings", lambda section=None: opened.append(section))
    for _ in range(dlg.pages.count() - 1):
        dlg.next.click()
    assert dlg.next.text() == "Done" and not dlg.skip.isVisible()
    btn = next(b for b in dlg.pages.currentWidget().findChildren(type(dlg.next)) if b.text() == "Pick your color and name")
    btn.click()
    assert pump(lambda: opened == ["Make it yours"])
    assert win._maybe_show_whats_new() is None                          # once
    win.ctx.set_pref("last_version", "1.9.0")
    assert isinstance(win._maybe_show_whats_new(), TourDialog)
