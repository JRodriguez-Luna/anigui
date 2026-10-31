"""v1.4: the airing calendar."""

from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QCoreApplication, QPoint  # noqa: E402

import ui_fakes  # noqa: E402
from core import calendar as cal  # noqa: E402
from core.anilist import AniListClient  # noqa: E402


def pump(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


STAR = ui_fakes.slug("Starfall Academy", 0)       # airing, AniList 500, airs Monday 1 PM (ep 5)
LANTERN = ui_fakes.slug("The Lantern Keeper", 1)  # airing, AniList 501, airs Tuesday (ep 6), 12 eps on hianime
ASHEN = ui_fakes.slug("Ashen Blade", 2)           # airing, AniList 502, airs Wednesday (ep 7), 13 eps


@pytest.fixture
def ctx(tmp_path):
    c = ui_fakes.fake_context(tmp_path, with_history=False)
    for aid, title, al in ((STAR, "Starfall Academy", 500), (LANTERN, "The Lantern Keeper", 501),
                           (ASHEN, "Ashen Blade", 502)):
        c.store.upsert_show(aid, title)
        c.store.set_anilist_match(aid, al, 1.0)
    c.store.set_in_library(STAR, True)
    c.store.set_in_library(LANTERN, True)
    yield c
    c.shutdown()


def test_schedule_query_filters_adult_and_ids():
    client = AniListClient(transport=ui_fakes.fake_anilist_transport)
    monday = dt.datetime(2026, 10, 26).astimezone()
    start = int(monday.timestamp())
    everything = client.schedule(start, start + 7 * 86400)
    assert everything and all(not a.media.title_english == "Neon Courier" or a.episode != 1 for a in everything)
    mine = client.schedule(start, start + 7 * 86400, [500, 501])
    assert sorted(a.media.anilist_id for a in mine) == [500, 501]
    assert client.schedule(start, start + 7 * 86400, []) == []


def test_week_for_my_shows(ctx):
    monday = dt.date(2026, 10, 26)
    now = dt.datetime(2026, 10, 27, 20, 0).astimezone()          # Tuesday evening
    week = cal.build(ctx.store, ctx.catalog, monday=monday, now=now)
    titles = {e.title: (i, e) for i, day in enumerate(week.days) for e in day}
    assert set(titles) == {"Starfall Academy", "The Lantern Keeper"}   # My List only
    star_day, star = titles["Starfall Academy"]
    lantern_day, lantern = titles["The Lantern Keeper"]
    assert (star_day, lantern_day) == (0, 1)
    assert star.when.hour == 13 and star.in_library and star.anime_id == STAR
    # Monday ep 5 aired and hianime lists 24 -> watchable; Tuesday ep 6 aired, hianime lists 12 -> watchable
    assert star.state == cal.AVAILABLE and lantern.state == cal.AVAILABLE
    assert ctx.store.watched_latest(STAR) == "24"


def test_states_upcoming_and_pending(ctx, monkeypatch):
    monday = dt.date(2026, 10, 26)
    early = dt.datetime(2026, 10, 26, 9, 0).astimezone()          # Monday morning: nothing aired yet
    week = cal.build(ctx.store, ctx.catalog, monday=monday, now=early)
    assert {e.state for day in week.days for e in day} == {cal.UPCOMING}
    monkeypatch.setattr(ctx.catalog, "episodes", lambda aid: ui_fakes.FakeHianime().episodes(aid)[:4])
    late = dt.datetime(2026, 10, 26, 22, 0).astimezone()
    star = next(e for e in cal.build(ctx.store, ctx.catalog, monday=monday, now=late).days[0])
    assert star.state == cal.PENDING                                # ep 5 aired, hianime has 4


def test_all_airing_and_scope(ctx):
    monday = dt.date(2026, 10, 26)
    now = dt.datetime(2026, 10, 25).astimezone()
    everything = cal.build(ctx.store, ctx.catalog, mine=False, monday=monday, now=now)
    assert everything.count > 2
    assert "Ashen Blade" in [e.title for d in everything.days for e in d]
    ctx.store.record_progress(ASHEN, "6", 100, 1400)                # Continue Watching
    with_continue = cal.build(ctx.store, ctx.catalog, scope="library+continue", monday=monday, now=now)
    assert "Ashen Blade" in [e.title for d in with_continue.days for e in d]


def test_week_start():
    assert cal.week_start(dt.date(2026, 10, 31)) == dt.date(2026, 10, 26)
    assert cal.week_start(dt.date(2026, 10, 31), offset=1) == dt.date(2026, 11, 2)


# -- the page ---------------------------------------------------------------------------------

@pytest.fixture
def win(ctx):
    from ui.main_window import MainWindow
    w = MainWindow(ctx)
    w.resize(1320, 860)
    w.show()
    yield w
    w.close()


def cards(page):
    from ui.calendar_page import EntryCard
    return page.findChildren(EntryCard)


def test_calendar_page_shows_week_and_opens(win):
    page = win.calendar
    win.go(page)
    assert pump(lambda: page.week is not None and cards(page))
    assert {c.entry.title for c in cards(page)} == {"Starfall Academy", "The Lantern Keeper"}
    assert sum(h.text() == "Today" for h in page.headers) == 1
    assert "from your shows" in page.status.text()
    star = next(c for c in cards(page) if c.entry.title == "Starfall Academy")
    star.clicked.emit(star.entry)
    assert pump(lambda: win.stack.currentWidget() is win.detail and win.detail.anime_id == STAR)


def test_week_navigation_and_all_airing(win):
    page = win.calendar
    win.go(page)
    assert pump(lambda: page.week is not None)
    this_monday = page.week.monday
    page.next_btn.click()
    assert pump(lambda: page.week.monday == this_monday + dt.timedelta(days=7))
    assert page.today_btn.isVisible()
    page.today_btn.click()
    assert pump(lambda: page.week.monday == this_monday) and not page.today_btn.isVisible()
    page.all_btn.click()
    assert pump(lambda: len(cards(page)) > 2 and not page.mine)


def test_add_to_my_list_from_calendar(win):
    page = win.calendar
    win.go(page)
    page.all_btn.click()
    assert pump(lambda: any(c.entry.title == "Ashen Blade" for c in cards(page)))
    ashen = next(c for c in cards(page) if c.entry.title == "Ashen Blade")
    assert not ashen.entry.in_library
    page._set_library(ashen.entry, True)
    assert pump(lambda: win.ctx.store.get_show(ASHEN).in_library)
    assert pump(lambda: "Added Ashen Blade" in win.toast.text())
