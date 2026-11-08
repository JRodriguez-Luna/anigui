"""2.0: My Library data (lists, ratings, tags, notes, timeline)."""

import datetime as dt
import sqlite3

from core.store import SAVED, Store, stars


def store(tmp_path):
    s = Store(tmp_path / "a.db")
    for i in range(4):
        s.upsert_show(f"show-{i}", f"Show {i}", f"https://img/{i}.jpg")
    return s


def test_saved_is_your_old_my_list(tmp_path):
    s = store(tmp_path)
    s.set_in_library("show-1", True)
    lists = s.lists()
    assert lists[0].list_id == SAVED and lists[0].name == "Saved" and lists[0].count == 1
    assert [x.anime_id for x in s.list_shows(SAVED)] == ["show-1"]
    s.add_to_list(SAVED, "show-2")
    assert s.get_show("show-2").in_library


def test_your_own_lists(tmp_path):
    s = store(tmp_path)
    a = s.create_list("Comfort shows", "🍵")
    b = s.create_list("With Xochitl")
    s.add_to_list(a, "show-0")
    s.add_to_list(a, "show-1")
    s.add_to_list(a, "show-1")                       # twice is still once
    s.add_to_list(b, "show-1")
    assert [(x.name, x.emoji, x.count) for x in s.lists()[1:]] == [("Comfort shows", "🍵", 2), ("With Xochitl", None, 1)]
    assert s.lists_for("show-1") == {a, b}
    s.move_list(b, 0)
    assert [x.list_id for x in s.lists()] == [SAVED, b, a]
    s.rename_list(a, "Cozy", "☕")
    assert s.get_list(a).name == "Cozy"
    s.remove_from_list(a, "show-0")
    assert [x.anime_id for x in s.list_shows(a)] == ["show-1"]
    s.delete_list(a)
    assert s.get_list(a) is None and s.get_show("show-1") is not None   # shows stay
    s.delete_list(SAVED)                             # can't delete Saved
    assert s.lists()[0].list_id == SAVED


def test_rating_tags_and_note(tmp_path):
    s = store(tmp_path)
    s.set_rating("show-0", 9)
    s.set_tags("show-0", ["Cozy", "cozy", " rewatch  later ", "a|b"])
    s.set_note("show-0", "  Ep 7 made me cry  ")
    n = s.notes("show-0")
    assert n.rating == 9 and n.tags == ("Cozy", "rewatch later", "a b") and n.note == "Ep 7 made me cry"
    assert stars(9) == "★★★★½" and stars(10) == "★★★★★" and stars(None) == ""
    s.set_tags("show-1", ["cozy"])
    assert s.all_tags()[0] == ("Cozy", 2)
    assert {x.anime_id for x in s.tagged("COZY")} == {"show-0", "show-1"}
    assert [(sh.anime_id, r) for sh, r in s.rated()] == [("show-0", 9)]
    s.set_rating("show-0", None)
    s.set_tags("show-0", [])
    s.set_note("show-0", "")
    assert s.notes("show-0").rating is None
    assert s._conn().execute("SELECT COUNT(*) FROM show_notes WHERE anime_id='show-0'").fetchone()[0] == 0


def test_timeline(tmp_path):
    s = store(tmp_path)
    today = dt.date.today()
    s.log_watch("show-0", "3", 1300, today)
    s.log_watch("show-0", "4", 1300, today)
    s.log_watch("show-0", "5", 20, today)            # a peek isn't watching
    s.log_watch("show-1", "1", 1400, today - dt.timedelta(days=1))
    s.set_in_library("show-2", True)
    lid = s.create_list("Cozy")
    s.add_to_list(lid, "show-3")
    s.set_rating("show-3", 8)
    s.set_rating("show-3", 10)                       # changed your mind: one entry
    moments = s.timeline()
    kinds = [(m.kind, m.anime_id, m.detail) for m in moments]
    assert ("watched", "show-0", "3, 4") in kinds and ("watched", "show-1", "1") in kinds
    assert ("saved", "show-2", "") in kinds and ("listed", "show-3", "Cozy") in kinds
    assert [k for k in kinds if k[0] == "rated"] == [("rated", "show-3", "10")]
    assert moments[0].title and moments == sorted(moments, key=lambda m: m.at, reverse=True)


def test_private_mode_leaves_no_trace_in_the_timeline(tmp_path):
    s = store(tmp_path)
    s.private = True
    s.set_in_library("show-0", True)
    s.set_rating("show-0", 6)
    assert s.timeline() == [] and s.notes("show-0").rating == 6


def test_renaming_a_show_keeps_its_lists_and_notes(tmp_path):
    s = store(tmp_path)
    lid = s.create_list("Cozy")
    s.add_to_list(lid, "show-0")
    s.set_rating("show-0", 7)
    s.rename_show("show-0", "show-0-new", "Show 0")
    assert [x.anime_id for x in s.list_shows(lid)] == ["show-0-new"]
    assert s.notes("show-0-new").rating == 7


def test_upgrading_a_1_11_database_keeps_everything(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE shows (anime_id TEXT PRIMARY KEY, title TEXT NOT NULL, poster TEXT, anilist_id INTEGER,
            match_score REAL, match_manual INTEGER NOT NULL DEFAULT 0, in_library INTEGER NOT NULL DEFAULT 0,
            library_added_at REAL, updated_at REAL NOT NULL);
        INSERT INTO shows VALUES ('frieren-18542', 'Frieren', NULL, 154587, 1.0, 0, 1, 1000, 1000);
        PRAGMA user_version = 2;
    """)
    old.close()
    s = Store(path)
    assert s._conn().execute("PRAGMA user_version").fetchone()[0] == 3
    assert [x.anime_id for x in s.list_shows(SAVED)] == ["frieren-18542"]   # My List is now Saved
    assert s.lists()[0].count == 1


# -- the interface -------------------------------------------------------------------------------

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_step4 import STARFALL, pump, win  # noqa: E402,F401


def open_starfall(w):
    w.open_item(w.ctx.store.get_show(STARFALL))
    assert pump(lambda: w.detail.anime_id == STARFALL and w.detail.yours.isVisible())


def test_lists_nest_under_library_in_the_sidebar(win):
    nav = win.libnav
    assert SAVED in nav.subs and nav.subs[SAVED].text() == "Saved"
    lid = win.ctx.store.create_list("Comfort shows", "🍵")
    win.ctx.store.add_to_list(lid, STARFALL)
    win._lists_changed()
    assert nav.subs[lid].text() == "🍵  Comfort shows" and nav.subs[lid].sl.count == 1
    nav.subs[lid].click()
    assert pump(lambda: win.stack.currentWidget() is win.library and win.library.list_id == lid)
    assert nav.subs[lid].isChecked() and not nav.header.isChecked()
    assert [c.payload.anime_id for c in win.library.grid.cards.cards()] == [STARFALL]
    nav.chevron.click()                                           # fold the lists away
    assert not nav.box.isVisible() and win.ctx.pref("sidebar_lists_open") is False
    nav.header.click()
    assert pump(lambda: win.library.list_id is None)
    assert win.library.title.text() == "My Library" and nav.header.isChecked()


def test_rate_tag_and_note_on_the_show_page(win):
    open_starfall(win)
    y = win.detail.yours
    y.stars.changed.emit(7)
    y._rated(7)
    assert win.ctx.store.notes(STARFALL).rating == 7 and y.rating_text.text() == "3.5 / 5"
    y.tag_box.setText("cozy")
    y._add_tag()
    assert win.ctx.store.notes(STARFALL).tags == ("cozy",)
    y.note.setPlainText("Stopped at the festival arc")
    assert pump(lambda: win.ctx.store.notes(STARFALL).note == "Stopped at the festival arc", 3)
    win.go(win.home)
    open_starfall(win)
    assert win.detail.yours.stars.rating == 7 and win.detail.yours.note.toPlainText() == "Stopped at the festival arc"


def test_add_to_a_list_from_the_show_page(win):
    lid = win.ctx.store.create_list("With friends")
    win._lists_changed()
    open_starfall(win)
    b = win.detail.lists_btn
    assert b.text() == "☰  Lists"
    b._build()
    act = next(a for a in b.menu_.actions() if a.text() == "With friends")
    act.setChecked(True)
    assert win.ctx.store.lists_for(STARFALL) >= {lid} and b.text() == "☰  In 1 list"
    assert pump(lambda: win.libnav.subs[lid].sl.count == 1)
    win.detail.list_btn.click()
    assert win.detail.list_btn.text() == "✓  Saved" and SAVED in win.ctx.store.lists_for(STARFALL)


def test_overview_tabs(win):
    s = win.ctx.store
    s.set_rating(STARFALL, 10)
    s.set_tags(STARFALL, ["cozy"])
    s.log_watch(STARFALL, "4", 900)
    win.open_library(None)
    lib = win.library
    assert STARFALL in [c.payload.anime_id for c in lib.grid.cards.cards()]
    lib.set_tab("ratings")
    assert [c.subtitle for c in lib.grid.cards.cards()] == ["★★★★★"]
    lib.set_tab("tags")
    assert lib.tag == "cozy" and lib.tag_bar.isVisible()
    lib.set_tab("timeline")
    assert lib.stack.currentWidget() is lib.timeline and lib.timeline.model_.rowCount() >= 2


def test_deleting_a_list_keeps_the_shows(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    s = win.ctx.store
    lid = s.create_list("Temp")
    s.add_to_list(lid, STARFALL)
    win._lists_changed()
    win.open_library(lid)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: None)     # (not Cancel)
    win._delete_list(lid)
    assert s.get_list(lid) is None and lid not in win.libnav.subs
    assert win.library.list_id is None and s.get_show(STARFALL) is not None


# -- privacy -------------------------------------------------------------------------------------

class FakeTouchID:
    def __init__(self, answer=True):
        self.answer, self.asked = answer, []

    def available(self):
        return True

    def ask(self, reason, done):
        self.asked.append(reason)
        done(self.answer)


def test_private_mode_saves_nothing(win):
    s = win.ctx.store
    before = s.get_progress(STARFALL, "4")
    win.private_action.trigger()                                   # ⌘⇧N
    assert s.private and win.private_pill.isVisible() and "Private" in win.windowTitle()
    p = s.record_progress(STARFALL, "4", 1400, 1420)
    assert p.completed                                             # (the player still knows)
    s.log_watch(STARFALL, "4", 900)
    assert s.get_progress(STARFALL, "4") == before and not s.watch_log()
    win.private_pill.click()
    assert not s.private and not win.private_pill.isVisible()


def test_locked_list_asks_and_hides_its_shows(win):
    s = win.ctx.store
    fake = FakeTouchID()
    win.gate.backend = fake
    lid = s.create_list("Secret")
    s.add_to_list(lid, STARFALL)
    s.set_rating(STARFALL, 8)
    win._lists_changed()
    win._lock_list(lid, True)
    assert s.get_list(lid).locked and STARFALL in win._hidden_ids()
    win.open_library(None)
    win.library.set_tab("ratings")
    assert win.library.grid.cards.cards() == []                   # its shows stay out of the overview
    win.open_library(lid)
    assert pump(lambda: win.library.list_id == lid)
    assert fake.asked == ["open your list “Secret”"]
    win.open_library(None)
    win.open_library(lid)
    assert len(fake.asked) == 1                                    # once until AniGUI quits / Lock Now
    win.lock_now()
    fake.answer = False
    win.open_library(lid)
    pump(lambda: False, 0.3)
    assert win.library.list_id is None and len(fake.asked) == 2


def test_app_lock_covers_until_unlocked(win):
    fake = FakeTouchID(answer=False)
    win.gate.backend = fake
    win.ctx.set_pref("lock_app", True)
    win.lock_now()
    assert win.lock_screen.isVisible()
    win.lock_screen.button.click()
    assert pump(lambda: len(fake.asked) == 1) and win.lock_screen.isVisible()
    fake.answer = True
    win.lock_screen.button.click()
    assert pump(lambda: not win.lock_screen.isVisible())
    assert fake.asked == ["open AniGUI", "open AniGUI"]


def test_what_leaves_your_mac(win):
    from core import http, privacy
    privacy.LOG.clear()
    try:
        http.request("http://127.0.0.1:9/nothing", timeout=0.2)
    except OSError:
        pass
    win.go(win.privacy_page)
    page = win.privacy_page
    assert pump(lambda: page.live.count() >= 4)
    assert page.live.itemAtPosition(0, 0).widget().text() == "127.0.0.1"
    assert privacy.destination_for("graphql.anilist.co") == "AniList"
    assert privacy.destination_for("s4.anilist.co") == "AniList"   # (same family)
    assert privacy.destination_for("cdn.somevideo.net") == "Video hosts"
    names = {d.name for d in privacy.DESTINATIONS}
    assert {"AniList", "hianime", "GitHub", "AniSkip"} <= names


# -- make it yours -------------------------------------------------------------------------------

def test_accent_color(win):
    from ui import theme
    try:
        win.ctx.set_pref("accent", "ocean")
        assert theme.ACCENT.lower() == theme.accent_hex("ocean").lower()
        assert theme.accent_hex("ocean").lower() in QApplication_sheet().lower()
    finally:
        win.ctx.set_pref("accent", "ember")
    assert theme.ACCENT == "#FF6B3D"


def QApplication_sheet():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance().styleSheet()


def test_greeting():
    import datetime as dt
    from ui.yours import greeting
    assert greeting("", dt.datetime(2026, 11, 8, 20)) == ""
    assert greeting("Chuy", dt.datetime(2026, 11, 8, 20)) == "Good evening, Chuy"
    assert greeting("Chuy", dt.datetime(2026, 11, 8, 9)) == "Good morning, Chuy"
    assert greeting("Chuy", dt.datetime(2026, 12, 25, 9), holiday=True) == "Merry Christmas, Chuy 🎄"
    assert greeting(" Chuy ", dt.datetime(2026, 12, 3, 2), holiday=True) == "Up late, Chuy ❄"


def test_home_rows_your_way(win):
    from ui.yours import join_rows, parse_rows
    assert [k for k, _ in parse_rows("")][:2] == ["new", "continue"]
    order = parse_rows("trending:1,continue:0")
    assert order[0] == ("trending", True) and ("continue", False) in order and len(order) == 7
    s = win.ctx.store
    lid = s.create_list("Cozy", "🍵")
    s.add_to_list(lid, STARFALL)
    win.ctx.set_pref("home_rows", join_rows([("trending", True), ("continue", False), (f"list:{lid}", True)]))
    home = win.home
    box = home.rows_box
    assert box.indexOf(home.holders["trending"]) < box.indexOf(home.holders[f"list:{lid}"])
    assert not home.holders["continue"].isVisibleTo(home)
    assert home.list_rows[lid].title.text() == "🍵  Cozy" and home.list_rows[lid].model().rowCount() == 1
    s.set_list_locked(lid, True)                       # a locked list never shows on Home
    home.apply_rows()
    assert lid not in home.list_rows
    win.ctx.set_pref("home_rows", "")


def test_app_icon_in_your_color(win):
    from PySide6.QtGui import QIcon, QPixmap, QColor
    from ui.yours import tinted_icon
    pm = QPixmap(64, 64)
    pm.fill(QColor("#FF6B3D"))
    icon = tinted_icon(QIcon(pm), "#3D8DFF")
    c = icon.pixmap(64, 64).toImage().pixelColor(32, 32)
    assert c.blue() > c.red()                          # orange became blue-ish


# -- your data -----------------------------------------------------------------------------------

def test_backup_and_restore_round_trip(tmp_path):
    from core import backup
    s = store(tmp_path)
    lid = s.create_list("Cozy", "🍵")
    s.add_to_list(lid, "show-1")
    s.set_rating("show-1", 9)
    s.set_note("show-1", "so good")
    out = backup.back_up(s, {"accent": "ocean", "weird": object()}, tmp_path / "b" / "mine")
    assert out.name == "mine.anigui-backup" and backup.read_manifest(out)["schema"] == 3
    s.delete_list(lid)
    s.set_note("show-1", "")
    import core.paths as paths_mod
    orig = paths_mod.data_dir
    paths_mod.data_dir = lambda: tmp_path / "data"
    try:
        settings, safety = backup.restore(s, out, {"accent": "matcha"})
    finally:
        paths_mod.data_dir = orig
    assert settings == {"accent": "ocean"} and safety.exists()
    assert s.get_list(lid).name == "Cozy" and s.notes("show-1").note == "so good"


def test_not_a_backup(tmp_path):
    import pytest
    from core import backup
    bad = tmp_path / "x.anigui-backup"
    bad.write_text("nope")
    with pytest.raises(backup.BackupError):
        backup.read_manifest(bad)


def test_automatic_backups_keep_seven(tmp_path):
    import datetime as dt
    import os
    from core import backup
    s = store(tmp_path)
    folder = tmp_path / "auto"
    t0 = dt.datetime(2026, 11, 1, 9)
    made = 0
    for d in range(10):
        now = t0 + dt.timedelta(days=d)
        p = backup.auto_backup(s, {}, folder, now=now)
        if p:
            os.utime(p, (now.timestamp(), now.timestamp()))
            made += 1
        assert backup.auto_backup(s, {}, folder, now=now + dt.timedelta(hours=1)) is None   # once a day
    assert made == 10 and len(list(folder.glob("*.anigui-backup"))) == 7


MAL_XML = b"""<?xml version="1.0"?><myanimelist>
<anime><series_animedb_id>52991</series_animedb_id><series_title>Frieren</series_title>
<my_watched_episodes>4</my_watched_episodes><my_score>9</my_score><my_status>Watching</my_status></anime>
<anime><series_animedb_id>1</series_animedb_id><series_title>Cowboy Bebop</series_title>
<my_watched_episodes>26</my_watched_episodes><my_score>0</my_score><my_status>Completed</my_status></anime>
<anime><series_animedb_id>999999</series_animedb_id><series_title>Nowhere</series_title>
<my_watched_episodes>0</my_watched_episodes><my_score>0</my_score><my_status>Plan to Watch</my_status></anime>
</myanimelist>"""


def test_mal_export_is_read(tmp_path):
    import gzip
    from core import importer
    f = tmp_path / "animelist.xml.gz"
    f.write_bytes(gzip.compress(MAL_XML))
    rows = importer.parse_mal(f)
    assert rows[0] == (52991, "Frieren", "CURRENT", 9.0, 4) and rows[1][2] == "COMPLETED" and rows[2][2] == "PLANNING"
    assert importer.rating_from(9) == 9 and importer.rating_from(0) is None and importer.rating_from(7.6) == 8


def test_import_puts_shows_in_lists(tmp_path):
    from core import importer
    from core.anilist import Media
    from core.hianime import SearchResult
    s = store(tmp_path)

    def media(aid, title, eps):
        return Media(anilist_id=aid, mal_id=None, title_romaji=title, title_english=title, title_native=None,
                     synonyms=(), cover=None, cover_color=None, banner=None, description="", episodes=eps,
                     status=None, format=None, genres=(), score=None, season=None, year=None)

    class Catalog:
        def find_streamable(self, m):
            if m.anilist_id == 3:
                return None
            return SearchResult(index=0, anime_id=f"found-{m.anilist_id}", title=m.title_english, poster=None)
    entries = [importer.Entry(media(1, "Frieren", 28), "CURRENT", 9, 4),
               importer.Entry(media(2, "Bebop", 26), "COMPLETED", 0, 26),
               importer.Entry(media(3, "Nowhere", 12), "PLANNING", 0, 0)]
    seen = []
    r = importer.apply(s, Catalog(), entries, progress=lambda i, n, t: seen.append((i, n)))
    assert (r.added, r.rated, r.episodes, r.not_found) == (2, 1, 30, ["Nowhere"])
    names = {sl.name: sl for sl in s.lists()}
    assert names["Watching"].count == 1 and names["Completed"].count == 1 and "Plan to watch" not in names
    assert s.notes("found-1").rating == 9
    assert len([p for p in s.show_progress("found-1").values() if p.completed]) == 4
    again = importer.apply(s, Catalog(), entries)                  # running it twice doubles nothing
    assert again.episodes == 0 and again.rated == 0 and s.get_list(names["Watching"].list_id).count == 1
    assert seen[-1] == (3, 3)
