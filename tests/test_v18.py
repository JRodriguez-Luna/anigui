"""v1.8: dub subtitles, Coming soon, sticky Back bar, mature content."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402
from ui.content_notes import Meter  # noqa: E402

import ui_fakes  # noqa: E402
from core.ani_cli import StreamInfo  # noqa: E402
from core.player import build_player_command  # noqa: E402

LANTERN = ui_fakes.slug("The Lantern Keeper", 1)
STARFALL = ui_fakes.slug("Starfall Academy", 0)


def pump(cond=lambda: False, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


@pytest.fixture
def win(tmp_path, monkeypatch):
    from ui import playback
    from ui.main_window import MainWindow

    monkeypatch.setattr(playback, "IPC_TIMEOUT_MS", 1500)
    monkeypatch.setattr(playback, "COUNTDOWN_S", 0)
    ctx = ui_fakes.fake_context(tmp_path)
    w = MainWindow(ctx)
    w.resize(1280, 820)
    w.show()
    yield w
    if ctx.player.mpv:
        ctx.player.mpv.server.close()
    w.close()
    ctx.shutdown()


# -- dub subtitles ---------------------------------------------------------------------------

INFO = StreamInfo("https://cdn.example/a.m3u8", "https://embed.example/", "T", subtitle_url="https://subs.example/a.vtt")


def test_player_commands_leave_subtitles_off_when_asked():
    from dataclasses import replace

    off = replace(INFO, show_subtitles=False)
    iina = build_player_command("iina", "/x/iina-cli", off, "T")
    mpv = build_player_command("mpv", "/x/mpv", off, "T", "/tmp/s")
    assert "--mpv-sid=no" in iina and any(a.startswith("--mpv-sub-files=") for a in iina)   # loaded, but off
    assert "--sid=no" in mpv and mpv.index("--sid=no") < mpv.index("--")
    assert "--mpv-sid=no" not in build_player_command("iina", "/x/iina-cli", INFO, "T")
    no_subs = replace(INFO, subtitle_url=None, show_subtitles=False)
    assert "--mpv-sid=no" not in build_player_command("iina", "/x/iina-cli", no_subs, "T")


def play_and_get_info(w, episode="2"):
    w.ctx.store.upsert_show(LANTERN, "The Lantern Keeper")
    w.open_item(w.ctx.store.get_show(LANTERN))
    assert pump(lambda: w.detail.grid.model_.items)
    before = len(w.ctx.player.launched)
    w.detail.play(episode)
    assert pump(lambda: len(w.ctx.player.launched) > before)
    return w.ctx.player.launched[-1][0]


def test_dub_plays_with_subtitles_off(win):
    win.ctx.set_pref("dub", True)
    info = play_and_get_info(win)
    assert info.subtitle_url and info.show_subtitles is False


def test_sub_keeps_subtitles_on(win):
    win.ctx.set_pref("dub", False)
    assert play_and_get_info(win).show_subtitles is True


def test_setting_turns_dub_subtitles_back_on(win):
    win.ctx.set_pref("dub", True)
    win.ctx.set_pref("dub_subtitles", True)
    assert play_and_get_info(win).show_subtitles is True


def test_no_dub_fallback_shows_subtitles(win):
    win.ctx.set_pref("dub", True)
    win.ctx.bridge.no_dub_episodes.add("3")
    info = play_and_get_info(win, "3")
    assert info.show_subtitles is True                   # it's playing subbed after all


def test_auto_next_adds_dub_subtitles_switched_off(win):
    win.ctx.set_pref("dub", True)
    play_and_get_info(win, "5")
    mpv = win.ctx.player.mpv
    assert pump(lambda: win.playback.session and win.playback.session.episodes)
    mpv.set_prop("duration", 1440.0)
    mpv.set_prop("time-pos", 1380.0)
    assert pump(lambda: win.playback.session.next_info is not None)
    mpv.send_event("end-file", reason="eof")
    assert pump(lambda: mpv.named("sub-add"))
    assert mpv.named("sub-add")[-1][2] == "auto"         # added to the menu, not shown


# -- the 18+ rule (real AniList numbers, Nov 2026) --------------------------------------------

from core.maturity import Tag, assess  # noqa: E402


def T(name, rank, adult=False, spoiler=False):
    return Tag(name, rank, adult, spoiler)


@pytest.mark.parametrize("name, genres, tags, mature", [
    ("I'm Dating a Dark Summoner", ["Comedy", "Ecchi"], [T("Nudity", 93), T("Hypersexuality", 60, True)], True),
    ("Food Wars!", ["Comedy", "Ecchi"], [T("Nudity", 80), T("Tentacles", 34, True)], True),
    ("Goblin Slayer", ["Action"], [T("Gore", 83), T("Nudity", 75), T("Rape", 72, True)], True),
    ("Berserk", ["Action"], [T("Gore", 86), T("Rape", 68, True), T("Nudity", 57)], True),
    ("KonoSuba", ["Comedy", "Ecchi"], [T("Masochism", 73, True), T("Nudity", 45)], False),
    ("Rent-a-Girlfriend", ["Romance"], [T("Prostitution", 97, True), T("Nudity", 20)], False),
    ("Chainsaw Man", ["Action"], [T("Gore", 88), T("Body Horror", 85), T("Nudity", 48)], False),
    ("Attack on Titan", ["Action"], [T("Gore", 77), T("Cannibalism", 69), T("Suicide", 55)], False),
    ("My Dress-Up Darling", ["Romance", "Ecchi"], [T("Otaku Culture", 91)], False),
    ("Frieren", ["Adventure"], [T("Travel", 96)], False),
])
def test_rule_on_real_shows(name, genres, tags, mature):
    assert assess(False, genres, tags).mature is mature, name


def test_adult_shows_are_always_18_plus():
    assert assess(True, ["Comedy"], []).mature


def test_content_notes():
    notes = assess(False, ["Ecchi"], [T("Nudity", 88), T("Gore", 77), T("Rape", 45, True),
                                      T("Torture", 70), T("Suicide", 30)]).notes
    assert notes == ("Nudity", "Sexual themes", "Sexual violence", "Gore", "Disturbing themes")
    aot = assess(False, ["Action"], [T("Gore", 77), T("Cannibalism", 69)]).notes
    assert aot == ("Gore", "Disturbing themes")
    assert assess(False, ["Action"], [T("Nudity", 48), T("Gore", 40)]).notes == ()   # minor parts aren't listed
    spoiler = assess(False, ["Drama"], [T("Rape", 90, True, spoiler=True)])
    assert spoiler.mature and spoiler.notes == ()           # counts, but never shown (spoiler)


# -- 18+ in the app --------------------------------------------------------------------------

POCKET = ui_fakes.slug("Pocket Dungeon Diaries", ui_fakes.MATURE)
POCKET_ID = 500 + ui_fakes.MATURE


def titles(row):
    return [c.title for c in row.model().cards()]


def test_hidden_from_home_and_back_when_turned_off(win):
    home = win.home
    home.load_remote()
    assert pump(lambda: not home.trending_row.model().is_loading() and not home.season_row.model().is_loading())
    assert "Pocket Dungeon Diaries" not in titles(home.trending_row) + titles(home.season_row)
    assert all(m.display_title != "Pocket Dungeon Diaries" for m in home.hero.items)
    win.ctx.set_pref("hide_mature", False)
    assert "Pocket Dungeon Diaries" in titles(home.trending_row)
    card = next(c for c in home.trending_row.model().cards() if c.title == "Pocket Dungeon Diaries")
    assert card.mature and not card.blur                    # badge, no blur


def test_your_own_18_plus_show_stays_blurred(win):
    win.ctx.store.upsert_show(POCKET, "Pocket Dungeon Diaries")
    win.ctx.store.set_anilist_match(POCKET, POCKET_ID, 1.0)
    win.ctx.store.set_in_library(POCKET, True)
    win.ctx.catalog.remember_maturity(win.ctx.catalog.anilist.media(POCKET_ID))
    win.home.refresh_local()
    card = next(c for c in win.home.library_row.model().cards() if c.title == "Pocket Dungeon Diaries")
    assert card.mature and card.blur
    win.ctx.set_pref("hide_mature", False)
    card = next(c for c in win.home.library_row.model().cards() if c.title == "Pocket Dungeon Diaries")
    assert card.mature and not card.blur


def test_opening_asks_first_and_can_stop_asking(win):
    media = win.ctx.catalog.anilist.media(POCKET_ID)
    asked = []
    win.mature_ask = lambda title, notes: asked.append((title, notes)) or (False, False)
    win.open_item(media)
    assert asked == [("Pocket Dungeon Diaries", ("Nudity", "Sexual themes", "Gore"))]   # spoiler tag left out
    assert win.stack.currentWidget() is not win.detail                                  # Go back

    win.mature_ask = lambda title, notes: (True, False)
    win.open_item(media)
    assert win.stack.currentWidget() is win.detail                                      # Show anyway

    win.go(win.home)
    win.mature_ask = lambda title, notes: asked.append(title) or (True, True)           # …and don't ask again
    win.open_item(media)
    n = len(asked)
    win.go(win.home)
    win.open_item(media)
    assert len(asked) == n                                                              # not asked this time
    assert win.ctx.store.maturity(POCKET_ID)[2] is True


def test_no_question_when_hiding_is_off_or_show_is_fine(win):
    win.mature_ask = lambda *_a: pytest.fail("shouldn't ask")
    win.open_item(win.ctx.catalog.anilist.media(500))
    win.ctx.set_pref("hide_mature", False)
    win.open_item(win.ctx.catalog.anilist.media(POCKET_ID))
    assert win.stack.currentWidget() is win.detail


def test_show_page_badge_and_content_line(win):
    win.ctx.set_pref("hide_mature", False)
    win.open_item(win.ctx.catalog.anilist.media(POCKET_ID))
    d = win.detail
    assert pump(lambda: d.media is not None)
    assert not d.mature_badge.isHidden() and not d.content_row.isHidden()
    line = d.content_row
    assert [tag.text() for tag in line.tags] == ["Nudity", "Sexual themes", "Gore"]
    nudity = line.tags[0]
    nudity.show_card()                                          # what hovering shows
    card = nudity.hover
    assert card.isVisible()
    assert card.findChild(QLabel, "NoteCardTitle").text() == "Nudity · 88 / 100"
    meter = card.findChild(Meter)
    assert meter is not None and meter.rank == 88
    assert meter.line == 70 and meter.color == "#C0392B"
    assert card.findChild(QLabel, "NoteCardText").text() == \
        "What the show is known for. Past the 18+ line (70), so it's marked 18+."
    nudity.hide_card()
    assert not card.isVisible()
    assert line.explainer.isHidden()
    line.info.click()                                           # ⓘ opens the panel under the line
    assert not line.explainer.isHidden()
    boxes = [w.text() for w in line.explainer.findChildren(QLabel, "ScaleBox")]
    assert len(boxes) == 4 and "0–40" in boxes[0] and "80–100" in boxes[3]
    line.info.click()
    assert line.explainer.isHidden()
    win.open_item(win.ctx.catalog.anilist.media(501))
    assert pump(lambda: d.media is not None and d.media.anilist_id == 501)
    assert d.mature_badge.isHidden() and d.content_row.isHidden()


def test_search_hides_and_says_so(win):
    win.go(win.search)
    win.search.box.setText("Pocket Dungeon")
    win.search._search()
    s = win.search
    assert pump(lambda: s.hidden_note.isVisible())
    assert "1 result hidden" in s.hidden_note.text()
    assert s.stack.currentWidget() is s.empty and "is 18+" in s.empty.text()
    s.hidden_note.linkActivated.emit("#show")                # Show them = turn the setting off
    assert win.ctx.pref("hide_mature") is False
    assert pump(lambda: [c.title for c in s.grid.cards.cards()] == ["Pocket Dungeon Diaries"])
    assert s.grid.cards.cards()[0].mature and not s.hidden_note.isVisible()


def test_settings_has_the_switch(win):
    from ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(win.ctx, section="Content")
    box = dlg.controls["hide_mature"]
    assert box.isChecked()
    box.setChecked(False)
    assert win.ctx.pref("hide_mature") is False


# -- Coming soon -----------------------------------------------------------------------------

def test_coming_soon_card():
    from ui.episodes import coming_soon
    now = 1_800_000_000
    item = coming_soon(6, now + 3 * 86400 + 4 * 3600 + 120, now=now)
    assert item.number == "6" and item.upcoming.endswith("· in 3d 4h")
    assert coming_soon(6, now + 2 * 3600 + 15 * 60, now=now).upcoming.endswith("in 2h 15m")
    assert coming_soon(6, now - 10, now=now) is None


def test_coming_soon_follows_the_last_episode_and_isnt_playable(win, monkeypatch):
    import dataclasses

    d = win.detail
    open_lantern = lambda: (win.ctx.store.upsert_show(LANTERN, "The Lantern Keeper"),  # noqa: E731
                            win.open_item(win.ctx.store.get_show(LANTERN)))
    open_lantern()
    assert pump(lambda: d.grid.model_.items and d.media)
    assert not any(i.upcoming for i in d.grid.model_.items)          # no airing info: no card
    d.media = dataclasses.replace(d.media, next_episode=13, next_airing_at=int(time.time()) + 93600)
    d._refresh_episode_states()
    last = d.grid.model_.items[-1]
    assert last.upcoming and last.number == "13" and "in 1d 1h" in last.upcoming
    clicked = []
    d.grid.episodeClicked.connect(clicked.append)
    d.grid.clicked.emit(d.grid.model_.index(len(d.grid.model_.items) - 1))
    assert clicked == []
    d.media = dataclasses.replace(d.media, next_episode=20)          # not right after the last one: no card
    d._refresh_episode_states()
    assert not any(i.upcoming for i in d.grid.model_.items)


# -- sticky Back bar -------------------------------------------------------------------------

def test_sticky_bar_appears_after_scrolling_and_goes_back(win):
    win.ctx.catalog.hianime.counts[STARFALL] = 150
    win.ctx.store.upsert_show(STARFALL, "Starfall Academy")
    win.open_item(win.ctx.store.get_show(STARFALL))
    d = win.detail
    assert pump(lambda: d.grid.model_.items and d.media)
    assert d.sticky.isHidden()
    assert pump(lambda: d.verticalScrollBar().maximum() > 1000)   # the grid has been laid out
    d.verticalScrollBar().setValue(d.verticalScrollBar().maximum())
    assert pump(lambda: d.sticky.isVisible())
    assert d.sticky.title.text() == "Starfall Academy"
    assert "Up next: 4" in d.sticky.where.text() and "Episodes 1–100" in d.sticky.where.text()
    assert d.sticky.play.text().startswith("▶  Resume 4")
    went_back = []
    d.backRequested.connect(lambda: went_back.append(True))
    d.sticky.back.click()
    assert went_back
    d.verticalScrollBar().setValue(0)
    assert pump(lambda: d.sticky.isHidden())


# -- 1.8.1: option B, and saved shows checked without opening them ----------------------------

def test_nudity_below_the_line_is_listed_but_not_18_plus():
    from ui.content_notes import note_card
    m = assess(False, ["Adventure", "Comedy", "Ecchi"], [T("Nudity", 65)])   # e.g. Tales of Wedding Rings
    assert not m.mature and m.notes == ("Nudity", "Sexual themes")
    card = note_card(m, "Nudity")
    assert card.title == "Nudity · 65 / 100" and card.line == 70 and card.color == "#E9B44C"
    assert card.text == "A regular part of the show, but below the 18+ line (70). Listed so you know, not hidden."
    m = assess(False, ["Comedy"], [T("Nudity", 70)])
    assert m.mature and note_card(m, "Nudity").color == "#C0392B"
    m = assess(False, ["Romance", "Ecchi"], [T("Nudity", 50)])
    assert not m.mature and m.notes == ("Sexual themes",)    # under 60: not listed


def test_meter_draws_the_18_plus_line():
    from PySide6.QtGui import QImage
    from ui.content_notes import Meter
    meter = Meter(65, "#E9B44C", 70)
    meter.resize(240, meter.height())
    img = QImage(meter.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QRegion
    from PySide6.QtWidgets import QWidget
    meter.render(img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)   # just the meter, no background
    line_x = int(240 * 70 / 100)
    assert QImage.pixelColor(img, line_x, 1).lightness() > 200    # the white 18+ mark sticks out above the bar
    assert QImage.pixelColor(img, 10, 1).alpha() == 0              # nothing else up there


def test_hover_cards_explain_each_note():
    from ui.content_notes import note_card
    m = assess(False, ["Action"], [T("Gore", 77), T("Body Horror", 85), T("Cannibalism", 69), T("Suicide", 55)])
    gore = note_card(m, "Gore")
    assert gore.title == "Gore · 85 / 100" and gore.rank == 85
    assert "Body Horror (85), Gore (77)" in gore.text and "never makes a show 18+" in gore.text
    assert "Cannibalism (69), Suicide (55)" in note_card(m, "Disturbing themes").text
    ecchi = note_card(assess(False, ["Ecchi"], []), "Sexual themes")
    assert ecchi.rank is None and "lists this show as Ecchi" in ecchi.text   # no meter without a rating
    themed = note_card(assess(False, ["Ecchi"], [T("Hypersexuality", 65, True)]), "Sexual themes")
    assert themed.rank == 65 and themed.color == "#E9B44C"


def saved_pocket(w, in_list=True):
    w.ctx.store.upsert_show(POCKET, "Pocket Dungeon Diaries")
    w.ctx.store.set_anilist_match(POCKET, POCKET_ID, 1.0)
    if in_list:
        w.ctx.store.set_in_library(POCKET, True)


def test_saved_shows_get_checked_without_being_opened(win):
    saved_pocket(win)                                     # in My List from before 1.8: never checked
    assert win.ctx.store.maturity(POCKET_ID) is None
    win.home.refresh_local()
    assert pump(lambda: any(c.title == "Pocket Dungeon Diaries" and c.mature and c.blur
                            for c in win.home.library_row.model().cards()))
    assert win.ctx.store.maturity(POCKET_ID)[0] is True


def test_my_list_page_checks_too(win):
    saved_pocket(win)
    win.go(win.library)
    win.library.refresh()
    assert pump(lambda: any(c.title == "Pocket Dungeon Diaries" and c.blur for c in win.library.grid.cards.cards()))


def test_show_page_asks_when_18_plus_turns_up_late(win):
    saved_pocket(win, in_list=False)
    win.ctx.catalog._maturity_tried.add(POCKET)           # as if the background check hasn't happened yet
    asked = []
    win.mature_ask = lambda title, notes: asked.append(title) or (False, False)
    came_back = []
    win.detail.backRequested.connect(lambda: came_back.append(True))
    win.open_item(win.ctx.store.get_show(POCKET))         # unknown, so opening didn't ask…
    assert pump(lambda: asked)                            # …but the page does once AniList answers
    assert asked == ["Pocket Dungeon Diaries"] and pump(lambda: came_back)


def test_known_18_plus_is_asked_once_not_twice(win):
    win.ctx.catalog.remember_maturity(win.ctx.catalog.anilist.media(POCKET_ID))
    saved_pocket(win, in_list=False)
    asked = []
    win.mature_ask = lambda title, notes: asked.append(title) or (True, False)
    win.open_item(win.ctx.store.get_show(POCKET))
    assert pump(lambda: win.detail.media is not None)
    pump(timeout=0.3)
    assert asked == ["Pocket Dungeon Diaries"]
