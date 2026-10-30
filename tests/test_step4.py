"""Step 4 tests: mpv IPC, progress tracking, resume, auto-next. A fake mpv serves the socket."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402

import ui_fakes  # noqa: E402
from core.mpv_ipc import MpvIpc  # noqa: E402
from ui import playback  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

STARFALL = ui_fakes.slug("Starfall Academy", 0)      # 24 eps, ep 4 in progress at 610/1420
LANTERN = ui_fakes.slug("The Lantern Keeper", 1)     # 12 eps, never watched


def pump(cond=lambda: False, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(playback, "SAVE_EVERY_S", 0.0)
    monkeypatch.setattr(playback, "COUNTDOWN_S", 0)
    monkeypatch.setattr(playback, "IPC_TIMEOUT_MS", 1500)


@pytest.fixture
def win(tmp_path):
    ctx = ui_fakes.fake_context(tmp_path)
    w = MainWindow(ctx)
    w.resize(1280, 820)
    w.show()
    yield w
    if ctx.player.mpv:
        ctx.player.mpv.server.close()
    w.close()
    ctx.shutdown()


def start_playing(w, anime_id, title, episode):
    w.open_item(w.ctx.store.get_show(anime_id) or _show(w, anime_id, title))
    pump(lambda: w.detail.grid.model_.items)
    w.detail.play(episode)
    assert pump(lambda: w.ctx.player.launched and w.playback.session and w.playback.session.alive), "session never connected"
    mpv = w.ctx.player.mpv
    assert pump(lambda: len(mpv.named("observe_property")) == 3)
    return mpv


def _show(w, anime_id, title):
    w.ctx.store.upsert_show(anime_id, title)
    return w.ctx.store.get_show(anime_id)


# -- IPC client ---------------------------------------------------------------------------

def test_ipc_connects_late_and_relays(qtbot_free=None):
    path = os.path.join(tempfile.mkdtemp(prefix="ag-", dir="/tmp"), "s.sock")
    ipc = MpvIpc(path)
    got = {"props": [], "events": []}
    ipc.propertyChanged.connect(lambda n, v: got["props"].append((n, v)))
    ipc.event.connect(lambda n, m: got["events"].append(n))
    ipc.connected.connect(lambda: got.setdefault("connected", True))
    ipc.start(3000)
    holder = {}
    QTimer.singleShot(400, lambda: holder.setdefault("mpv", ui_fakes.FakeMpv(path)))  # player starts late
    assert pump(lambda: got.get("connected"), 3)
    ipc.observe("time-pos")
    mpv = holder["mpv"]
    assert pump(lambda: mpv.named("observe_property"))
    assert mpv.named("observe_property")[0][2] == "time-pos"
    mpv.set_prop("time-pos", 12.5)
    mpv.send_event("end-file", reason="eof")
    assert pump(lambda: got["props"] and got["events"])
    assert got["props"] == [("time-pos", 12.5)] and got["events"] == ["end-file"]
    mpv.server.close()


def test_ipc_gives_up():
    ipc = MpvIpc(os.path.join(tempfile.mkdtemp(prefix="ag-", dir="/tmp"), "none.sock"))
    flag = {}
    ipc.gaveUp.connect(lambda: flag.setdefault("gave_up", True))
    ipc.start(500)
    assert pump(lambda: flag.get("gave_up"), 3)


# -- Tracking -----------------------------------------------------------------------------

def test_progress_saved_and_watched_at_90(win):
    mpv = start_playing(win, LANTERN, "The Lantern Keeper", "2")
    mpv.set_prop("duration", 1440.0)
    mpv.set_prop("time-pos", 300.0)
    assert pump(lambda: (p := win.ctx.store.get_progress(LANTERN, "2")) and p.position == 300.0)
    item = next(i for i in win.detail.grid.model_.items if i.number == "2")
    assert item.state == "progress" and item.playing and abs(item.fraction - 300 / 1440) < 1e-6

    mpv.set_prop("time-pos", 1310.0)  # 91%
    assert pump(lambda: win.ctx.store.get_progress(LANTERN, "2").completed)
    assert next(i for i in win.detail.grid.model_.items if i.number == "2").state == "watched"


def test_resume_passes_start_position(win):
    start_playing(win, STARFALL, "Starfall Academy", "4")
    _info, title, start = win.ctx.player.launched[-1]
    assert start == 610 and title == "Starfall Academy — Episode 4"
    assert pump(lambda: "Resuming episode 4 at 10:10" in win.toast.text())


def test_play_button_shows_resume_time(win):
    win.open_item(win.ctx.store.get_show(STARFALL))
    pump(lambda: win.detail.grid.model_.items)
    assert win.detail.play_btn.text() == "▶  Resume Episode 4  ·  10:10"


def test_auto_next_prefetches_and_loads(win):
    mpv = start_playing(win, LANTERN, "The Lantern Keeper", "5")
    assert pump(lambda: win.playback.session.episodes)
    mpv.set_prop("duration", 1440.0)
    mpv.set_prop("time-pos", 1380.0)  # last two minutes -> prefetch episode 6
    assert pump(lambda: win.playback.session.next_info is not None)
    assert win.ctx.bridge.requests[-1].episode == "6"

    mpv.send_event("end-file", reason="eof")
    assert pump(lambda: mpv.named("loadfile"))
    load = mpv.named("loadfile")[-1]
    assert load[1].endswith(".m3u8") and load[2] == "replace"
    assert ["set_property", "force-media-title", "The Lantern Keeper — Episode 6"] in mpv.commands
    assert ["set_property", "options/start", "none"] in mpv.commands
    assert win.playback.session.now.episode == "6"
    assert win.ctx.store.get_progress(LANTERN, "5").completed
    assert win.ctx.store.get_progress(LANTERN, "6") is not None
    assert pump(lambda: any(i.playing and i.number == "6" for i in win.detail.grid.model_.items))

    mpv.set_prop("time-pos", 42.0)  # positions now count toward episode 6
    assert pump(lambda: win.ctx.store.get_progress(LANTERN, "6").position == 42.0)


def test_auto_next_off(win):
    win.ctx.set_pref("autoplay", False)
    mpv = start_playing(win, LANTERN, "The Lantern Keeper", "5")
    pump(lambda: win.playback.session.episodes)
    mpv.set_prop("duration", 1440.0)
    mpv.set_prop("time-pos", 1400.0)
    mpv.send_event("end-file", reason="eof")
    pump(timeout=0.4)
    assert not mpv.named("loadfile")
    assert win.ctx.store.get_progress(LANTERN, "5").completed


def test_last_episode_says_so(win):
    mpv = start_playing(win, LANTERN, "The Lantern Keeper", "12")
    pump(lambda: win.playback.session.episodes)
    mpv.set_prop("duration", 1440.0)
    mpv.send_event("end-file", reason="eof")
    assert pump(lambda: any(c[:2] == ["show-text", "That was the last episode"] for c in mpv.commands))
    assert not mpv.named("loadfile")


def test_new_play_reuses_open_player(win):
    mpv = start_playing(win, LANTERN, "The Lantern Keeper", "1")
    mpv.set_prop("duration", 1440.0)
    mpv.set_prop("time-pos", 200.0)
    pump(lambda: win.ctx.store.get_progress(LANTERN, "1").position == 200.0)
    launches = len(win.ctx.player.launched)
    win.open_item(win.ctx.store.get_show(STARFALL))
    pump(lambda: win.detail.anime_id == STARFALL and win.detail.grid.model_.items)
    win.detail.play("4")
    assert pump(lambda: mpv.named("loadfile"))
    assert len(win.ctx.player.launched) == launches  # no second window
    assert ["set_property", "options/start", "610"] in mpv.commands
    assert win.playback.session.now.anime_id == STARFALL
    assert win.ctx.store.get_progress(LANTERN, "1").position == 200.0


def test_player_closed_saves_and_ends(win):
    mpv = start_playing(win, LANTERN, "The Lantern Keeper", "3")
    ended = {}
    win.playback.sessionEnded.connect(lambda: ended.setdefault("yes", True))
    mpv.set_prop("duration", 1440.0)
    mpv.set_prop("time-pos", 777.0)
    mpv.quit()
    assert pump(lambda: ended.get("yes"))
    assert win.ctx.store.get_progress(LANTERN, "3").position == 777.0
    assert not win.playback.session.alive


def test_untracked_player_warns(tmp_path):
    ctx = ui_fakes.fake_context(tmp_path)
    ctx.player = ui_fakes.FakePlayer(open_socket=False)
    w = MainWindow(ctx)
    w.show()
    w.open_item(ctx.store.get_show(STARFALL))
    pump(lambda: w.detail.grid.model_.items)
    w.detail.play("5")
    assert pump(lambda: "without progress tracking" in w.toast.text(), timeout=4)
    assert ctx.store.get_progress(STARFALL, "5") is not None  # still recorded as started
    w.close()
    ctx.shutdown()


def test_mark_up_to_here(win):
    win.open_item(win.ctx.store.get_show(STARFALL))
    pump(lambda: win.detail.grid.model_.items)
    win.detail._mark("6", "upto")
    states = {i.number: i.state for i in win.detail.grid.model_.items}
    assert all(states[str(n)] == "watched" for n in range(1, 7)) and states["7"] == "new"
    assert win.detail.play_btn.text() == "▶  Play Episode 7"
    win.detail._mark("6", "unwatched")
    assert next(i for i in win.detail.grid.model_.items if i.number == "6").state == "new"


def test_settings_persist_and_sync(win):
    dlg = win.open_settings("Playback")
    player = dlg.controls["player"]
    player.setCurrentIndex(player.findData("mpv"))
    dlg.controls["autoplay"].setChecked(False)
    assert win.ctx.pref("player", "auto") == "mpv"
    assert win.ctx.pref("autoplay", True) is False

    # Audio and quality are shared with the show page's Sub/Dub and quality controls
    audio = dlg.controls["dub"]
    audio.setCurrentIndex(audio.findData(True))
    assert win.ctx.pref("dub") is True and win.detail.dub_btn.isChecked()
    win.detail.sub_btn.setChecked(True)
    assert win.ctx.pref("dub") is False and audio.currentData() is False
    win.detail.quality.setCurrentIndex(win.detail.quality.findData("720"))
    assert dlg.controls["quality"].currentData() == "720"
    dlg.close()
