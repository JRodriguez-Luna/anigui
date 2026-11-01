"""v1.7: filler episodes (Anime Filler List), Hide fillers, Skip fillers."""

from __future__ import annotations

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


# -- the data (shaped like the real animefillerlist.com pages) -------------------------------

SHOWS_PAGE = """<div class="Group"><h2>N</h2><ul>
<li><a href="/shows/naruto">Naruto</a></li><li><a href="/shows/boruto-naruto-movie">Naruto Films</a></li>
<li><a href="/shows/naruto-shippuden">Naruto Shippuden</a></li></ul></div>
<li><a href="/shows/bleach-thousand-year-blood-war">Bleach: Thousand-Year Blood War (Bleach: Sennen Kessen-hen)</a></li>
<li><a href="/shows/one-piece">One Piece</a></li><li><a href="/shows/attack-titan">Attack on Titan</a></li>"""


def row(n, cls, label):
    return (f'<tr class="{cls} {"odd" if n % 2 else "even"}" id="eps-{n}"><td class="Number">{n}</td>'
            f'<td class="Title"><a href="/shows/naruto/x-{n}" rel="nofollow">Episode {n}</a></td>'
            f'<td class="Type"><span>{label}</span></td><td class="Date">2003-04-02</td> </tr>')


def naruto_page():
    rows = []
    for n in range(1, 221):
        if n in (26, 97) or n >= 136:
            rows.append(row(n, "filler", "Filler"))
        elif n in (7, 27):
            rows.append(row(n, "mixed_canon/filler", "Mixed Canon/Filler"))
        elif n == 101:
            rows.append(row(n, "anime_canon", "Anime Canon"))
        else:
            rows.append(row(n, "manga_canon", "Manga Canon"))
    return "<html><table class=\"EpisodeList\"><tbody>" + "".join(rows) + "</tbody></table></html>"


def site(pages=None, status=200):
    pages = {"https://www.animefillerlist.com/shows": SHOWS_PAGE,
             "https://www.animefillerlist.com/shows/naruto": naruto_page(), **(pages or {})}
    seen = []

    def fetch(url):
        seen.append(url)
        if status != 200 or url not in pages:
            return http.Response(404 if status == 200 else status, {}, b"not found")
        return http.Response(200, {}, pages[url].encode())
    return fetch, seen


def test_reads_the_show_and_caches_only_what_it_parses(tmp_path):
    store = Store(tmp_path / "t.db")
    fetch, seen = site()
    guide = FillerGuide(store, fetch=fetch)
    info = guide.for_titles(["Naruto", "NARUTO"])
    assert info.complete
    assert info.kind("26") == FILLER and info.kind("97") == FILLER and info.kind("136.0") == FILLER
    assert info.kind("27") is None and info.kind("101") is None and info.kind("25") is None   # mixed / anime canon
    assert seen == ["https://www.animefillerlist.com/shows", "https://www.animefillerlist.com/shows/naruto"]
    cached = store.cache_get_json("afl:https://www.animefillerlist.com/shows/naruto")
    assert "<td" not in cached and cached.count("<tr") == 220                 # rows' opening tags only
    assert guide.for_titles(["Naruto"]) == info and len(seen) == 2           # second time: all cached


def test_titles_must_match_exactly():
    fetch, _ = site()
    guide = FillerGuide(fetch=fetch)
    assert guide.find_show(["Naruto: Shippuden"]) == "naruto-shippuden"      # punctuation doesn't matter
    assert guide.find_show(["Naruto"]) == "naruto"                            # never Shippuden or the films
    assert guide.find_show(["Bleach: Sennen Kessen-hen"]) == "bleach-thousand-year-blood-war"   # the alt title
    assert guide.find_show(["Attack on Titan Season 2"]) is None             # a later season: no borrowing
    assert guide.find_show(["Frieren", None, ""]) is None
    assert guide.find_show(["Some Show", "One Piece"]) == "one-piece"        # any of the titles


def test_summary():
    numbers = [str(n) for n in range(1, 221)]
    info = FillerGuide(fetch=site()[0]).for_titles(["Naruto"])
    assert info.summary(numbers) == "87 of 220 episodes are filler"
    assert FillerInfo({"3": FILLER}, complete=True).summary(["1", "2", "3"]) == "1 of 3 episodes is filler"
    assert FillerInfo({"3": FILLER, "2": RECAP}, complete=True).summary(["1", "2", "3"]) == \
        "1 of 3 episodes is filler · 1 recap"
    assert FillerInfo({"3": FILLER}, complete=False).summary(["1", "2", "3"]) is None   # partial: no count
    assert FillerInfo({}, complete=True).summary(numbers) is None
    assert info.skippable(["25", "26", "27", "30"]) == {"26"}


def test_failures_mean_no_fillers():
    assert FillerGuide(fetch=site(status=503)[0]).for_titles(["Naruto"]) == FillerInfo()
    assert FillerGuide(fetch=site({"https://www.animefillerlist.com/shows/naruto": "<html>"})[0]
                       ).for_titles(["Naruto"]) == FillerInfo()

    def offline(_url):
        raise OSError("offline")

    assert FillerGuide(fetch=offline).for_titles(["Naruto"]) == FillerInfo()
    assert FillerGuide(fetch=lambda _u: http.Response(200, {}, b"\xff\xfe junk")).for_titles(["Naruto"]) == FillerInfo()


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
    monkeypatch.setattr(win.ctx.fillers, "for_titles", lambda _titles: FillerInfo({}, complete=True))
    open_show(win, STARFALL, "Starfall Academy")
    d = win.detail
    assert not d.pager.isVisible() and not d.filler_note.isVisible()
    assert all(i.kind is None for i in d.grid.model_.items)
