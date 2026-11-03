"""v1.8.5: adult shows get linked and flagged, nav works for accessibility presses, Go menu,
search grid fills the width, Skip fillers lives under Skipping."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtGui import QKeySequence, QShortcut  # noqa: E402

import ui_fakes  # noqa: E402
from core import anilist, http  # noqa: E402
from core.anilist import AniListClient  # noqa: E402
from core.catalog import Catalog  # noqa: E402
from core.store import Store  # noqa: E402


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
    from ui.main_window import MainWindow

    ctx = ui_fakes.fake_context(tmp_path)
    w = MainWindow(ctx)
    w.resize(1280, 820)
    w.show()
    yield w
    w.close()
    ctx.shutdown()


# -- adult shows are linked, so they're flagged ----------------------------------------------

def adult_media() -> dict:
    m = ui_fakes.media_json(2)
    m.update(id=4242, isAdult=True, title={"english": None, "romaji": "Nukitashi the Animation", "native": None},
             tags=[])
    return m


def adult_anilist(seen: list[str]) -> AniListClient:
    def transport(payload: bytes) -> http.Response:
        body = json.loads(payload)
        seen.append(body["query"])
        hits = [adult_media()] if "isAdult: false" not in body["query"] else []   # what AniList does
        return http.Response(200, {}, json.dumps({"data": {"Page": {"media": hits}}}).encode())
    return AniListClient(transport=transport)


class NoHianime:
    def search(self, _query):
        return []


def test_title_matching_includes_adult_entries():
    assert "isAdult" not in anilist.Q_SEARCH.split("query")[-1]
    for q in (anilist.Q_TRENDING, anilist.Q_SEASON, anilist.browse_query({})):
        assert "isAdult: false" in q          # lists AniGUI shows on its own still leave them out


def test_adult_show_links_and_is_18_plus(tmp_path):
    store = Store(tmp_path / "t.db")
    seen: list[str] = []
    cat = Catalog(store, hianime=NoHianime(), anilist=adult_anilist(seen))
    media = cat.enrich("nukitashi-the-animation-19790", "Nukitashi the Animation")
    assert media is not None and media.anilist_id == 4242
    assert store.get_show("nukitashi-the-animation-19790").anilist_id == 4242   # poster and details now
    mature, _notes, _allowed = store.maturity(4242)
    assert mature
    show = store.get_show("nukitashi-the-animation-19790")
    assert cat.is_mature(show)


def test_shows_that_missed_before_are_tried_again(tmp_path):
    store = Store(tmp_path / "t.db")
    store.cache_put("nomatch:anilist:nukitashi-the-animation-19790", "1", 3600)   # a 1.8.4 miss
    cat = Catalog(store, hianime=NoHianime(), anilist=adult_anilist([]))
    assert cat.enrich("nukitashi-the-animation-19790", "Nukitashi the Animation") is not None


def test_search_results_get_rated_against_adult_entries_too(tmp_path):
    from core.hianime import SearchResult

    class Hianime:
        def search(self, _query):
            return [SearchResult(1, "nukitashi-the-animation-19790", "Nukitashi the Animation", None)]

    store = Store(tmp_path / "t.db")
    cat = Catalog(store, hianime=Hianime(), anilist=adult_anilist([]))
    [result] = cat.search_rated("nukitashi")
    assert cat.is_mature(result)


# -- navigation --------------------------------------------------------------------------------

def test_accessibility_press_on_the_sidebar_changes_page(win):
    # VoiceOver (and macOS automation) checks the button rather than clicking it
    win.nav_buttons[win.library].toggle()
    assert win.stack.currentWidget() is win.library
    win.nav_buttons[win.stats].setChecked(True)
    assert win.stack.currentWidget() is win.stats


def test_clicking_the_highlighted_item_from_a_show_page_still_goes_there(win):
    win.open_item(anilist.Media.from_json(ui_fakes.media_json(1)))
    assert pump(lambda: win.stack.currentWidget() is win.detail)
    assert win.nav_buttons[win.home].isChecked()
    win.nav_buttons[win.home].click()
    assert win.stack.currentWidget() is win.home


def test_go_menu_has_every_page_and_back(win):
    titles = [m.title() for m in win.menuBar().findChildren(type(win.menuBar().addMenu("x")))]
    assert "Go" in titles
    keys = {name: a.shortcut().toString() for name, a in win.go_actions.items()}
    assert keys["Home"] == "Ctrl+1" and keys["Calendar"] == "Ctrl+5"
    assert keys["Back"]
    win.go_actions["My List"].trigger()
    assert win.stack.currentWidget() is win.library
    win.go_actions["Back"].trigger()
    assert win.stack.currentWidget() is win.home


def test_no_shortcut_is_bound_twice(win):
    # a key bound both to a menu item and a QShortcut is "ambiguous" and does nothing
    menu_keys = [a.shortcut().toString() for a in win.go_actions.values()]
    shortcut_keys = [s.key().toString() for s in win.findChildren(QShortcut)]
    assert not set(menu_keys) & set(shortcut_keys)
    assert QKeySequence("Ctrl+F").toString() in shortcut_keys


# -- search grid -------------------------------------------------------------------------------

@pytest.mark.parametrize("width", [700, 1028, 1180, 1500])
def test_grid_reaches_the_right_edge(win, width):
    from ui.cards import Card, CardGrid

    grid = CardGrid(win.ctx.images)
    grid.resize(width, 600)
    grid.show()
    grid.cards.set_cards([Card(key=str(i), title=f"Show {i}") for i in range(20)])
    pump(timeout=0.2)
    rects = [grid.visualRect(grid.cards.index(i)) for i in range(20)]
    first_row = [r for r in rects if r.y() == rects[0].y()]
    left = first_row[0].left()
    right = grid.viewport().width() - first_row[-1].right()
    assert abs(left - right) <= 24 and left <= 30                # balanced (Qt keeps a scroll bar's width spare)
    assert len({r.y() for r in rects[:len(first_row)]}) == 1


def test_cards_show_the_full_title_on_hover(win):
    from ui.cards import Card, CardModel

    model = CardModel()
    model.set_cards([Card(key="1", title="One Piece: The Movie - Dead End Adventure")])
    assert model.index(0).data(Qt.ItemDataRole.ToolTipRole) == "One Piece: The Movie - Dead End Adventure"


# -- settings ----------------------------------------------------------------------------------

def test_skip_fillers_lives_under_skipping(win):
    from ui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(win.ctx, section="Skipping")
    rows = [r.title.text() for r in dlg._skipping() if hasattr(r, "title")]
    assert "Skip fillers" in rows
    assert "Skip fillers" not in [r.title.text() for r in dlg._playback() if hasattr(r, "title")]
    dlg.close()


def test_one_result_is_singular(win):
    win.go_actions["Search"].trigger()
    win.search._show("lantern", [ui_fakes.FakeHianime().search("Lantern")[0]])
    assert win.search.status.text().startswith("1 result for")
