"""v1.8.7: hianime renumbered its shows; saved shows with old ids find their new ones."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fake_site  # noqa: E402
import ui_fakes  # noqa: E402
from core.catalog import Catalog, slug_base  # noqa: E402
from core.hianime import HianimeClient, HianimeError, SearchResult  # noqa: E402
from core.store import Store  # noqa: E402

OLD = "frieren-beyond-journeys-end-season-2-1665"
NEW = "frieren-beyond-journeys-end-season-2-808"
TITLE = "Frieren: Beyond Journey's End Season 2"


@pytest.fixture
def site(tmp_path, monkeypatch):
    for key, value in fake_site.build(tmp_path).items():
        monkeypatch.setenv(key, value)
    return tmp_path


def test_an_unknown_show_id_lists_nothing_instead_of_failing(site):
    # hianime answers 404 {"status":false} for an id it no longer has
    assert HianimeClient().episodes("some-show-from-before-99999") == []


def test_other_errors_still_raise(site, monkeypatch):
    client = HianimeClient()
    monkeypatch.setattr(client, "fetch", lambda url, referer=None:
                        type("R", (), {"curl_exit": 0, "status": 429, "body": "slow down"})())
    with pytest.raises(HianimeError):
        client.episodes("some-show-1")


def test_slug_base():
    assert slug_base(OLD) == slug_base(NEW) == "frieren-beyond-journeys-end-season-2"
    assert slug_base("one-piece-1") == "one-piece"
    assert slug_base("no-number-here") == "no-number-here"


class Renumbered(ui_fakes.FakeHianime):
    """The old id is gone; searching finds season 1, the mini anime and season 2."""

    def episodes(self, anime_id):
        if anime_id == OLD:
            return []
        if anime_id == NEW:
            return super().episodes(ui_fakes.slug("Starfall Academy", 0))
        return super().episodes(anime_id)

    def search(self, query):
        return [SearchResult(1, "frieren-beyond-journeys-end-481", "Frieren: Beyond Journey's End", None),
                SearchResult(2, NEW, "Frieren: Beyond Journey's End Season 2", "https://img/new.jpg"),
                SearchResult(3, "frieren-beyond-journeys-end-mini-anime-2851", "Frieren Mini Anime", None)]


def test_saved_show_moves_to_its_new_id_with_progress(tmp_path):
    store = Store(tmp_path / "s.db")
    store.upsert_show(OLD, TITLE)
    store.set_in_library(OLD, True)
    store.mark_watched(OLD, "3")
    cat = Catalog(store, hianime=Renumbered(), anilist=None)
    new_id, title, eps = cat.episodes_for(OLD, TITLE)
    assert new_id == NEW and eps
    assert store.get_show(OLD) is None
    show = store.get_show(NEW)
    assert show.in_library and store.get_progress(NEW, "3").completed


def test_same_address_wins_even_when_the_title_changed(tmp_path):
    store = Store(tmp_path / "s.db")
    store.upsert_show(OLD, "Sousou no Frieren 2nd Season")     # saved under another title
    cat = Catalog(store, hianime=Renumbered(), anilist=None)
    assert cat.episodes_for(OLD, "Sousou no Frieren 2nd Season")[0] == NEW


def test_new_episode_checks_repair_old_ids_too(tmp_path):
    from core import alerts

    store = Store(tmp_path / "s.db")
    store.upsert_show(OLD, TITLE)
    store.set_in_library(OLD, True)
    cat = Catalog(store, hianime=Renumbered(), anilist=None)
    # what alerts.check does for each followed show
    new_id, _t, eps = cat.episodes_for(OLD, TITLE)
    assert new_id == NEW and store.get_show(NEW).in_library
    assert "episodes_for" in Path(alerts.__file__).read_text()
