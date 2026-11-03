"""v1.10.0: the holiday update. The Holidays page (advent calendar, 12 Days of Anime, badges),
the decorations, and the surprises."""

from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import ui_fakes  # noqa: E402
from core import holiday  # noqa: E402
from core.store import Progress  # noqa: E402
from test_step4 import LANTERN, STARFALL, fast, pump, win  # noqa: E402,F401

DEC7 = dt.date(2026, 12, 7)


@pytest.fixture
def plain_theme(monkeypatch):
    from ui import theme
    applied = []
    monkeypatch.setattr(theme, "apply_theme", lambda app: applied.append(theme.HOLIDAY))
    yield applied
    theme.set_holiday(False)


@pytest.fixture
def motion_on(monkeypatch):
    from ui import motion
    monkeypatch.setenv("ANIGUI_REDUCE_MOTION", "0")
    motion.set_reduce_motion(None)
    yield
    motion.set_reduce_motion(None)


@pytest.fixture
def motion_off(monkeypatch):
    from ui import motion
    monkeypatch.setenv("ANIGUI_REDUCE_MOTION", "1")
    motion.set_reduce_motion(None)
    yield
    motion.set_reduce_motion(None)


@pytest.fixture
def fake_advent(monkeypatch):
    """Advent episodes from the fake AniList shows (Starfall is 500, The Lantern Keeper 501)."""
    eps = tuple(holiday.XmasEpisode(500 + (i % 2), str(i % 9 + 1), f"Show {i}", f"Title {i}") for i in range(24))
    monkeypatch.setattr(holiday, "CHRISTMAS_EPISODES", eps)
    monkeypatch.setattr(holiday, "CHRISTMAS_IDS", (500, 501))
    return eps


def festive(win, today=DEC7):
    win.ctx.set_pref("holiday_theme", "early")
    win.ctx.set_pref("sleigh_day", today.isoformat())       # (tests play it themselves)
    win.apply_holiday(today=today, animate=False)


# -- core ----------------------------------------------------------------------------------------

def test_twenty_four_different_christmas_episodes():
    eps = holiday.CHRISTMAS_EPISODES
    assert len(eps) == 24 and len({(e.anilist_id, e.episode) for e in eps}) == 24
    assert [holiday.advent_pick(d) for d in range(1, 25)] == list(eps)
    assert holiday.advent_pick(0) is None and holiday.advent_pick(25) is None
    assert eps[-1].show == "Tokyo Godfathers"                     # Christmas Eve: the movie
    assert all(e.title and e.show and e.episode.isdigit() for e in eps)
    # every show on the Christmas shelf has its Christmas episode in the calendar
    assert set(holiday.CHRISTMAS_IDS) <= {e.anilist_id for e in eps}
    assert holiday.christmas_episodes_for(4224) == {"17", "19"} and holiday.christmas_episodes_for(None) == set()


def test_doors_open_one_a_day():
    assert holiday.advent_open_until(dt.date(2026, 11, 30)) == 0
    assert holiday.advent_open_until(dt.date(2026, 12, 1)) == 1
    assert holiday.advent_open_until(DEC7) == 7
    assert holiday.advent_open_until(dt.date(2026, 12, 31)) == 24
    assert holiday.advent_open_until(dt.date(2027, 1, 1)) == 24
    assert holiday.advent_open_until(dt.date(2027, 1, 2)) == 0


def test_calendar_days_and_big_days():
    assert holiday.holiday_days(dt.date(2026, 12, 24)) == "Christmas Eve"
    assert holiday.holiday_days(dt.date(2026, 12, 25)) == "Christmas"
    assert holiday.holiday_days(dt.date(2026, 12, 31)) == "New Year's Eve"
    assert holiday.holiday_days(dt.date(2027, 1, 1)) == "New Year's Day"
    assert holiday.holiday_days(DEC7) is None
    assert holiday.is_christmas(dt.date(2026, 12, 25)) and not holiday.is_christmas(DEC7)
    assert holiday.is_new_year(dt.date(2027, 1, 1)) and holiday.season_year(dt.date(2027, 1, 1)) == 2026


def _p(anime_id, episode, when: dt.datetime, completed=True):
    return Progress(anime_id=anime_id, episode=episode, position=0, duration=1440, completed=completed,
                    updated_at=when.timestamp(), source="anigui")


def test_twelve_days_counts_and_badges():
    at = lambda m, d, h=20: dt.datetime(2026, m, d, h)  # noqa: E731
    progress = [_p("a", str(n), at(12, 14 + n % 10)) for n in range(14)]       # 14 in the window
    progress += [_p("b", "1", at(12, 2, 2)), _p("c", "1", at(10, 3)), _p("d", "1", at(12, 20), completed=False)]
    days = {"2026-12-02", "2026-12-03", "2026-12-04", "2025-12-01"}
    count, badges = holiday.challenge(progress, days, {("b", "1")}, {"a": at(12, 14).timestamp(), "c": at(10, 1).timestamp()},
                                      dt.date(2026, 12, 26))
    earned = {b.key for b in badges if b.earned}
    assert count == 12                                                     # capped at the goal
    assert earned == {"gift", "owl", "streak", "xmas", "new", "twelve"}
    count, badges = holiday.challenge([_p("c", "1", at(10, 3))], set(), set(), {"c": at(10, 1).timestamp()},
                                      dt.date(2026, 12, 26))
    assert count == 0 and not any(b.earned for b in badges)              # October doesn't count
    assert [b.emoji for b in badges] == ["🎁", "🦉", "🔥", "🎄", "⛷️", "⭐"]


def test_countdown_text():
    from ui.festive import countdown_text
    assert countdown_text(DEC7) == "🎄 18 days to Christmas"
    assert countdown_text(dt.date(2026, 12, 24)) == "🎄 Christmas is tomorrow!"
    assert countdown_text(dt.date(2026, 12, 25)) == "🎄 Merry Christmas!"
    assert countdown_text(dt.date(2026, 12, 28)) == "❄ Happy holidays"
    assert countdown_text(dt.date(2027, 1, 1)) == "✨ Happy New Year 2027!"


def test_greeting_lines():
    from ui.festive import greeting_lines
    title, body = greeting_lines("Chuy", 61.5 * 3600, 2026)
    assert title == "Merry Christmas, Chuy! 🎄" and "61h" in body and "2026" in body
    title, body = greeting_lines("", 0, 2026)
    assert title == "Merry Christmas! 🎄" and "watched" not in body


# -- the sidebar ---------------------------------------------------------------------------------

def test_holidays_page_only_while_festive(win, plain_theme, fake_advent):
    btn = win.nav_buttons[win.holidays]
    assert btn.isHidden() and win.countdown.isHidden() and win.lights.isHidden()
    festive(win)
    assert not btn.isHidden() and not win.countdown.isHidden() and not win.lights.isHidden()
    assert win.go_actions["Holidays"].isVisible() and win.go_actions["Holidays"].shortcut().toString() == "Ctrl+6"
    assert win.countdown.text() == "🎄 18 days to Christmas"
    win.go_actions["Holidays"].trigger()
    assert win.stack.currentWidget() is win.holidays and btn.isChecked()
    win.apply_holiday(today=dt.date(2027, 1, 2), animate=False)             # season's over
    assert btn.isHidden() and win.countdown.isHidden() and win.stack.currentWidget() is win.home
    assert "Happy holidays" not in win.footer.text()


def test_countdown_chip_lets_it_snow(win, plain_theme, motion_on):
    festive(win)
    win.countdown.clicked.emit()
    assert win.flurry.isVisible() and win.flurry.flakes
    assert pump(lambda: not win.flurry.isVisible(), 8)                      # and it stops by itself
    win.countdown.clicked.emit()                                            # however slow the frames are
    assert win.flurry.step(win.flurry.started + 0.05) and not win.flurry.step(win.flurry.started + 4.6)


def test_reduce_motion_keeps_everything_still(win, plain_theme, motion_off):
    festive(win)
    win.countdown.clicked.emit()
    assert not win.flurry.isVisible()
    assert not win.home.sleigh.play() and not win.fireworks.play(2027)
    assert not win.lights._timer.isActive() and not win.lights.isHidden()  # lit, not twinkling


# -- the Holidays page -------------------------------------------------------------------------

def test_advent_doors(win, plain_theme, fake_advent):
    festive(win)
    page = win.holidays
    page.today = DEC7
    win.go(page)
    states = [d.property("state") for d in page.doors]
    assert states[:6] == ["closed"] * 6 and states[6] == "today" and set(states[7:]) == {"locked"}
    page.open_door(9)                                                       # no peeking
    assert "opens on December 9" in page.pick.text() and not page.watch.isVisibleTo(page)
    page.open_door(3)                                                       # a missed one
    assert "Door 3:" in page.pick.text() and fake_advent[2].title in page.pick.text()
    assert page.watch.isVisibleTo(page) and page.doors[2].property("state") == "open"
    assert win.ctx.pref("advent_2026") == "3"
    page.open_door(7)
    assert win.ctx.pref("advent_2026") == "3,7" and page.doors[2].text() == "★"


def test_watch_from_a_door_plays_that_episode(win, plain_theme, fake_advent):
    festive(win)
    page = win.holidays
    page.today = DEC7
    win.go(page)
    assert pump(lambda: page.media)
    page.open_door(2)                                                       # Lantern Keeper, ep 2
    page.watch.click()
    assert pump(lambda: win.ctx.player.launched, 8)
    assert win.stack.currentWidget() is win.detail and win.detail.anime_id == LANTERN
    assert pump(lambda: win.playback.now_playing == (LANTERN, "2"))


def test_twelve_days_and_your_christmas_episodes(win, plain_theme, fake_advent):
    festive(win)
    page = win.holidays
    page.today = dt.date(2026, 12, 20)
    win.ctx.store.set_anilist_match(STARFALL, 500, 1.0)
    win.go(page)
    assert "0 of 12" in page.bar_text.text()
    assert [b.key for b in page.badges] == ["gift", "owl", "streak", "xmas", "new", "twelve"]
    # Starfall (500) is in Continue Watching in the fake history: its Christmas episodes show up
    assert pump(lambda: page.yours.isVisible() and page.yours.view.cards.cards())
    cards = page.yours.view.cards.cards()
    assert all(c.payload[0].anilist_id == 500 for c in cards)
    assert {c.payload[1] for c in cards} == {e.episode for e in fake_advent if e.anilist_id == 500}


# -- decorations -----------------------------------------------------------------------------------

def test_christmas_episodes_are_tagged(win, plain_theme, fake_advent):
    festive(win)
    win.open_item(win.ctx.store.get_show(STARFALL))
    assert pump(lambda: win.detail.grid.model_.items and win.detail.media)
    pump(lambda: False, 0.3)
    tagged = {i.number for i in win.detail.grid.model_.items if i.christmas}
    assert tagged and tagged <= holiday.christmas_episodes_for(500)


def test_adding_to_my_list_is_a_gift(win, plain_theme, motion_on):
    festive(win)
    toasts = []
    win.detail.toast.connect(lambda text, err: toasts.append(text))
    win.open_item(win.ctx.store.get_show(STARFALL))
    assert pump(lambda: win.detail.anime_id)
    if win.ctx.store.get_show(win.detail.anime_id).in_library:
        win.detail._toggle_library()                                         # take it off first
    toasts.clear()
    win.detail._toggle_library()
    assert toasts == ["🎁 Added to My List"] and win.detail.bow.isVisible()
    assert win.toast.property("kind") == "holiday"
    win.detail._toggle_library()                                             # removing: no gift
    assert toasts == ["🎁 Added to My List"]


def test_toasts_are_plain_out_of_season(win, plain_theme):
    win.toast.show_message("Hello")
    assert win.toast.property("kind") == "info"
    festive(win)
    win.toast.show_message("Oops", error=True)
    assert win.toast.property("kind") == "error"


def test_stats_wear_a_sweater(win, plain_theme):
    assert win.stats.sweater.isHidden()
    festive(win)
    assert not win.stats.sweater.isHidden() and win.stats.title.property("sweater")
    assert win.stats.sweater.clear_left > win.stats.title.sizeHint().width()
    win.apply_holiday(today=dt.date(2027, 1, 2), animate=False)
    assert win.stats.sweater.isHidden()


def test_calendar_marks_the_holidays(win, plain_theme, monkeypatch):
    from ui import calendar_page
    festive(win)
    xmas_week = (dt.date(2026, 12, 21) - calendar_page.cal.week_start(offset=0)).days // 7
    win.go(win.calendar)
    win.calendar.offset = xmas_week
    win.calendar.refresh()
    assert pump(lambda: win.calendar.week and win.calendar.week.monday == dt.date(2026, 12, 21))
    texts = [h.text() for h in win.calendar.headers]
    assert "Christmas Eve" in texts[3] and "🎁 Christmas" in texts[4] and win.calendar.headers[3].property("holiday")
    assert "Christmas" not in texts[2]


# -- surprises -------------------------------------------------------------------------------------

def test_surprise_me_plays_something_of_yours(win, plain_theme):
    assert win.home.surprise_btn.isHidden()
    festive(win)
    assert not win.home.surprise_btn.isHidden()
    mine = {s.anime_id for s in win.home.surprise_choices()}
    assert STARFALL in mine
    picked = win.home.surprise_me()
    assert picked.anime_id in mine
    assert pump(lambda: win.ctx.player.launched, 8)                          # opens it and plays
    assert win.detail.anime_id == picked.anime_id


def test_surprise_me_with_nothing_to_pick(win, plain_theme, monkeypatch):
    festive(win)
    monkeypatch.setattr(win.home, "surprise_choices", lambda: [])
    assert win.home.surprise_me() is None
    assert "🎁" in win.toast.text()


def test_sleigh_once_a_day(win, plain_theme, motion_on, monkeypatch):
    played = []
    monkeypatch.setattr(win.home.sleigh, "play", lambda: played.append(1) or True)
    monkeypatch.setattr("ui.main_window.QTimer.singleShot", lambda ms, fn: fn())
    win.ctx.set_pref("holiday_theme", "early")      # (this restyles for the real date)
    played.clear()
    win.apply_holiday(today=DEC7, animate=False)
    win.apply_holiday(today=DEC7, animate=False)
    assert played == [1] and win.ctx.pref("sleigh_day") == "2026-12-07"
    win.apply_holiday(today=DEC7 + dt.timedelta(days=1), animate=False)
    assert played == [1, 1]


def test_christmas_card_once_on_christmas(win, plain_theme, monkeypatch):
    monkeypatch.setattr("ui.main_window.QTimer.singleShot", lambda ms, fn: fn())
    monkeypatch.setattr("ui.main_window.first_name", lambda: "Chuy")
    xmas = dt.date(2026, 12, 25)
    festive(win, xmas)
    assert win.christmas_card.isVisible() and win.christmas_card.title.text() == "Merry Christmas, Chuy! 🎄"
    win.christmas_card.ok.click()
    assert not win.christmas_card.isVisible()
    win.apply_holiday(today=xmas, animate=False)
    assert not win.christmas_card.isVisible()                                # once
    festive(win, DEC7)
    assert not win.christmas_card.isVisible()


def test_fireworks_on_new_years_day(win, plain_theme, motion_on, monkeypatch):
    monkeypatch.setattr("ui.main_window.QTimer.singleShot", lambda ms, fn: fn())
    ny = dt.date(2027, 1, 1)
    festive(win, ny)
    assert win.fireworks.isVisible() and win.fireworks.year == 2027 and win.ctx.pref("fireworks_year") == "2027"
    win.fireworks.finish()
    win.apply_holiday(today=ny, animate=False)
    assert not win.fireworks.isVisible()                                     # once a year


def test_new_years_eve_waits_for_midnight(win, plain_theme):
    win.now = lambda: dt.datetime(2026, 12, 31, 23, 58)
    festive(win, dt.date(2026, 12, 31))
    assert win._midnight.isActive() and not win.fireworks.isVisible()
    assert 120_000 <= win._midnight.remainingTime() <= 121_500
    festive(win, DEC7)
    assert win.christmas_card.isHidden()


def test_overlays_end_by_themselves(win, motion_on):
    from ui.festive import BowPop, Fireworks, Sleigh
    from PySide6.QtCore import QPointF
    host = win.centralWidget()
    for overlay, start in ((Sleigh(host), lambda o: o.play()), (Fireworks(host), lambda o: o.play(2027)),
                           (BowPop(host), lambda o: o.pop(QPointF(50, 50)))):
        assert start(overlay)
        steps = 0
        while overlay.step() and steps < 2000:
            steps += 1
        assert steps < 2000, type(overlay).__name__


def test_searches_are_plain_ascii():
    # hianime answered HTTP 400 to "Polar Bear's Café" (a raw é in the address)
    from core.hianime import normalize_query
    assert normalize_query("Polar Bear's Café") == "Polar Bear's Cafe"
    assert normalize_query("Lucky☆Star") == "Lucky Star"
    assert normalize_query("Pokémon: Shōgun") == "Pokemon Shogun"


def test_nothing_is_earned_before_december():
    at = lambda m, d, h=20: dt.datetime(2026, m, d, h)  # noqa: E731
    november = [_p("a", "1", at(11, 20, 2)), _p("a", "2", at(11, 21)), _p("a", "3", at(11, 22))]
    days = {"2026-11-20", "2026-11-21", "2026-11-22"}
    count, badges = holiday.challenge(november, days, {("a", "1")}, {"a": at(11, 20).timestamp()},
                                      dt.date(2026, 11, 28))
    assert count == 0 and not any(b.earned for b in badges)
    assert not holiday.holidays_open(dt.date(2026, 11, 30))
    assert holiday.holidays_open(dt.date(2026, 12, 1)) and holiday.holidays_open(dt.date(2027, 1, 1))
    assert not holiday.holidays_open(dt.date(2027, 1, 2))
