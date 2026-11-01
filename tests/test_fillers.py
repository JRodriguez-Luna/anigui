"""v1.7: filler and recap episodes (MyAnimeList via Jikan), Hide fillers, Skip fillers."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QCoreApplication  # noqa: E402

import ui_fakes  # noqa: E402
from core import http  # noqa: E402
from core.catalog import Catalog  # noqa: E402
from core.fillers import FILLER, RECAP, FillerGuide, FillerInfo  # noqa: E402
from core.hianime import Episode  # noqa: E402
from core.store import Store  # noqa: E402
from ui.playback import Session  # noqa: E402

STARFALL = ui_fakes.slug("Starfall Academy", 0)


def pump(cond=lambda: False, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


# -- the data -------------------------------------------------------------------------------

def jikan(pages: dict[int, list[tuple[int, bool, bool]]], statuses: dict[int, int] | None = None):
    """Fake Jikan: pages[page] = [(episode, filler, recap), ...]."""
    seen = []

    def fetch(url):
        seen.append(url)
        assert url.startswith("https://api.jikan.moe/v4/anime/20/episodes?page=")
        page = int(url.rsplit("=", 1)[1])
        status = (statuses or {}).get(page, 200)
        if status != 200:
            return http.Response(status, {}, b"{}")
        body = {"pagination": {"last_visible_page": max(pages), "has_next_page": page < max(pages)},
                "data": [{"mal_id": n, "title": f"Ep {n}", "url": "https://myanimelist.net/x", "filler": f,
                          "recap": r, "aired": "2002-10-03T00:00:00+00:00"} for n, f, r in pages[page]]}
        return http.Response(200, {}, json.dumps(body).encode())
    return fetch, seen


def naruto_pages():
    p1 = [(n, n in range(26, 30) or n == 97, n == 15) for n in range(1, 101)]
    p2 = [(n, n >= 136, False) for n in range(101, 221)]
    return {1: p1, 2: p2}


def test_reads_every_page_and_caches_only_what_it_needs(tmp_path):
    store = Store(tmp_path / "t.db")
    fetch, seen = jikan(naruto_pages())
    sleeps = []
    guide = FillerGuide(store, fetch=fetch, sleep=sleeps.append)
    info = guide.for_mal(20)
    assert info.complete
    assert info.kind("26") == FILLER and info.kind("97") == FILLER and info.kind("15") == RECAP
    assert info.kind("25") is None and info.kind("136") == FILLER and info.kind("136.0") == FILLER
    assert len(seen) == 2 and sleeps == [0.4]                      # polite gap between pages
    cached = store.cache_get_json("jikan:" + seen[0])
    assert set(cached["data"][0]) == {"mal_id", "filler", "recap"}   # titles, URLs etc. not stored
    assert guide.for_mal(20) == info and len(seen) == 2           # second time: all cached


def test_summary():
    numbers = [str(n) for n in range(1, 221)]
    info = FillerGuide(fetch=jikan(naruto_pages())[0], sleep=lambda _s: None).for_mal(20)
    assert info.summary(numbers) == "90 of 220 episodes are filler · 1 recap"
    assert FillerInfo({"3": FILLER}, complete=True).summary(["1", "2", "3"]) == "1 of 3 episodes is filler"
    assert FillerInfo({"3": FILLER}, complete=False).summary(["1", "2", "3"]) is None   # partial: no count
    assert FillerInfo({}, complete=True).summary(numbers) is None
    assert info.skippable(["14", "15", "26", "30"]) == {"15", "26"}


def test_rate_limit_retry_and_failures():
    pages = naruto_pages()
    calls = {"n": 0}
    fetch_ok, _ = jikan(pages)

    def limited(url):
        calls["n"] += 1
        if calls["n"] == 1:
            return http.Response(429, {}, b"{}")
        return fetch_ok(url)

    sleeps = []
    assert FillerGuide(fetch=limited, sleep=sleeps.append).for_mal(20).complete
    assert 1.5 in sleeps

    fetch, _ = jikan(pages, statuses={2: 500})
    info = FillerGuide(fetch=fetch, sleep=lambda _s: None).for_mal(20)
    assert not info.complete and info.kind("26") == FILLER       # page 1 still used

    fetch404, _ = jikan(pages, statuses={1: 404})
    assert FillerGuide(fetch=fetch404, sleep=lambda _s: None).for_mal(20) == FillerInfo({}, complete=True)

    def offline(_url):
        raise OSError("offline")

    assert FillerGuide(fetch=offline).for_mal(20) == FillerInfo()
    assert FillerGuide(fetch=offline).for_mal(None) == FillerInfo()
    assert FillerGuide(fetch=lambda _u: http.Response(200, {}, b"<html>")).for_mal(20) == FillerInfo()


# -- Up Next and auto-play -----------------------------------------------------------------

def test_up_next_skips_fillers_but_resumes_one_you_started(tmp_path):
    store = Store(tmp_path / "t.db")
    catalog = Catalog(store, hianime=ui_fakes.FakeHianime(), anilist=SimpleNamespace())
    eps = [Episode(str(n), str(n), None) for n in range(1, 12)]
    skip = {"1", "2", "5", "6", "7"}
    store.upsert_show("x", "X")
    assert catalog.resume_episode("x", eps, skip=skip)[0].number == "3"           # nothing watched yet
    store.mark_watched("x", "4")
    assert catalog.resume_episode("x", eps)[0].number == "5"                      # Skip off
    assert catalog.resume_episode("x", eps, skip=skip) == (eps[7], "next")        # 5-7 skipped
    store.record_progress("x", "6", 300, 1400)
    assert catalog.resume_episode("x", eps, skip=skip) == (eps[5], "resume")      # partway through: resume
    store.mark_watched("x", "11")
    store.mark_watched("x", "8")
    assert catalog.resume_episode("x", eps[:10], skip=skip | {"9", "10"})[1] == "rewatch"   # only fillers left


def test_auto_play_skips_fillers_when_on():
    prefs = {"skip_fillers": False}
    s = SimpleNamespace(episodes=[str(n) for n in range(1, 10)], now=SimpleNamespace(episode="4"),
                        filler_keys={"5", "6", "7"}, ctx=SimpleNamespace(pref=lambda k, d=None: prefs.get(k, d)))
    assert Session._next_number(s) == "5"
    prefs["skip_fillers"] = True
    assert Session._next_number(s) == "8"
    s.now.episode = "8"
    s.filler_keys = {"9"}
    assert Session._next_number(s) is None                                         # nothing but filler left


# -- the show page --------------------------------------------------------------------------

@pytest.fixture
def win(tmp_path):
    from ui.main_window import MainWindow

    ctx = ui_fakes.fake_context(tmp_path)
    w = MainWindow(ctx)
    w.resize(1280, 820)
    w.show()
    yield w
    w.close()
    ctx.shutdown()


def open_show(w, anime_id, title):
    w.ctx.store.upsert_show(anime_id, title)
    w.open_item(w.ctx.store.get_show(anime_id))
    assert pump(lambda: w.detail.grid.model_.items and w.detail.fillers is not None)


def shown(w):
    return [i.number for i in w.detail.grid.model_.items]


def test_badges_summary_and_switches(win):
    open_show(win, STARFALL, "Starfall Academy")
    d = win.detail
    kinds = {i.number: i.kind for i in d.grid.model_.items}
    assert kinds["5"] == "filler" and kinds["4"] is None
    assert d.filler_note.isVisible() and d.filler_note.text() == "3 of 24 episodes are filler"
    assert d.pager.isVisible() and d.pager.hide_fillers.isVisible() and not d.pager.jump.isVisible()
    assert d.grid.model_.data(d.grid.model_.index(4), 3).endswith("(filler)")

    d.pager.hide_fillers.click()
    assert win.ctx.pref("hide_fillers") is True
    assert "5" not in shown(win) and "8" in shown(win) and len(shown(win)) == 21
    d.pager.hide_fillers.click()
    assert len(shown(win)) == 24


def test_skip_fillers_moves_up_next_and_follows_settings(win):
    win.ctx.store.mark_watched(STARFALL, "4")
    open_show(win, STARFALL, "Starfall Academy")
    d = win.detail
    assert d.play_target == "5"
    d.pager.skip_fillers.click()
    assert win.ctx.pref("skip_fillers") is True and d.play_target == "8"
    assert "Episode 8" in d.play_btn.text()
    win.ctx.set_pref("skip_fillers", False)                 # e.g. from Settings → Playback
    assert not d.pager.skip_fillers.isChecked() and d.play_target == "5"


def test_hidden_fillers_still_show_up_next_and_jumps(win):
    win.ctx.store.mark_watched(STARFALL, "4")
    win.ctx.set_pref("hide_fillers", True)
    open_show(win, STARFALL, "Starfall Academy")
    assert shown(win)[:5] == ["1", "2", "3", "4", "5"]      # 5 is Up Next, so it stays
    assert "6" not in shown(win)


def test_shows_without_fillers_get_no_switches(win, monkeypatch):
    monkeypatch.setattr(win.ctx.fillers, "for_mal", lambda _mal: FillerInfo({}, complete=True))
    open_show(win, STARFALL, "Starfall Academy")
    d = win.detail
    assert not d.pager.isVisible() and not d.filler_note.isVisible()
    assert all(i.kind is None for i in d.grid.model_.items)
