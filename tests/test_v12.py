"""v1.2 tests: Settings, built-in skipping, new-episode alerts, What's New."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QCoreApplication  # noqa: E402

import ui_fakes  # noqa: E402
from core import aniskip, http  # noqa: E402
from core.store import Store  # noqa: E402
from ui import playback  # noqa: E402

STARFALL = ui_fakes.slug("Starfall Academy", 0)
LANTERN = ui_fakes.slug("The Lantern Keeper", 1)


def pump(cond=lambda: False, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


def aniskip_body(*items, found=True) -> bytes:
    return json.dumps({"found": found, "statusCode": 200, "message": "ok", "results": [
        {"interval": {"startTime": s, "endTime": e}, "skipType": t, "skipId": f"id{i}", "episodeLength": length}
        for i, (t, s, e, length) in enumerate(items)
    ]}).encode()


# -- AniSkip --------------------------------------------------------------------------------

def test_aniskip_request_and_parse(tmp_path):
    seen = []

    def fetch(url):
        seen.append(url)
        return http.Response(200, {}, aniskip_body(("op", 90.0, 179.5, 1420.0), ("ed", 1330.0, 1419.0, 1420.0),
                                                   ("mixed-op", 0, 3, 1420.0), ("recap", 0.0, 60.0, 1420.0)))

    store = Store(tmp_path / "t.db")
    segs = aniskip.skip_times(21, "7", 1421.0, cache=store, fetch=fetch)
    assert [(s.kind, s.start, s.end) for s in segs] == [("recap", 0.0, 60.0), ("intro", 90.0, 179.5),
                                                       ("ending", 1330.0, 1419.0)]
    assert seen[0].startswith("https://api.aniskip.com/v2/skip-times/21/7?types[]=op&types[]=ed")
    assert "episodeLength=0" in seen[0]
    # cached: no second request
    assert aniskip.skip_times(21, "7", 1421.0, cache=store, fetch=fetch) == segs and len(seen) == 1


def test_aniskip_ignores_other_cuts_and_odd_episodes(tmp_path):
    body = aniskip_body(("op", 90.0, 180.0, 1500.0), ("ed", 1300.0, 1390.0, 1420.0))
    segs = aniskip.parse(body, duration=1420.0)
    assert [s.kind for s in segs] == ["ending"]           # the intro was timed on a 25-minute cut
    assert aniskip.skip_times(21, "7.5", fetch=lambda u: pytest.fail("no lookup")) == []
    assert aniskip.skip_times(0, "7", fetch=lambda u: pytest.fail("no lookup")) == []


def test_aniskip_missing_and_offline(tmp_path):
    store = Store(tmp_path / "t.db")
    calls = []

    def missing(url):
        calls.append(url)
        return http.Response(404, {}, b'{"found":false,"results":[]}')

    assert aniskip.skip_times(5, "1", cache=store, fetch=missing) == []
    assert aniskip.skip_times(5, "1", cache=store, fetch=missing) == [] and len(calls) == 1  # remembered

    def offline(url):
        raise OSError("no route")

    assert aniskip.skip_times(5, "2", cache=store, fetch=offline) == []


def test_segment_contains_leaves_last_second():
    seg = aniskip.Segment("intro", 90.0, 180.0)
    assert seg.contains(90.0) and seg.contains(178.9) and not seg.contains(179.2) and not seg.contains(80)


# -- Skipping during playback -------------------------------------------------------------

@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(playback, "SAVE_EVERY_S", 0.0)
    monkeypatch.setattr(playback, "COUNTDOWN_S", 0)
    monkeypatch.setattr(playback, "IPC_TIMEOUT_MS", 1500)


@pytest.fixture
def win(tmp_path, fast):
    from ui.main_window import MainWindow

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
    if not w.ctx.store.get_show(anime_id):
        w.ctx.store.upsert_show(anime_id, title)
    w.open_item(w.ctx.store.get_show(anime_id))
    pump(lambda: w.detail.grid.model_.items)
    w.detail.play(episode)
    assert pump(lambda: w.ctx.player.launched and w.playback.session and w.playback.session.alive)
    mpv = w.ctx.player.mpv
    assert pump(lambda: len(mpv.named("observe_property")) == 3)
    return mpv


def test_skips_intro_once_and_ending(win, monkeypatch):
    lookups = []
    monkeypatch.setattr(win.ctx.catalog, "mal_id", lambda aid, title: 4242)

    def fake_times(mal, ep, duration, cache=None):
        lookups.append((mal, ep, duration))
        return [aniskip.Segment("intro", 90.0, 180.0), aniskip.Segment("ending", 1330.0, 1420.0)]

    monkeypatch.setattr(aniskip, "skip_times", fake_times)
    win.ctx.set_pref("skip_intro", True)
    win.ctx.set_pref("skip_ending", True)
    win.ctx.set_pref("autoplay", False)
    mpv = start_playing(win, LANTERN, "The Lantern Keeper", "2")
    mpv.set_prop("duration", 1440.0)
    assert pump(lambda: win.playback.session.now.skips)
    assert lookups == [(4242, "2", 1440.0)]

    mpv.set_prop("time-pos", 60.0)
    mpv.set_prop("time-pos", 95.0)
    assert pump(lambda: mpv.named("seek"))
    assert mpv.named("seek")[0][1:] == ["180.00", "absolute"]
    assert ["show-text", "Skipped intro", 2000] in mpv.commands

    mpv.set_prop("time-pos", 120.0)   # the user went back into the intro on purpose: leave it
    mpv.set_prop("time-pos", 1335.0)
    assert pump(lambda: len(mpv.named("seek")) == 2)
    assert mpv.named("seek")[1][1:] == ["1420.00", "absolute"]


def test_skip_lookup_without_duration(win, monkeypatch):
    """Auto-next: mpv may report the duration before AniGUI sees file-loaded. Skips still load."""
    monkeypatch.setattr(win.ctx.catalog, "mal_id", lambda aid, title: 7)
    monkeypatch.setattr(aniskip, "skip_times", lambda mal, ep, duration, cache=None: [aniskip.Segment("intro", 10.0, 100.0)])
    win.ctx.set_pref("skip_intro", True)
    mpv = start_playing(win, LANTERN, "The Lantern Keeper", "4")
    mpv.set_prop("time-pos", 1.0)                          # no duration reported at all
    assert pump(lambda: win.playback.session.now.skips)
    mpv.set_prop("time-pos", 12.0)
    assert pump(lambda: mpv.named("seek"))
    assert mpv.named("seek")[0][1:] == ["100.00", "absolute"]


def test_no_skipping_when_turned_off(win, monkeypatch):
    monkeypatch.setattr(win.ctx.catalog, "mal_id", lambda aid, title: pytest.fail("no lookup when off"))
    win.ctx.set_pref("skip_intro", False)
    mpv = start_playing(win, LANTERN, "The Lantern Keeper", "3")
    mpv.set_prop("duration", 1440.0)
    mpv.set_prop("time-pos", 95.0)
    assert pump(lambda: win.ctx.store.get_progress(LANTERN, "3") and win.ctx.store.get_progress(LANTERN, "3").position == 95.0)
    assert mpv.named("seek") == []


def test_ani_cli_never_gets_skip_flag(win):
    from core.ani_cli import ResolveRequest, build_command

    win.ctx.set_pref("skip_intro", True)
    req = win.ctx.catalog.play_request(LANTERN, "1", title="The Lantern Keeper")
    cmd, _env = build_command(req, "/x/ani-cli", "/x/shim", "/x/cap")
    assert "--skip" not in cmd


# -- New episode alerts ---------------------------------------------------------------------

from core import alerts  # noqa: E402
from core.anilist import Media  # noqa: E402
from core.hianime import Episode  # noqa: E402


def media(anilist_id, status="RELEASING", next_ep=None, episodes=None, mal=None):
    return Media(anilist_id, mal, "T", "T", None, (), None, None, None, "", episodes, status, "TV", (), None,
                 None, None, next_ep, None)


class StubAniList:
    def __init__(self):
        self.shows: dict[int, Media] = {}
        self.calls = 0

    def airing(self, ids):
        self.calls += 1
        return {i: self.shows[i] for i in ids if i in self.shows}


class StubCatalog:
    def __init__(self, store):
        self.store = store
        self.anilist = StubAniList()
        self.eps: dict[str, int] = {}
        self.fetched: list[str] = []

    def episodes(self, anime_id):
        self.fetched.append(anime_id)
        return [Episode(str(n), str(n), None) for n in range(1, self.eps[anime_id] + 1)]

    def enrich(self, anime_id, title, poster=None):
        return None


@pytest.fixture
def followed(tmp_path):
    store = Store(tmp_path / "t.db")
    cat = StubCatalog(store)
    for aid, al in (("frieren-1", 11), ("dandadan-2", 22), ("finished-3", 33)):
        store.upsert_show(aid, aid.split("-")[0].title())
        store.set_anilist_match(aid, al, 1.0)
        store.set_in_library(aid, True)
    cat.anilist.shows = {11: media(11, next_ep=7), 22: media(22, next_ep=4),
                         33: media(33, status="FINISHED", episodes=12)}
    cat.eps = {"frieren-1": 6, "dandadan-2": 3, "finished-3": 12}
    return store, cat


def test_first_check_sets_a_baseline(followed):
    store, cat = followed
    assert alerts.check(store, cat) == []
    assert store.new_episodes() == []
    assert store.watched_latest("frieren-1") == "6"


def test_new_episode_found_once_and_cleared_on_open(followed):
    store, cat = followed
    alerts.check(store, cat)
    cat.fetched.clear()
    assert alerts.check(store, cat) == [] and cat.fetched == []   # nothing aired: hianime isn't asked

    cat.anilist.shows[11] = media(11, next_ep=8)                  # episode 7 aired...
    assert alerts.check(store, cat) == [] and cat.fetched == ["frieren-1"]   # ...but isn't on hianime yet
    cat.eps["frieren-1"] = 7
    fresh = alerts.check(store, cat)
    assert [(n.show.anime_id, n.latest, n.count) for n in fresh] == [("frieren-1", "7", 1)]
    assert alerts.check(store, cat) == []                          # notified once
    assert [n.show.anime_id for n in store.new_episodes()] == ["frieren-1"]   # still on Home

    store.set_latest("frieren-1", "7", seen=True)                  # opened the show
    store.mark_episodes_seen("frieren-1")
    assert store.new_episodes() == []


def test_two_new_episodes_and_scope(followed):
    store, cat = followed
    store.upsert_show("solo-4", "Solo")
    store.set_anilist_match("solo-4", 44, 1.0)
    store.record_progress("solo-4", "2", 100, 1400)                # Continue Watching, not My List
    cat.anilist.shows[44] = media(44, next_ep=3)
    cat.eps["solo-4"] = 2
    alerts.check(store, cat)
    assert store.watched_latest("solo-4") is None                   # not followed with scope=library
    alerts.check(store, cat, "library+continue")
    assert store.watched_latest("solo-4") == "2"

    cat.anilist.shows[22] = media(22, next_ep=6)
    cat.eps["dandadan-2"] = 5
    fresh = alerts.check(store, cat)
    assert [(n.show.anime_id, n.count) for n in fresh] == [("dandadan-2", 2)]
    from ui.alerts import describe
    assert describe(fresh[0]) == "2 new · up to EP 5"


def test_set_latest_for_unsaved_show_is_skipped(tmp_path):
    store = Store(tmp_path / "t.db")
    assert store.set_latest("not-saved-1", "3", seen=True) is False
    assert store.watched_latest("not-saved-1") is None


def test_expected_episode():
    assert alerts.expected_episode(media(1, next_ep=1)) is None
    assert alerts.expected_episode(media(1, next_ep=9)) == 8
    assert alerts.expected_episode(media(1, status="FINISHED", episodes=24)) == 24
    assert alerts.expected_episode(media(1, status="NOT_YET_RELEASED", episodes=12)) is None


def test_home_shows_new_episodes_and_opening_clears(win, monkeypatch):
    ctx = win.ctx
    sent = []
    monkeypatch.setattr(win.alerts.notifier, "notify", lambda title, body: sent.append((title, body)))
    tea = ui_fakes.slug("Tea House on Cloud Street", 4)      # in My List (fake data), 12 episodes
    ctx.store.set_anilist_match(tea, 504, 1.0)
    ctx.store.set_latest(tea, "11")                           # we last saw 11; hianime now lists 12
    real_airing = ctx.catalog.anilist.airing
    monkeypatch.setattr(ctx.catalog.anilist, "airing", lambda ids: {
        504: media(504, next_ep=13), **{k: v for k, v in real_airing(ids).items() if k != 504}})

    win.alerts.check_now()
    assert pump(lambda: not win.alerts.running)
    assert sent == [("Tea House on Cloud Street", "Episode 12 is out")]
    win.home.refresh_local()
    row = win.home.new_row
    assert row.isVisible() and row.model().rowCount() == 1
    from ui.cards import CARD_ROLE
    card = row.model().index(0, 0).data(CARD_ROLE)
    assert card.badge == "NEW · EP 12" and card.subtitle == "Episode 12 is out"
    lib = [row_card for i in range(win.home.library_row.model().rowCount())
           if (row_card := win.home.library_row.model().index(i, 0).data(CARD_ROLE)).payload.anime_id == tea]
    assert lib[0].badge == "NEW · EP 12"
    assert "Tea House" in win.toast.text()

    win.open_item(card.payload)                               # opening the show clears it
    assert pump(lambda: not ctx.store.new_episodes())
    win.go(win.home)
    assert not win.home.new_row.isVisible()


def test_notifications_off_and_alerts_off(win, monkeypatch):
    ctx = win.ctx
    sent = []
    monkeypatch.setattr(win.alerts.notifier, "notify", lambda *a: sent.append(a))
    tea = ui_fakes.slug("Tea House on Cloud Street", 4)
    ctx.store.set_anilist_match(tea, 504, 1.0)
    ctx.store.set_latest(tea, "11")
    monkeypatch.setattr(ctx.catalog.anilist, "airing", lambda ids: {504: media(504, next_ep=13)})
    ctx.set_pref("notify", False)
    win.alerts.check_now()
    assert pump(lambda: not win.alerts.running)
    assert sent == [] and len(ctx.store.new_episodes()) == 1
    ctx.set_pref("alerts", False)
    win.home.refresh_local()
    assert not win.home.new_row.isVisible()
    win.alerts.check_now()
    assert not win.alerts.running                            # automatic checks are off


def test_settings_check_now_reports_status(win, monkeypatch):
    monkeypatch.setattr(win.ctx.catalog.anilist, "airing", lambda ids: {})
    dlg = win.open_settings("New Episodes")
    dlg.check_episodes_btn.click()
    assert pump(lambda: not win.alerts.running)
    from ui.settings_dialog import SettingRow
    texts = [r.detail.text() for r in dlg.pages.currentWidget().widget().findChildren(SettingRow)]
    assert any("Last checked" in t and "No new episodes" in t for t in texts)
    dlg.close()


# -- What's New -----------------------------------------------------------------------------

def test_changelog_covers_current_version():
    from core import __version__, changelog
    assert changelog.RELEASES[0].version == __version__
    assert [r.version for r in changelog.since("1.1.0")] == [__version__]
    assert changelog.since(__version__) == []
    assert len(changelog.since(None)) == len(changelog.RELEASES)


def _status(ready=True):
    from core import setup
    return setup.SetupStatus("/x/ani-cli", "5.1.6", True, True, ("iina", "/x/iina") if ready else None, ready)


def test_whats_new_after_update_once(win, monkeypatch):
    from core import __version__
    checks = []
    monkeypatch.setattr(win, "_check_updates", lambda status: checks.append(status))
    win.ctx.set_pref("setup_done", True)            # a 1.1 user: Setup done, no version recorded
    win._on_status(_status())
    dlg = win._whats_new
    assert dlg.isVisible() and dlg.subtitle.text() == "Updated from 1.1.0."
    assert dlg.release_boxes[0].property("highlight") is True and dlg.release_boxes[1].property("highlight") is False
    assert checks == []                              # update pop-ups wait until it's closed
    dlg.accept()
    assert pump(lambda: checks)
    assert win.ctx.pref("last_version") == __version__

    win._whats_new = None
    win._on_status(_status())                        # next launch: not again
    assert win._whats_new is None and len(checks) == 2


def test_no_whats_new_on_fresh_install(win, monkeypatch):
    from core import __version__
    opened = []
    monkeypatch.setattr(win, "open_setup", lambda: opened.append(True))
    win._on_status(_status(ready=False))
    assert pump(lambda: opened)
    assert getattr(win, "_whats_new", None) is None
    assert win.ctx.pref("last_version") == __version__


def test_whats_new_from_menu(win):
    action = next(a for a in win.menuBar().actions()[0].menu().actions() if a.text() == "What's New")
    action.trigger()
    assert win._whats_new.isVisible() and len(win._whats_new.release_boxes) >= 3
    win._whats_new.accept()


# -- Terminal history is a choice ------------------------------------------------------------

@pytest.fixture
def terminal_history(tmp_path, monkeypatch):
    from core import paths, setup
    hist = tmp_path / "ani-hsts"
    hist.write_text("9\tdemon-slayer-1\tDemon Slayer\n29\tfrieren-2\tFrieren\n", encoding="utf-8")
    monkeypatch.setattr(paths, "ani_cli_history_file", lambda: hist)
    monkeypatch.setattr(setup, "current_status", lambda: setup.SetupStatus("/x", "5.1.6", True, True, ("iina", "/x"), True))
    monkeypatch.setattr(setup, "check_network", lambda *a, **k: setup.NetworkStatus("ok", "fine"))
    return hist


def test_brand_new_user_is_asked_before_importing(tmp_path, terminal_history):
    from ui.main_window import MainWindow
    from ui.setup_dialog import SetupDialog

    ctx = ui_fakes.fake_context(tmp_path / "new", with_history=False)
    win = MainWindow(ctx)
    win.start()
    assert pump(lambda: getattr(win, "_setup_dialog", None) is not None, 3)
    assert ctx.store.continue_watching() == []                     # nothing imported behind their back
    dlg: SetupDialog = win._setup_dialog
    assert dlg.terminal.isVisible() and dlg.terminal.button.text() == "Import"
    assert "2 shows" in dlg.terminal.detail.text()
    assert pump(lambda: dlg.terminal.button.isEnabled())
    dlg.terminal.button.click()
    assert pump(lambda: len(ctx.store.continue_watching()) == 2)
    assert ctx.pref("import_history") is True and not dlg.terminal.button.isVisible()
    win.close()
    ctx.shutdown()


def test_existing_users_keep_importing(tmp_path, terminal_history):
    from ui.main_window import MainWindow

    ctx = ui_fakes.fake_context(tmp_path / "old", with_history=False)
    ctx.set_pref("setup_done", True)                   # a 1.1 user; import_history was never stored
    ctx.set_pref("last_version", "1.2.0")
    win = MainWindow(ctx)
    win.start()
    assert pump(lambda: len(ctx.store.continue_watching()) == 2)
    assert ctx.pref("import_history") is True
    win.close()
    ctx.shutdown()


def test_turning_on_in_settings_imports(tmp_path, terminal_history):
    from ui.main_window import MainWindow

    ctx = ui_fakes.fake_context(tmp_path / "s", with_history=False)
    win = MainWindow(ctx)
    dlg = win.open_settings("History")
    dlg.controls["import_history"].setChecked(True)
    assert pump(lambda: win.home.continue_row.model().rowCount() == 2)
    win.close()
    ctx.shutdown()


def test_whats_new_after_setup_when_update_needed_setup(win, monkeypatch):
    checks = []
    monkeypatch.setattr(win, "_check_updates", lambda status: checks.append(status))
    win.ctx.set_pref("setup_done", True)
    win.ctx.set_pref("last_version", "1.1.0")
    monkeypatch.setattr(win, "open_setup", lambda: None)
    win._on_status(_status(ready=False))                  # e.g. ani-cli went missing: Setup first
    assert getattr(win, "_whats_new", None) is None
    win._after_setup(_status())                           # Setup finished
    assert win._whats_new.isVisible() and checks == []
    win._whats_new.accept()
    assert pump(lambda: checks)
