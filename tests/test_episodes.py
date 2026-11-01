"""v1.6: episode stills, pages for long shows, Jump to episode."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem  # noqa: E402

import ui_fakes  # noqa: E402
from core import http, stills  # noqa: E402
from core.anilist import AniListClient  # noqa: E402
from core.store import Store  # noqa: E402
from ui.episodes import EP_ROLE, find_episode, page_ranges, visible_tabs  # noqa: E402

STARFALL = ui_fakes.slug("Starfall Academy", 0)


def pump(cond=lambda: False, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


# -- stills: parsing and checks ---------------------------------------------------------

def test_streaming_titles_and_numbers():
    assert stills.parse_streaming_title("Episode 12 - The Wind Rises") == ("12", "The Wind Rises")
    assert stills.parse_streaming_title("Episode 7.5: Recap") == ("7.5", "Recap")
    assert stills.parse_streaming_title("The Wind Rises") == (None, "The Wind Rises")
    assert stills.number_key("7.0") == stills.number_key(7) == "7"
    assert stills.number_key("abc") is None and stills.number_key("0") is None


def test_titles_must_agree_only_when_both_are_real():
    assert stills.titles_agree("Izuku Midoriya: Origin", "Izuku Midoriya - Origin", "1")
    assert stills.titles_agree("Episode 4", "Start Line", "4")            # placeholder on our side
    assert stills.titles_agree("Start Line", None, "4")
    assert not stills.titles_agree("Start Line", "Battle Without a Quirk", "4")


def anilist_with(streaming):
    def transport(payload):
        body = json.loads(payload)
        assert "streamingEpisodes" in body["query"]
        return http.Response(200, {}, json.dumps({"data": {"Media": {"streamingEpisodes": streaming}}}).encode())
    return AniListClient(transport=transport)


def eps(n, titled=True):
    return [(str(i), f"Title number {i}" if titled else f"Episode {i}") for i in range(1, n + 1)]


def test_anilist_stills_are_checked_against_the_show(tmp_path):
    streaming = [
        {"title": "Episode 1 - Title number 1", "thumbnail": "https://img/1.jpg"},
        {"title": "Episode 2 - Something else entirely", "thumbnail": "https://img/2.jpg"},   # wrong episode
        {"title": "Episode 159 - Battle Without a Quirk", "thumbnail": "https://img/159.jpg"},  # wrong season
        {"title": "Episode 3 - Title number 3", "thumbnail": "javascript:alert(1)"},            # not an image URL
        {"title": "Episode 4 - Title number 4", "thumbnail": "https://img/4.jpg"},
    ]
    src = stills.EpisodeStills(anilist_with(streaming), kitsu_fetch=lambda _u: pytest.fail("no Kitsu without a MAL id"))
    assert src.for_episodes(21, None, eps(13)) == {"1": "https://img/1.jpg", "4": "https://img/4.jpg"}


def kitsu(pages, mapping_id="11469"):
    seen = []

    def fetch(url):
        seen.append(url)
        if "/mappings?" in url:
            assert "filter%5BexternalSite%5D=myanimelist%2Fanime" in url and "filter%5BexternalId%5D=31964" in url
            return json.dumps({"data": [{"id": "9"}], "included": [{"type": "anime", "id": mapping_id}]}).encode()
        assert f"/anime/{mapping_id}/episodes?" in url
        offset = int(url.split("page%5Boffset%5D=")[1].split("&")[0])
        return json.dumps({"data": [
            {"attributes": {"number": n, "canonicalTitle": f"Title number {n}",
                            "thumbnail": {"original": f"https://media.kitsu.app/{n}.jpg"} if n in pages else None}}
            for n in range(offset + 1, offset + 21)
        ]}).encode()
    return fetch, seen


def test_kitsu_fills_the_gaps_and_is_cached(tmp_path):
    store = Store(tmp_path / "t.db")
    streaming = [{"title": "Episode 1 - Title number 1", "thumbnail": "https://img/1.jpg"}]
    fetch, seen = kitsu(pages=set(range(1, 30)))
    src = stills.EpisodeStills(anilist_with(streaming), cache=store, kitsu_fetch=fetch)
    found = src.for_episodes(21, 31964, eps(25))
    assert found["1"] == "https://img/1.jpg"                                  # AniList wins
    assert found["2"] == "https://media.kitsu.app/2.jpg" and found["25"].endswith("/25.jpg")
    assert len(seen) == 3                                                       # mapping + 2 pages of 20
    src.for_episodes(21, 31964, eps(25))
    assert len(seen) == 3                                                       # all cached


def test_kitsu_only_fetches_the_pages_it_needs(tmp_path):
    fetch, seen = kitsu(pages=set())
    src = stills.EpisodeStills(anilist_with([]), kitsu_fetch=fetch)
    page = [(str(n), None) for n in range(201, 301)]
    assert src.for_episodes(21, 31964, page) == {}                             # no stills there: tiles
    offsets = sorted(int(u.split("page%5Boffset%5D=")[1].split("&")[0]) for u in seen if "/episodes?" in u)
    assert offsets == [200, 220, 240, 260, 280]


def test_network_trouble_never_breaks_the_page():
    def broken_transport(_payload):
        raise OSError("offline")

    def broken_kitsu(_url):
        raise OSError("offline")

    src = stills.EpisodeStills(AniListClient(transport=broken_transport), kitsu_fetch=broken_kitsu)
    assert src.for_episodes(21, 31964, eps(5)) == {}
    junk = stills.EpisodeStills(anilist_with([]), kitsu_fetch=lambda _u: b"<html>")
    assert junk.for_episodes(21, 31964, eps(5)) == {}


# -- paging helpers -----------------------------------------------------------------------

def test_pages_tabs_and_jump():
    numbers = [str(n) for n in range(1, 1123)]
    pages = page_ranges(numbers)
    assert len(pages) == 12 and pages[0] == (0, 100, "1–100") and pages[-1] == (1100, 1122, "1101–1122")
    assert visible_tabs(12, 2) == [0, 1, 2, 3, None, 11]
    assert visible_tabs(12, 7) == [0, 1, 2, 3, None, 6, 7, 8, None, 11]
    assert visible_tabs(3, 0) == [0, 1, 2]
    assert find_episode(numbers, "845") == 844 and find_episode(numbers, "007") == 6
    assert find_episode(numbers, "2000") is None and find_episode(numbers, "x") is None


# -- the show page ------------------------------------------------------------------------

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
    assert pump(lambda: w.detail.grid.model_.items and w.detail.media)


def numbers_shown(w):
    return [i.number for i in w.detail.grid.model_.items]


def test_long_show_opens_on_the_up_next_page(win):
    win.ctx.catalog.hianime.counts[STARFALL] = 1122
    win.ctx.store.mark_watched(STARFALL, "205")
    open_show(win, STARFALL, "Starfall Academy")
    d = win.detail
    assert d.ep_count.text() == "1,122"
    assert d.pager.isVisible()
    assert numbers_shown(win)[0] == "201"
    assert len(d.grid.model_.items) == 100
    up = [i for i in d.grid.model_.items if i.up_next]
    assert [i.number for i in up] == ["206"]
    assert [b.text() for b in d.pager.buttons.values()][:3] == ["1–100", "101–200", "201–300"]
    assert d.pager.buttons[2].isChecked()


def test_page_tabs_and_jump(win):
    win.ctx.catalog.hianime.counts[STARFALL] = 1122
    open_show(win, STARFALL, "Starfall Academy")
    d = win.detail
    assert numbers_shown(win)[0] == "1"                      # nothing watched: first page
    d.pager.buttons[11].click()
    assert numbers_shown(win) == [str(n) for n in range(1101, 1123)]

    d.pager.jump.setText("845")
    d.pager.jump.returnPressed.emit()
    assert numbers_shown(win)[0] == "801"
    assert [i.number for i in d.grid.model_.items if i.hit] == ["845"]
    assert d.pager.buttons[8].isChecked()

    d.pager.jump.setText("5000")
    d.pager.jump.returnPressed.emit()
    assert d.pager.error.text() == "No episode 5000"
    assert numbers_shown(win)[0] == "801"                    # stayed put
    d.pager.jump.textEdited.emit("5")
    assert d.pager.error.text() == ""


def test_short_show_has_no_pages(win):
    open_show(win, STARFALL, "Starfall Academy")
    assert not win.detail.pager.isVisible()
    assert len(win.detail.grid.model_.items) == len(win.ctx.catalog.hianime.episodes(STARFALL))


def test_stills_load_per_page_and_survive_refreshes(win):
    win.ctx.catalog.hianime.counts[STARFALL] = 250
    open_show(win, STARFALL, "Starfall Academy")
    d, fake = win.detail, win.ctx.stills
    assert pump(lambda: d.grid.model_.items[0].still)
    items = {i.number: i for i in d.grid.model_.items}
    assert items["1"].still.startswith("fake://still/") and items["3"].still is None   # 3 gets the tile
    assert fake.calls[-1][1] == [str(n) for n in range(1, 101)]                        # only this page

    d.pager.buttons[2].click()
    assert pump(lambda: len(fake.calls) == 2 and d.grid.model_.items[0].still)
    assert fake.calls[-1][1][0] == "201"
    d.pager.buttons[0].click()                                                          # cached in the page
    assert len(fake.calls) == 2 and d.grid.model_.items[0].still

    d._mark("1", "watched")                                                             # refresh keeps stills
    assert d.grid.model_.items[0].still and d.grid.model_.items[0].state == "watched"


def test_cards_paint_in_every_state(win):
    from ui.episodes import EpisodeItem

    open_show(win, STARFALL, "Starfall Academy")
    d = win.detail
    assert pump(lambda: d.grid.model_.items[0].still)
    pump(lambda: False, timeout=0.3)                     # let the still images load
    items = d.grid.model_.items
    d.grid.model_.set_items([
        EpisodeItem("1", "Seen it", state="watched", still=items[0].still),
        EpisodeItem("2", "Halfway", state="progress", fraction=0.4, up_next=True, still=items[1].still),
        EpisodeItem("3", "Episode 3"),                    # tile, placeholder title
        EpisodeItem("4", "A very long episode title that cannot possibly fit on one card", busy="Starting…"),
        EpisodeItem("5", "Playing", playing=True, state="progress", fraction=0.7, hit=True),
    ])
    img = QImage(d.grid.size(), QImage.Format.Format_ARGB32)
    d.grid.render(img)
    # hovered card: dark overlay and play button over the still
    opt = QStyleOptionViewItem()
    opt.rect = d.grid.visualRect(d.grid.model_.index(0))
    opt.state = QStyle.StateFlag.State_MouseOver
    p = QPainter(img)
    d.grid.delegate.paint(p, opt, d.grid.model_.index(0))
    p.end()
    assert d.grid.model_.index(1).data(EP_ROLE).up_next
    assert d.grid.model_.data(d.grid.model_.index(2), 3) == "Episode 3"          # no ": Episode 3" in tooltip
    assert d.grid.model_.data(d.grid.model_.index(3), 3).endswith("cannot possibly fit on one card")


# -- also fixed in 1.6 ----------------------------------------------------------------------

def test_bridge_reports_a_missing_ani_cli(monkeypatch):
    """The error used to vanish (NameError inside the timer), leaving the episode stuck on Starting…"""
    from core import ani_cli, cli_bridge

    def missing():
        raise ani_cli.AniCliError("ani-cli isn't installed")

    monkeypatch.setattr(cli_bridge, "find_ani_cli", missing)
    bridge = cli_bridge.CliBridge()
    failures = []
    bridge.failed.connect(lambda rid, msg: failures.append((rid, msg)))
    rid = bridge.resolve(ani_cli.ResolveRequest(query="x", index=1, episode="1"))
    assert pump(lambda: failures)
    assert failures == [(rid, "ani-cli isn't installed")]
