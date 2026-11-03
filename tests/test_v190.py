"""v1.9.0: Seasons on one page, Up next, and auto-play rolling into the next season."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import ui_fakes  # noqa: E402
from core.anilist import Media, Related  # noqa: E402
from core.seasons import MAX_LOOKUPS, Series, build, season_labels  # noqa: E402
from test_step4 import LANTERN, STARFALL, fast, pump, start_playing, win  # noqa: E402,F401


def media(i: int, title: str, fmt: str = "TV", year: int = 2020, status: str = "FINISHED", eps: int = 12) -> Media:
    return Media(anilist_id=i, mal_id=None, title_romaji=None, title_english=title, title_native=None, synonyms=(),
                 cover=f"fake://cover/{i}", cover_color=None, banner=None, description="", episodes=eps,
                 status=status, format=fmt, genres=(), score=None, season="SPRING", year=year,
                 next_episode=None, next_airing_at=None, popularity=None)


# My Hero Academia-like: three seasons, a movie hanging off season 2, an OVA side story,
# and a crossover that must not count. Demon Slayer-like: a movie between two seasons.
S1, S2, S3 = media(1, "Hero School"), media(2, "Hero School Season 2", year=2021), media(3, "Hero School Season 3", year=2022)
MOVIE = media(10, "Hero School: Two Heroes", "MOVIE", 2021, eps=1)
OVA = media(11, "Hero School: Training of the Dead", "OVA", 2022, eps=2)
OTHER = media(12, "Some Crossover", "TV", 2019)
A1, ATRAIN, A2 = media(20, "Blade Arc"), media(21, "Blade Arc: Night Train", "MOVIE", 2021, eps=1), media(22, "Blade Arc: District", year=2022)

GRAPH: dict[int, list[Related]] = {
    1: [Related(S2, "SEQUEL"), Related(OTHER, "CHARACTER")],
    2: [Related(S1, "PREQUEL"), Related(S3, "SEQUEL"), Related(MOVIE, "SIDE_STORY"), Related(OVA, "SIDE_STORY")],
    3: [Related(S2, "PREQUEL")],
    10: [Related(S2, "PARENT")],
    20: [Related(ATRAIN, "SEQUEL")],
    21: [Related(A1, "PREQUEL"), Related(A2, "SEQUEL")],
    22: [Related(ATRAIN, "PREQUEL")],
}


def related(calls=None):
    def fn(anilist_id):
        if calls is not None:
            calls.append(anilist_id)
        return GRAPH.get(anilist_id, [])
    return fn


# -- core ----------------------------------------------------------------------------------------

def test_seasons_in_order_from_any_season():
    for start in (S1, S2, S3):
        series = build(start, related())
        assert [s.media.anilist_id for s in series.seasons] == [1, 2, 3]
        assert [s.label for s in series.seasons] == ["Season 1", "Season 2", "Season 3"]
        assert [m.anilist_id for m in series.extras] == [10, 11]          # movie and OVA, not the crossover
        assert series.complete and series.worth_showing


def test_opening_the_movie_still_shows_the_seasons():
    series = build(MOVIE, related())
    assert [s.media.anilist_id for s in series.seasons] == [1, 2, 3]


def test_a_movie_between_seasons_is_walked_through_but_not_numbered():
    series = build(A2, related())
    assert [s.media.anilist_id for s in series.seasons] == [20, 22]
    assert [s.label for s in series.seasons] == ["Season 1", "District"]
    assert [m.anilist_id for m in series.extras] == [21]
    assert series.after(20).media.anilist_id == 22 and series.after(22) is None


def test_a_show_without_seasons_shows_nothing():
    lone = media(99, "One and Done")
    series = build(lone, related())
    assert [s.media.anilist_id for s in series.seasons] == [99] and not series.worth_showing


def test_loops_and_long_series_stop():
    cyc = {i: [Related(media(i + 1 if i < 59 else 0, f"Show S{i + 1}"), "SEQUEL"),
               Related(media(i - 1 if i else 59, f"Show S{i - 1}"), "PREQUEL")] for i in range(60)}
    calls = []
    series = build(media(5, "Show S5"), lambda i: calls.append(i) or cyc[i])
    assert len(calls) <= MAX_LOOKUPS and not series.complete


def test_anilist_trouble_shows_what_it_has():
    def broken(_i):
        raise OSError("offline")
    series = build(S2, broken)
    assert [s.media.anilist_id for s in series.seasons] == [2] and not series.complete


def test_labels():
    assert season_labels(["Mob Psycho 100", "Mob Psycho 100 II", "Mob Psycho 100 III"]) == ["Season 1", "Season 2", "Season 3"]
    assert season_labels(["Naruto", "Naruto: Shippuden"]) == ["Season 1", "Shippuden"]
    assert season_labels(["Alpha", "Beta"]) == ["Alpha", "Beta"]                  # nothing shared: full names
    assert season_labels(["Solo"]) == ["Season 1"]


# -- catalog: the next season for auto-play ------------------------------------------------------

def catalog_with(tmp_path, current: Media, found=True):
    from core.catalog import Catalog
    from core.hianime import Episode, SearchResult
    from core.store import Store

    store = Store(tmp_path / "t.db")
    cat = Catalog(store, hianime=ui_fakes.FakeHianime(), anilist=None)
    cat.enrich = lambda aid, title, poster=None: current
    cat.series = lambda m: build(m, related())
    cat.find_streamable = lambda m: SearchResult(0, f"hero-school-season-{m.anilist_id}-77", m.display_title, None) if found else None
    cat.episodes_for = lambda aid, title: (aid, title, [Episode("2", "b", None), Episode("1", "a", None)])
    return cat


def test_next_season_after_a_finished_season(tmp_path):
    nxt = catalog_with(tmp_path, S2).next_season("hero-school-season-2-5", "Hero School Season 2")
    assert (nxt.anime_id, nxt.episode, nxt.label) == ("hero-school-season-3-77", "1", "Season 3")


def test_no_next_season_while_airing_or_at_the_end_or_not_on_hianime(tmp_path):
    airing = media(2, "Hero School Season 2", status="RELEASING")
    assert catalog_with(tmp_path, airing).next_season("x-1", "x") is None
    assert catalog_with(tmp_path, S3).next_season("x-1", "x") is None
    assert catalog_with(tmp_path, S2, found=False).next_season("x-1", "x") is None


def test_no_next_season_before_it_comes_out(tmp_path, monkeypatch):
    soon = media(3, "Hero School Season 3", status="NOT_YET_RELEASED")
    GRAPH_SOON = {**GRAPH, 2: [Related(S1, "PREQUEL"), Related(soon, "SEQUEL")], 3: [Related(S2, "PREQUEL")]}
    cat = catalog_with(tmp_path, S2)
    cat.series = lambda m: build(m, lambda i: GRAPH_SOON.get(i, []))
    assert cat.next_season("x-1", "x") is None


# -- the show page -------------------------------------------------------------------------------

def fake_series(win, current_id: int, nxt_status: str = "FINISHED"):
    """Starfall Academy (fake AniList 500) as season 1 of 2; Lantern Keeper (501) as season 2."""
    a = Media.from_json(ui_fakes.media_json(0))
    b = Media.from_json(ui_fakes.media_json(1))
    a = a.__class__(**{**a.__dict__, "status": "FINISHED", "year": 2024})
    b = b.__class__(**{**b.__dict__, "status": nxt_status, "year": 2025})
    g = {a.anilist_id: [Related(b, "SEQUEL")], b.anilist_id: [Related(a, "PREQUEL")]}
    win.ctx.catalog.series = lambda m: build(m, lambda i: g.get(i, []))
    enrich = win.ctx.catalog.enrich
    win.ctx.catalog.enrich = lambda aid, title, poster=None: a if aid == STARFALL else enrich(aid, title, poster)
    return a, b


def open_starfall(win):
    win.open_item(win.ctx.store.get_show(STARFALL))
    assert pump(lambda: win.detail.grid.model_.items and win.detail.seasons_row.isVisible())


def test_seasons_row_shows_progress_and_where_you_are(win):
    a, b = fake_series(win, 500)
    open_starfall(win)
    cards = win.detail.seasons_row.cards
    assert len(cards) == 2
    first = cards[0]
    assert first.state.current and first.line.startswith("You're here")
    assert cards[1].line == "Not started"
    assert "2 seasons" in win.detail.seasons_row.count.text()


def test_clicking_a_season_opens_it(win):
    a, b = fake_series(win, 500)
    open_starfall(win)
    opened = []
    win.detail.seasons_row.openMedia.disconnect()
    win.detail.seasons_row.openMedia.connect(opened.append)
    first, second = win.detail.seasons_row.cards
    first.clicked.emit(a)                                             # the one you're on: nothing
    assert opened == []
    second.clicked.emit(b)
    assert opened and opened[-1].anilist_id == b.anilist_id


def test_up_next_appears_once_the_season_is_watched(win):
    a, b = fake_series(win, 500)
    for n in range(1, 25):
        win.ctx.store.mark_watched(STARFALL, str(n))
    open_starfall(win)
    assert pump(lambda: win.detail.up_next.isVisible())
    assert win.detail.up_next.button.text().startswith("▶  Start ")
    started = []
    win.detail.openNext.connect(started.append)
    win.detail.up_next.button.click()
    assert started and started[-1].anilist_id == b.anilist_id


def test_no_up_next_while_watching_or_before_it_comes_out(win):
    fake_series(win, 500)
    open_starfall(win)
    pump(timeout=0.3)
    assert not win.detail.up_next.isVisible()                         # season not finished
    for n in range(1, 25):
        win.ctx.store.mark_watched(STARFALL, str(n))
    fake_series(win, 500, nxt_status="NOT_YET_RELEASED")
    win.detail._seasons_for = None
    win.detail._load_seasons(win.detail.media)
    pump(timeout=0.5)
    assert not win.detail.up_next.isVisible()
    assert win.detail.seasons_row.cards[1].line.startswith("Coming")


def test_related_row_leaves_out_what_seasons_shows(win):
    a, b = fake_series(win, 500)
    open_starfall(win)
    assert pump(lambda: win.detail._related is not None)
    keys = [c.key for c in win.detail.related_row.view.cards.cards()] if hasattr(win.detail.related_row, "view") else []
    assert f"anilist:{b.anilist_id}" not in keys


# -- auto-play rolls into the next season --------------------------------------------------------

def test_auto_play_moves_on_to_the_next_season(win):
    from core.catalog import NextSeason

    b = Media.from_json(ui_fakes.media_json(0))
    asked = []

    def next_season(aid, title):
        asked.append(aid)
        return NextSeason(STARFALL, "Starfall Academy", "1", "Season 2", b) if aid == LANTERN else None

    win.ctx.catalog.next_season = next_season
    mpv = start_playing(win, LANTERN, "The Lantern Keeper", "12")
    assert pump(lambda: win.playback.session.episodes)
    mpv.set_prop("duration", 1440.0)
    mpv.set_prop("time-pos", 1400.0)                                  # near the end: look it up early
    assert pump(lambda: asked == [LANTERN] and win.playback.session.next_info is not None)
    mpv.send_event("end-file", reason="eof")
    assert pump(lambda: mpv.named("loadfile"))
    assert ["set_property", "force-media-title", "Starfall Academy — Episode 1"] in mpv.commands
    s = win.playback.session
    assert (s.now.anime_id, s.now.episode) == (STARFALL, "1")
    assert win.ctx.store.get_progress(LANTERN, "12").completed


def test_auto_play_finds_the_next_season_even_without_the_early_look(win):
    from core.catalog import NextSeason

    b = Media.from_json(ui_fakes.media_json(0))
    win.ctx.catalog.next_season = lambda aid, title: NextSeason(STARFALL, "Starfall Academy", "1", "Season 2", b)
    mpv = start_playing(win, LANTERN, "The Lantern Keeper", "12")
    assert pump(lambda: win.playback.session.episodes)
    mpv.set_prop("duration", 1440.0)
    mpv.send_event("end-file", reason="eof")                          # straight to the end
    assert pump(lambda: mpv.named("loadfile"))
    assert win.playback.session.now.anime_id == STARFALL


def test_last_episode_without_a_next_season_still_says_so(win):
    win.ctx.catalog.next_season = lambda aid, title: None
    mpv = start_playing(win, LANTERN, "The Lantern Keeper", "12")
    assert pump(lambda: win.playback.session.episodes)
    mpv.set_prop("duration", 1440.0)
    mpv.send_event("end-file", reason="eof")
    assert pump(lambda: any(c[:2] == ["show-text", "That was the last episode"] for c in mpv.commands))
    assert not mpv.named("loadfile")


def test_labels_use_whichever_title_language_fits():
    from core.seasons import season_labels_for

    def m(en, ro):
        return media(1, en or ro).__class__(**{**media(1, "x").__dict__, "title_english": en, "title_romaji": ro})

    frieren = [m("Frieren: Beyond Journey's End", "Sousou no Frieren"),
               m("Frieren: Beyond Journey's End Season 2", "Sousou no Frieren 2nd Season"),
               m(None, "Sousou no Frieren 3rd Season")]                    # no English title yet
    assert season_labels_for(frieren) == ["Season 1", "Season 2", "Season 3"]
    mha = [m("My Hero Academia", "Boku no Hero Academia"), m("My Hero Academia FINAL SEASON", None)]
    assert season_labels_for(mha) == ["Season 1", "Final Season"]


# -- animations ----------------------------------------------------------------------------------

def test_reduce_motion_follows_the_setting(monkeypatch):
    from ui import motion
    monkeypatch.setenv("ANIGUI_REDUCE_MOTION", "1")
    motion.set_reduce_motion(None)
    assert motion.reduce_motion()
    monkeypatch.setenv("ANIGUI_REDUCE_MOTION", "0")
    motion.set_reduce_motion(None)
    assert not motion.reduce_motion()


def test_page_switch_fades_and_cleans_up(win):
    from PySide6.QtWidgets import QLabel
    win.go(win.library)
    overlays = [w for w in win.stack.findChildren(QLabel) if w.pixmap() is not None and not w.pixmap().isNull()]
    assert overlays                                                     # the old page, fading out
    assert pump(lambda: not [w for w in win.stack.findChildren(QLabel)
                             if w.pixmap() is not None and not w.pixmap().isNull() and w.parent() is win.stack], 2)
    assert win.stack.currentWidget() is win.library and win.library.pos().y() == 0


def test_new_pictures_fade_in(win):
    images = win.ctx.images
    images._born["fake://new"] = __import__("time").monotonic()
    assert 0.0 <= images.alpha("fake://new") < 0.5
    assert pump(lambda: images.alpha("fake://new") == 1.0, 1)
    assert images.alpha("fake://never-loaded") == 1.0


def test_toast_fades_out_and_hides(win):
    win.toast.show_message("Added to My List", ms=10)
    assert win.toast.isVisible()
    assert pump(lambda: win.toast.isHidden(), 2)


def test_hover_lift_eases_in_and_out(win):
    from ui.cards import CardGrid, Card
    from ui import motion
    motion.set_reduce_motion(False)
    grid = CardGrid(win.ctx.images)
    grid.cards.set_cards([Card("a", "A"), Card("b", "B")])
    grid._hover(0)
    assert pump(lambda: grid.lift(0) == 1.0, 1)
    grid._hover(None)
    assert pump(lambda: grid.lift(0) == 0.0, 1)
    motion.set_reduce_motion(True)
    grid._hover(1)
    pump(timeout=0.2)
    assert grid.lift(1) == 0.0                                          # Reduce motion: no lift
    motion.set_reduce_motion(None)


# -- holiday theme -------------------------------------------------------------------------------

import datetime as dt  # noqa: E402

from core import holiday  # noqa: E402


@pytest.fixture
def plain_theme(monkeypatch):
    """Restyling every widget the test run has ever made is slow, so these tests check the
    logic and leave the stylesheet alone (test_colors_switch_and_switch_back covers it)."""
    from ui import theme
    applied = []
    monkeypatch.setattr(theme, "apply_theme", lambda app: applied.append(theme.HOLIDAY))
    yield applied
    theme.set_holiday(False)


def test_thanksgiving_and_the_season():
    assert [holiday.thanksgiving(y).day for y in (2024, 2025, 2026, 2027)] == [28, 27, 26, 25]
    assert not holiday.is_on("auto", dt.date(2026, 11, 26))                 # Thanksgiving itself
    assert holiday.is_on("auto", dt.date(2026, 11, 27))                     # the day after
    assert holiday.is_on("auto", dt.date(2026, 12, 31)) and holiday.is_on("auto", dt.date(2027, 1, 1))
    assert not holiday.is_on("auto", dt.date(2027, 1, 2))
    assert holiday.is_on("early", dt.date(2026, 11, 1)) and not holiday.is_on("early", dt.date(2026, 10, 31))
    assert not holiday.is_on("off", dt.date(2026, 12, 25))


def test_the_november_offer():
    nov3 = dt.date(2026, 11, 3)
    assert holiday.offer_early("auto", "", nov3)
    assert not holiday.offer_early("auto", "2026", nov3)                    # answered this year
    assert holiday.offer_early("auto", "2025", nov3)                        # but asked again next year
    assert not holiday.offer_early("early", "", nov3)                       # already on
    assert not holiday.offer_early("auto", "", dt.date(2026, 11, 27))       # it has started anyway
    assert not holiday.offer_early("auto", "", dt.date(2026, 10, 20))


def test_colors_switch_and_switch_back(plain_theme):
    from ui import theme
    normal = theme.stylesheet()
    theme.set_holiday(True)
    sheet = theme.stylesheet()
    assert theme.ACCENT == theme.HOLIDAY_COLORS["ACCENT"] and theme.NORMAL_COLORS["ACCENT"] not in sheet
    assert "#Kicker { color: #3FAE6A" in sheet and theme.MATURE == "#C0392B"     # 18+ keeps its own red
    theme.set_holiday(False)
    assert theme.stylesheet() == normal


def test_app_turns_festive_in_december(win, plain_theme, monkeypatch):
    from ui import theme
    monkeypatch.setattr(holiday, "CHRISTMAS_IDS", (501, 500, 502))          # fake AniList's shows
    win.apply_holiday(today=dt.date(2026, 12, 5), animate=False)
    assert plain_theme == [True]                                            # restyled once
    assert theme.HOLIDAY and theme.HOLIDAY_COLORS["ACCENT"] in win.brand.text()
    assert "Happy holidays" in win.footer.text()
    assert win.home.hero_snow is not None and win.home.hero_snow.running
    assert pump(lambda: win.home.xmas_row.isVisible() and not win.home.xmas_row.view.cards.is_loading())
    keys = [c.key for c in win.home.xmas_row.view.cards.cards()]
    assert keys == ["anilist:501", "anilist:500", "anilist:502"]           # in the hand-picked order
    win.apply_holiday(today=dt.date(2027, 1, 2), animate=False)
    assert not theme.HOLIDAY and not win.home.xmas_row.isVisible() and not win.home.hero_snow.running


def test_november_banner_turn_on_now(win, plain_theme):
    from ui import theme
    win.apply_holiday(today=dt.date(2026, 11, 3), animate=False)
    banner = win.home.holiday_banner
    assert not banner.isHidden() and not theme.HOLIDAY
    banner.on_btn.click()
    assert win.ctx.pref("holiday_theme") == "early" and win.ctx.pref("holiday_banner_seen") == str(dt.date.today().year)
    assert theme.HOLIDAY                                                    # on right away
    assert pump(lambda: banner.isHidden(), 2)


def test_november_banner_wait(win, plain_theme):
    from ui import theme
    win.ctx.set_pref("holiday_banner_seen", "")
    win.apply_holiday(today=dt.date(2026, 11, 3), animate=False)
    win.home.holiday_banner.wait_btn.click()
    assert win.ctx.pref("holiday_theme") == "auto" and not theme.HOLIDAY
    assert pump(lambda: win.home.holiday_banner.isHidden(), 2)


def test_setting_has_the_three_choices(win, plain_theme):
    from ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(win.ctx, section="Appearance")
    combo = dlg.controls["holiday_theme"]
    assert [combo.itemData(i) for i in range(combo.count())] == ["auto", "early", "off"]
    combo.setCurrentIndex(2)
    assert win.ctx.pref("holiday_theme") == "off"
    dlg.close()


def test_dock_icon_gets_a_hat():
    from PySide6.QtGui import QIcon, QPixmap
    from ui.holiday import holiday_icon
    base = QPixmap(64, 64)
    base.fill()
    icon = holiday_icon(QIcon(base))
    assert icon.pixmap(64, 64).toImage() != base.toImage()
