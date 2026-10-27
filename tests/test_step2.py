"""Step 2 tests: store, AniList, covers, matching, catalog, task runner. Fully offline."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import http  # noqa: E402
from core.anilist import AniListClient, AniListError, Media, clean_description, current_season  # noqa: E402
from core.catalog import (  # noqa: E402
    AUTO_MATCH, Catalog, CatalogError, best_media_match, normalize_title, title_score,
)
from core.covers import CoverCache, CoverError  # noqa: E402
from core.hianime import Episode, SearchResult  # noqa: E402
from core.store import ContinueItem, Progress, Store  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
JPG = b"\xff\xd8\xff\xe0" + b"1" * 100


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def media_json(i, english, romaji=None, synonyms=(), episodes=12):
    return {
        "id": i, "idMal": i + 1000,
        "title": {"romaji": romaji or english, "english": english, "native": None},
        "synonyms": list(synonyms),
        "coverImage": {"extraLarge": f"https://s4.anilist.co/c/{i}.jpg", "large": None, "color": "#334455"},
        "bannerImage": f"https://s4.anilist.co/b/{i}.jpg",
        "description": "A mage's journey.<br><br><i>Elves</i> &amp; humans.<br>(Source: Crunchyroll)",
        "episodes": episodes, "status": "FINISHED", "format": "TV", "genres": ["Fantasy"],
        "averageScore": 90, "season": "FALL", "seasonYear": 2023,
        "nextAiringEpisode": None,
    }


FRIEREN = media_json(154587, "Frieren: Beyond Journey’s End", "Sousou no Frieren", ["Frieren at the Funeral"], 28)
FRIEREN_S2 = media_json(182255, "Frieren: Beyond Journey’s End Season 2", "Sousou no Frieren 2nd Season", episodes=None)
AOT = media_json(16498, "Attack on Titan", "Shingeki no Kyojin", episodes=25)
AOT_S2 = media_json(20958, "Attack on Titan Season 2", "Shingeki no Kyojin 2", episodes=12)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, payload: bytes) -> http.Response:
        self.calls.append(json.loads(payload))
        status, body, headers = self.responses.pop(0)
        return http.Response(status, headers or {}, json.dumps(body).encode())


def page(*media):
    return (200, {"data": {"Page": {"media": list(media)}}}, None)


class FakeHianime:
    def __init__(self, catalog: dict[str, list[tuple[str, str]]], episodes=None):
        self.catalog = catalog  # query(lower) -> [(anime_id, title)]
        self.searches = []
        self._episodes = episodes or {}

    def search(self, query):
        self.searches.append(query)
        rows = self.catalog.get(query.lower(), [])
        return [SearchResult(i, aid, t, None) for i, (aid, t) in enumerate(rows, start=1)]

    def episodes(self, anime_id):
        return [Episode(n, str(100 + i), None) for i, n in enumerate(self._episodes.get(anime_id, []))]


# -- Store -------------------------------------------------------------------------------

def test_store_upsert_keeps_poster_and_library(store):
    store.upsert_show("a-1", "A", "https://p/a.jpg")
    store.upsert_show("a-1", "A renamed")
    show = store.get_show("a-1")
    assert show.title == "A renamed" and show.poster == "https://p/a.jpg"

    store.upsert_show("b-2", "B")
    store.set_in_library("a-1", True)
    time.sleep(0.01)
    store.set_in_library("b-2", True)
    assert [s.anime_id for s in store.library()] == ["b-2", "a-1"]
    store.set_in_library("b-2", False)
    assert [s.anime_id for s in store.library()] == ["a-1"]


def test_progress_completion_rules(store):
    store.upsert_show("a-1", "A")
    p = store.record_progress("a-1", "1", 300, 1440)
    assert not p.completed and abs(p.fraction - 300 / 1440) < 1e-9
    p = store.record_progress("a-1", "1", 1300, 1440)
    assert p.completed
    p = store.record_progress("a-1", "1", 10, 1440)  # rewatching doesn't un-watch
    assert p.completed and p.position == 10
    store.mark_watched("a-1", "1", False)
    assert store.get_progress("a-1", "1") is None
    store.mark_watched("a-1", "2")
    assert store.show_progress("a-1")["2"].completed


def test_continue_watching_latest_per_show(store):
    for aid in ("a-1", "b-2"):
        store.upsert_show(aid, aid.upper())
    store.record_progress("a-1", "1", 100, 1000)
    time.sleep(0.01)
    store.record_progress("b-2", "4", 100, 1000)
    time.sleep(0.01)
    store.record_progress("a-1", "2", 50, 1000)
    items = store.continue_watching()
    assert [(i.show.anime_id, i.last.episode) for i in items] == [("a-1", "2"), ("b-2", "4")]
    assert items[0].show.title == "A-1"


def test_import_ani_cli_history(store, tmp_path):
    hist = tmp_path / "ani-hsts"
    hist.write_text(
        "3\tfrieren-beyond-journeys-end-18542\tFrieren: Beyond Journey's End\n"
        "5\tReooPAxPMsHM4KPMY\tOld v4 entry\n"
        "garbage line\n"
        "12\tone-piece-100\tOne Piece\n",
        encoding="utf-8",
    )
    assert store.import_ani_cli_history(hist) == 2
    assert store.import_ani_cli_history(hist) == 0  # idempotent
    assert store.get_progress("frieren-beyond-journeys-end-18542", "3").completed
    assert store.get_progress("one-piece-100", "12").source == "ani-cli"
    assert store.get_show("ReooPAxPMsHM4KPMY") is None

    store.record_progress("one-piece-100", "12", 30, 1400)  # GUI progress isn't overwritten
    store.import_ani_cli_history(hist)
    assert store.get_progress("one-piece-100", "12").position == 30


def test_import_missing_history_file(store, tmp_path):
    assert store.import_ani_cli_history(tmp_path / "nope") == 0


def test_cache_ttl(store, monkeypatch):
    store.cache_put_json("k", {"a": 1}, ttl=10)
    assert store.cache_get_json("k") == {"a": 1}
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 11)
    assert store.cache_get_json("k") is None
    assert store.cache_prune() == 1


def test_store_concurrent_writers(store):
    store.upsert_show("a-1", "A")
    errors = []

    def work(n):
        try:
            for i in range(25):
                store.record_progress("a-1", f"{n}-{i}", i, 100)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(store.show_progress("a-1")) == 200


def test_store_refuses_newer_schema(tmp_path):
    db = tmp_path / "new.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version=99")
    conn.close()
    with pytest.raises(RuntimeError, match="newer"):
        Store(db)


# -- AniList ----------------------------------------------------------------------------

def test_media_from_json_and_description():
    m = Media.from_json(FRIEREN)
    assert m.display_title == "Frieren: Beyond Journey’s End"
    assert m.cover.endswith("/154587.jpg") and m.mal_id == 155587
    assert m.description == "A mage's journey.\n\nElves & humans."
    assert m.all_titles[:2] == ("Frieren: Beyond Journey’s End", "Sousou no Frieren")
    assert clean_description(None) == ""


def test_trending_uses_cache(store):
    t = FakeTransport([page(FRIEREN, AOT)])
    client = AniListClient(cache=store, transport=t)
    first = client.trending(per_page=2)
    second = client.trending(per_page=2)
    assert [m.anilist_id for m in first] == [154587, 16498] == [m.anilist_id for m in second]
    assert len(t.calls) == 1
    assert t.calls[0]["variables"] == {"page": 1, "perPage": 2}


def test_rate_limit_retry():
    slept = []
    t = FakeTransport([(429, {"errors": [{"message": "Too Many Requests."}]}, {"retry-after": "3"}), page(AOT)])
    client = AniListClient(transport=t, sleep=slept.append)
    assert client.search("attack on titan")[0].anilist_id == 16498
    assert slept == [3.0]


def test_rate_limit_gives_up_after_one_retry():
    t = FakeTransport([(429, {}, {"retry-after": "1"}), (429, {}, {"retry-after": "1"})])
    with pytest.raises(AniListError, match="rate limit"):
        AniListClient(transport=t, sleep=lambda s: None).trending()


def test_graphql_error_and_not_found():
    t = FakeTransport([(400, {"errors": [{"message": "Bad field"}]}, None)])
    with pytest.raises(AniListError, match="Bad field"):
        AniListClient(transport=t).trending()
    t = FakeTransport([(404, {"errors": [{"message": "Not Found."}], "data": {"Media": None}}, None)])
    assert AniListClient(transport=t).media(1) is None


def test_network_failure_wrapped():
    def boom(_payload):
        raise OSError("offline")
    with pytest.raises(AniListError, match="offline"):
        AniListClient(transport=boom).trending()


def test_current_season():
    assert current_season(dt.date(2026, 10, 26)) == ("FALL", 2026)
    assert current_season(dt.date(2026, 12, 2)) == ("WINTER", 2027)
    assert current_season(dt.date(2027, 2, 28)) == ("WINTER", 2027)
    assert current_season(dt.date(2027, 3, 1)) == ("SPRING", 2027)
    assert current_season(dt.date(2027, 7, 4)) == ("SUMMER", 2027)


# -- Covers -------------------------------------------------------------------------------

def test_cover_cache_download_once_and_prune(tmp_path):
    fetched = []

    def fetch(url):
        fetched.append(url)
        return PNG if url.endswith(".png") else JPG

    cache = CoverCache(tmp_path / "covers", fetcher=fetch, budget_bytes=150)
    a = cache.get("https://x/a.png")
    assert a.suffix == ".png" and a.read_bytes() == PNG
    assert cache.get("https://x/a.png") == a and fetched == ["https://x/a.png"]
    assert cache.cached_path("https://x/b.jpg") is None

    time.sleep(0.01)
    b = cache.get("https://x/b.jpg")
    assert b.suffix == ".jpg"
    assert cache.prune() == 1           # budget fits one image; oldest goes
    assert not a.exists() and b.exists()


def test_cover_cache_rejects_non_images(tmp_path):
    cache = CoverCache(tmp_path, fetcher=lambda url: b"<html>blocked</html>")
    with pytest.raises(CoverError):
        cache.get("https://x/a.jpg")
    assert list(tmp_path.iterdir()) == []


# -- Matching ---------------------------------------------------------------------------

def test_normalize_title():
    assert normalize_title("Frieren: Beyond Journey’s End") == ("frieren beyond journeys end", None)
    assert normalize_title("Attack on Titan Season 2") == ("attack on titan", 2)
    assert normalize_title("Sousou no Frieren 2nd Season") == ("sousou no frieren", 2)
    assert normalize_title("Shingeki no Kyojin 2") == ("shingeki no kyojin", 2)
    assert normalize_title("Mob Psycho 100 III") == ("mob psycho 100", 3)
    assert normalize_title("Kaguya-sama Season 1") == ("kaguya sama", None)


def test_title_score_separates_seasons():
    assert title_score("Frieren: Beyond Journey's End", "Frieren: Beyond Journey’s End") == 1.0
    assert title_score("Attack on Titan Season 2", "Shingeki no Kyojin 2") < AUTO_MATCH
    assert title_score("Attack on Titan Season 2", "Attack on Titan") < AUTO_MATCH
    assert title_score("Attack on Titan Season 2", "Attack on Titan 2nd Season") == 1.0


def test_best_media_match_prefers_right_season():
    candidates = [Media.from_json(AOT), Media.from_json(AOT_S2)]
    m, score = best_media_match("Attack on Titan Season 2", candidates)
    assert m.anilist_id == 20958 and score >= AUTO_MATCH
    m, _ = best_media_match("Attack on Titan", candidates)
    assert m.anilist_id == 16498


# -- Catalog -----------------------------------------------------------------------------

FRIEREN_ID = "frieren-beyond-journeys-end-18542"


def test_enrich_links_once_and_caches(store):
    t = FakeTransport([page(FRIEREN, FRIEREN_S2), (200, {"data": {"Media": FRIEREN}}, None)])
    cat = Catalog(store, hianime=FakeHianime({}), anilist=AniListClient(cache=store, transport=t))
    m = cat.enrich(FRIEREN_ID, "Frieren: Beyond Journey's End", "https://p/f.jpg")
    assert m.anilist_id == 154587
    show = store.get_show(FRIEREN_ID)
    assert show.anilist_id == 154587 and show.match_score >= AUTO_MATCH and show.poster == "https://p/f.jpg"
    assert cat.enrich(FRIEREN_ID, "Frieren: Beyond Journey's End").anilist_id == 154587
    assert [c["variables"].get("id") for c in t.calls] == [None, 154587]


def test_enrich_no_match_is_negative_cached(store):
    t = FakeTransport([page(AOT)])
    cat = Catalog(store, hianime=FakeHianime({}), anilist=AniListClient(cache=store, transport=t))
    assert cat.enrich("obscure-ova-1", "Obscure OVA Collection") is None
    assert cat.enrich("obscure-ova-1", "Obscure OVA Collection") is None
    assert len(t.calls) == 1


def test_manual_link_survives_auto_match(store):
    store.upsert_show("x-1", "X")
    Catalog(store, hianime=FakeHianime({}), anilist=AniListClient(transport=FakeTransport([]))).link_manually("x-1", 5)
    store.set_anilist_match("x-1", 6, 0.99)
    assert store.get_show("x-1").anilist_id == 5


def test_find_streamable_and_shortcut(store):
    hi = FakeHianime({
        "frieren beyond journey s end": [],  # english title search finds nothing
        "sousou no frieren": [("frieren-mini-anime-19001", "Frieren Mini Anime"),
                              (FRIEREN_ID, "Frieren: Beyond Journey's End")],
    })
    cat = Catalog(store, hianime=hi, anilist=AniListClient(transport=FakeTransport([])))
    media = Media.from_json(FRIEREN)
    found = cat.find_streamable(media)
    assert found.anime_id == FRIEREN_ID
    assert hi.searches == ["Frieren Beyond Journey s End", "Sousou no Frieren"]
    assert cat.find_streamable(media).anime_id == FRIEREN_ID
    assert len(hi.searches) == 2  # second call answered from the store


def test_locate_and_play_request(store):
    hi = FakeHianime({"frieren beyond journey's end": [("other-1", "Other"), (FRIEREN_ID, "Frieren: Beyond Journey's End")]})
    cat = Catalog(store, hianime=hi, anilist=AniListClient(transport=FakeTransport([])))
    store.upsert_show(FRIEREN_ID, "Frieren: Beyond Journey's End")
    req = cat.play_request(FRIEREN_ID, "5", dub=True)
    assert (req.query, req.index, req.episode, req.dub) == ("Frieren Beyond Journey's End", 2, "5", True)
    cat.play_request(FRIEREN_ID, "6")
    assert len(hi.searches) == 1  # cached

    cat.verify_stream(FRIEREN_ID, "Frieren: Beyond Journey's End Episode 6")
    with pytest.raises(CatalogError):
        cat.verify_stream(FRIEREN_ID, "Other Episode 6")
    cat.play_request(FRIEREN_ID, "6")
    assert len(hi.searches) == 2  # mismatch dropped the cached location

    with pytest.raises(CatalogError, match="Unknown show"):
        cat.locate("missing-1")


def test_next_episode():
    eps = [Episode(n, str(i), None) for i, n in enumerate(["1", "2", "3"])]

    def item(ep, done):
        return ContinueItem(show=None, last=Progress("a", ep, 10, 100, done, "gui", 0))  # type: ignore[arg-type]

    assert Catalog.next_episode(item("2", False), eps).number == "2"
    assert Catalog.next_episode(item("2", True), eps).number == "3"
    assert Catalog.next_episode(item("3", True), eps) is None
    assert Catalog.next_episode(item("9", True), eps).number == "1"


# -- Task runner -------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


def _pump(app, runner, timeout=5.0):
    from PySide6.QtCore import QCoreApplication
    end = time.time() + timeout
    while (runner.pending() or runner.pool.activeThreadCount()) and time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()


def test_task_runner_delivers_on_main_thread(qapp):
    from core.tasks import TaskRunner

    runner = TaskRunner()
    main = threading.get_ident()
    got = {}

    def work(x):
        got["worker"] = threading.get_ident()
        return x * 2

    def done(value):
        got["value"] = value
        got["callback"] = threading.get_ident()

    runner.submit(work, 21, on_done=done)
    runner.submit(lambda: 1 / 0, on_error=lambda msg: got.setdefault("error", msg))
    _pump(qapp, runner)
    assert got["value"] == 42
    assert got["worker"] != main and got["callback"] == main
    assert "division by zero" in got["error"]


def test_task_runner_group_latest_wins(qapp):
    from core.tasks import TaskRunner

    runner = TaskRunner()
    delivered = []

    def slow(tag, delay):
        time.sleep(delay)
        return tag

    runner.submit(slow, "old", 0.2, on_done=delivered.append, group="search")
    runner.submit(slow, "new", 0.01, on_done=delivered.append, group="search")
    tid = runner.submit(slow, "cancelled", 0.01, on_done=delivered.append)
    runner.cancel(tid)
    _pump(qapp, runner)
    assert delivered == ["new"]
