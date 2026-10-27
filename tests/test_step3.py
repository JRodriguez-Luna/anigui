"""Step 3 UI tests: offscreen, fake services, real widgets and click paths."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QCoreApplication, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import ui_fakes  # noqa: E402
from core.ani_cli import StreamInfo  # noqa: E402
from core.catalog import Catalog  # noqa: E402
from core.hianime import Episode  # noqa: E402
from core.player import build_player_command  # noqa: E402
from core.store import Store  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.theme import apply_theme  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_theme(a)
    return a


def pump(cond=lambda: False, timeout: float = 5.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return
        time.sleep(0.01)


@pytest.fixture
def win(app, tmp_path):
    ctx = ui_fakes.fake_context(tmp_path)
    w = MainWindow(ctx)
    w.resize(1280, 820)
    w.show()
    w.home.load_remote()
    w.home.refresh_local()
    yield w
    w.close()
    ctx.shutdown()


def test_stylesheet_parses(app):
    assert "anigui-chevron" in app.styleSheet()


def test_home_loads_rows_and_hero(win):
    pump(lambda: not win.home.trending_row.model().is_loading() and win.home.season_row.model().cards())
    trending = win.home.trending_row.model().cards()
    assert len(trending) == len(ui_fakes.SHOWS)
    assert trending[0].badge == "★ 88" and trending[0].subtitle == "TV · 24 eps · 2026"
    assert win.home.hero.title.text() == "Starfall Academy"
    cont = win.home.continue_row.model().cards()
    assert [c.title for c in cont][0] == "Tidecaller"  # most recent first
    assert cont[-1].subtitle == "Episode 4 · 43%"
    assert [c.title for c in win.home.library_row.model().cards()] == ["Paper Crane Requiem", "Tea House on Cloud Street"]


def test_missing_continue_covers_are_looked_up(win):
    pump(lambda: all(c.cover for c in win.home.continue_row.model().cards()))
    assert all(c.cover and c.cover.startswith("fake://cover/") for c in win.home.continue_row.model().cards())


def test_search_debounce_and_results(win):
    win.go(win.search)
    win.search.box.setText("neon")
    pump(lambda: win.search.grid.cards.cards() and not win.search.grid.cards.is_loading(), timeout=3)
    assert [c.title for c in win.search.grid.cards.cards()] == ["Neon Courier"]
    win.search.box.setText("zzzz nothing")
    pump(lambda: win.search.stack.currentWidget() is win.search.empty, timeout=3)
    assert "No results" in win.search.empty.text()


def test_open_media_and_play(win):
    pump(lambda: not win.home.trending_row.model().is_loading())
    media = win.home.trending_row.model().cards()[1].payload  # The Lantern Keeper, never watched
    win.open_item(media)
    assert win.stack.currentWidget() is win.detail
    pump(lambda: win.detail.grid.model_.items)
    assert len(win.detail.grid.model_.items) == 12
    assert win.detail.play_btn.text() == "▶  Play Episode 1"

    win.detail.play("3")
    pump(lambda: win.ctx.player.launched)
    info, title, _start = win.ctx.player.launched[-1]
    assert title == "The Lantern Keeper — Episode 3"
    assert win.ctx.bridge.requests[-1].episode == "3"
    pump(lambda: win.detail.play_btn.text() != "▶  Play Episode 1")
    assert win.detail.play_btn.text() == "▶  Resume Episode 3"
    states = {i.number: i.state for i in win.detail.grid.model_.items}
    assert states["3"] == "progress" and states["1"] == "new"
    assert win.toast.isVisible() and "mpv" in win.toast.text()


def test_play_failure_shows_error(win):
    win.ctx.bridge.fail_episodes = {"2"}
    show = win.ctx.store.continue_watching()[0].show
    win.open_item(show)
    pump(lambda: win.detail.grid.model_.items)
    win.detail.play("2")
    pump(lambda: win.toast.isVisible() and "Couldn't play" in win.toast.text())
    assert "No sources found" in win.toast.text()
    assert all(i.busy is None for i in win.detail.grid.model_.items)


def test_resume_targets(tmp_path):
    store = Store(tmp_path / "r.db")
    cat = Catalog(store, hianime=ui_fakes.FakeHianime(), anilist=None)  # anilist unused here
    eps = [Episode(str(n), str(n), None) for n in range(1, 4)]
    store.upsert_show("a-1", "A")
    assert cat.resume_episode("a-1", eps) == (eps[0], "play")
    store.record_progress("a-1", "2", 100, 1000)
    assert cat.resume_episode("a-1", eps) == (eps[1], "resume")
    store.mark_watched("a-1", "2")
    assert cat.resume_episode("a-1", eps) == (eps[2], "next")
    store.mark_watched("a-1", "3")
    assert cat.resume_episode("a-1", eps) == (eps[0], "rewatch")


def test_library_toggle_and_back(win):
    pump(lambda: not win.home.trending_row.model().is_loading())
    win.open_item(win.home.trending_row.model().cards()[2].payload)  # Ashen Blade
    pump(lambda: win.detail.list_btn.isEnabled())
    win.detail.list_btn.click()
    assert win.detail.list_btn.text() == "✓  In My List"
    win.back()
    assert win.stack.currentWidget() is win.home
    assert "Ashen Blade" in [c.title for c in win.home.library_row.model().cards()]
    win.go(win.library)
    assert "Ashen Blade" in [c.title for c in win.library.grid.cards.cards()]


def test_history_import_keeps_file_order(tmp_path):
    hist = tmp_path / "ani-hsts"
    hist.write_text("1\tfirst-show-1\tFirst\n5\tsecond-show-2\tSecond\n9\tthird-show-3\tThird\n")
    store = Store(tmp_path / "h.db")
    store.import_ani_cli_history(hist)
    assert [i.show.title for i in store.continue_watching()] == ["Third", "Second", "First"]


def test_player_commands():
    info = StreamInfo("https://cdn/v.m3u8", "https://embed/", "T", "https://cdn/a.m3u8", "https://cdn/s.vtt")
    iina = build_player_command("iina", "/usr/local/bin/iina", info, "Show — Episode 1")
    assert "--mpv-referrer=https://embed/" in iina
    assert "--mpv-sub-files=https\\://cdn/s.vtt" in iina
    assert iina[-1] == "https://cdn/v.m3u8"
    mpv = build_player_command("mpv", "/opt/homebrew/bin/mpv", info, "Show — Episode 1", "/tmp/x.sock", 615.4)
    assert mpv[0] == "/opt/homebrew/bin/mpv" and mpv[-1] == "https://cdn/v.m3u8"
    for flag in ("--referrer=https://embed/", "--input-ipc-server=/tmp/x.sock", "--start=615",
                 "--idle=yes", "--force-media-title=Show — Episode 1"):
        assert flag in mpv
    iina2 = build_player_command("iina", "/x/iina", info, "T", "/tmp/x.sock", 90)
    assert "--mpv-input-ipc-server=/tmp/x.sock" in iina2 and "--mpv-start=90" in iina2


def test_settings_persist(app, tmp_path):
    ctx = ui_fakes.fake_context(tmp_path, with_history=False)
    w = MainWindow(ctx)
    w.detail.dub_btn.click()
    w.detail.quality.setCurrentIndex(2)
    ctx.settings.sync()
    s = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert s.value("dub") in (True, "true") and s.value("quality") == "720"
    w.close()
    ctx.shutdown()


# -- Stale id repair ----------------------------------------------------------------------

class _StaleHianime(ui_fakes.FakeHianime):
    """Old id lists nothing; searching the title finds the show under a new id."""

    def episodes(self, anime_id):
        if anime_id == "demon-arc-old-77":
            return []
        return super().episodes(anime_id)

    def search(self, query):
        if "district" in query.lower():
            from core.hianime import SearchResult
            return [SearchResult(1, "demon-arc-mini-9", "District Arc Recap", None),
                    SearchResult(2, "starfall-academy-1000", "Entertainment District Arc", "fake://cover/0")]
        return super().search(query)


def test_rename_show_moves_progress_and_library(tmp_path):
    store = Store(tmp_path / "m.db")
    store.upsert_show("old-1", "Show")
    store.record_progress("old-1", "1", 1400, 1440)
    store.record_progress("old-1", "2", 300, 1440)
    store.set_in_library("old-1", True)
    store.upsert_show("new-2", "Show")
    store.record_progress("new-2", "2", 900, 1440)  # newer data under the new id wins
    store.rename_show("old-1", "new-2", "Show", "https://p/new.jpg")
    assert store.get_show("old-1") is None
    progress = store.show_progress("new-2")
    assert progress["1"].completed and progress["2"].position == 900
    new = store.get_show("new-2")
    assert new.in_library and new.poster == "https://p/new.jpg"


def test_episodes_for_relinks_stale_id(tmp_path):
    store = Store(tmp_path / "s.db")
    store.upsert_show("demon-arc-old-77", "Entertainment District Arc")
    store.mark_watched("demon-arc-old-77", "9")
    cat = Catalog(store, hianime=_StaleHianime(), anilist=None)
    new_id, title, eps = cat.episodes_for("demon-arc-old-77", "Entertainment District Arc")
    assert new_id == "starfall-academy-1000" and title == "Entertainment District Arc"
    assert len(eps) == 24
    assert store.get_progress(new_id, "9").completed
    assert store.get_show("demon-arc-old-77") is None
    assert cat.resume_episode(new_id, eps)[0].number == "10"


def test_episodes_for_gives_up_without_confident_match(tmp_path):
    store = Store(tmp_path / "g.db")
    store.upsert_show("demon-arc-old-77", "Totally Different Title")
    cat = Catalog(store, hianime=_StaleHianime(), anilist=None)
    assert cat.episodes_for("demon-arc-old-77", "Totally Different Title") == ("demon-arc-old-77", "Totally Different Title", [])
    assert store.get_show("demon-arc-old-77") is not None


def test_detail_page_follows_relinked_id(app, tmp_path):
    ctx = ui_fakes.fake_context(tmp_path, with_history=False)
    ctx.catalog.hianime = _StaleHianime()
    ctx.store.upsert_show("demon-arc-old-77", "Entertainment District Arc")
    ctx.store.mark_watched("demon-arc-old-77", "9")
    w = MainWindow(ctx)
    w.open_item(ctx.store.get_show("demon-arc-old-77"))
    pump(lambda: w.detail.grid.model_.items)
    assert w.detail.anime_id == "starfall-academy-1000"
    assert w.detail.play_btn.text() == "▶  Play Episode 10"
    assert [c.payload.anime_id for c in w.home.continue_row.model().cards()] == ["starfall-academy-1000"]
    w.close()
    ctx.shutdown()
