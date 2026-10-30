"""Links hianime (what can be streamed) with AniList (how it looks) and the Store.

All methods block on the network; call them from worker threads (core/tasks.py).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from .ani_cli import ResolveRequest
from .anilist import AniListClient, Media
from .hianime import Episode, HianimeClient, SearchResult, normalize_query
from .store import ContinueItem, Store

AUTO_MATCH = 0.85          # minimum score to link automatically
NO_MATCH_TTL = 7 * 24 * 3600   # AniList has no entry for this hianime title
NOT_STREAMABLE_TTL = 24 * 3600  # hianime has no match for this AniList entry (yet)
LOCATE_TTL = 15 * 60            # search order can shift; keep only for a binge session

_ROMAN = {"ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}
_SEASON_PATTERNS = [
    re.compile(r"\bseason (\d+)\b"),
    re.compile(r"\b(\d+)(?:st|nd|rd|th) season\b"),
    re.compile(r"\bpart (\d+)\b"),
    re.compile(r"\bcour (\d+)\b"),
]


class CatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class Located:
    query: str
    index: int
    result: SearchResult


# -- Title matching ------------------------------------------------------------------

def normalize_title(title: str) -> tuple[str, int | None]:
    """Return (comparable text, season number or None). Season 1 is treated as None."""
    t = unicodedata.normalize("NFKD", title)
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
    t = re.sub(r"[’‘`']", "", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = " ".join(t.split())

    season: int | None = None
    for pattern in _SEASON_PATTERNS:
        m = pattern.search(t)
        if m:
            season = int(m.group(1))
            t = pattern.sub(" ", t)
            break
    else:
        words = t.split()
        if words and words[-1] in _ROMAN:
            season = _ROMAN[words.pop()]
            t = " ".join(words)
        elif len(words) > 1 and words[-1].isdigit() and 1 < int(words[-1]) < 10:
            season = int(words.pop())  # "Shingeki no Kyojin 2"
            t = " ".join(words)
    if season == 1:
        season = None
    return " ".join(t.split()), season


def title_score(a: str, b: str) -> float:
    ta, sa = normalize_title(a)
    tb, sb = normalize_title(b)
    if not ta or not tb:
        return 0.0
    score = 1.0 if ta == tb else SequenceMatcher(None, ta, tb).ratio()
    if sa != sb:
        score *= 0.5 if (sa and sb) else 0.6  # different seasons, or a sequel vs. the original
    return score


def best_media_match(title: str, candidates: list[Media]) -> tuple[Media | None, float]:
    best, best_score = None, 0.0
    for rank, media in enumerate(candidates):
        score = max((title_score(title, t) for t in media.all_titles), default=0.0)
        score -= rank * 0.001  # earlier AniList results win ties
        if score > best_score:
            best, best_score = media, score
    return best, round(best_score, 4)


def best_result_match(titles: tuple[str, ...], results: list[SearchResult]) -> tuple[SearchResult | None, float]:
    best, best_score = None, 0.0
    for result in results:
        score = max((title_score(t, result.title) for t in titles), default=0.0)
        score -= result.index * 0.001
        if score > best_score:
            best, best_score = result, score
    return best, round(best_score, 4)


# -- Catalog -------------------------------------------------------------------------

class Catalog:
    def __init__(self, store: Store, hianime: HianimeClient | None = None,
                 anilist: AniListClient | None = None) -> None:
        self.store = store
        self.hianime = hianime or HianimeClient()
        self.anilist = anilist or AniListClient(cache=store)

    # hianime -> AniList (artwork and details for something the user found or watched)
    def enrich(self, anime_id: str, title: str, poster: str | None = None) -> Media | None:
        self.store.upsert_show(anime_id, title, poster)
        show = self.store.get_show(anime_id)
        if show and show.anilist_id:
            return self.anilist.media(show.anilist_id)

        miss_key = f"nomatch:anilist:{anime_id}"
        if self.store.cache_get(miss_key):
            return None
        media, score = best_media_match(title, self.anilist.search(title))
        if media and score >= AUTO_MATCH:
            self.store.set_anilist_match(anime_id, media.anilist_id, score)
            return media
        self.store.cache_put(miss_key, "1", NO_MATCH_TTL)
        return None

    def link_manually(self, anime_id: str, anilist_id: int) -> None:
        self.store.set_anilist_match(anime_id, anilist_id, 1.0, manual=True)

    # AniList -> hianime (a trending card the user clicked)
    def find_streamable(self, media: Media) -> SearchResult | None:
        """The hianime show for an AniList entry. Its `index` is not an ani-cli index; use locate()."""
        known = self.store.find_by_anilist(media.anilist_id)
        if known:
            return SearchResult(index=0, anime_id=known.anime_id, title=known.title, poster=known.poster)

        miss_key = f"nomatch:hianime:{media.anilist_id}"
        if self.store.cache_get(miss_key):
            return None
        titles = media.all_titles
        tried: set[str] = set()
        for query in (media.title_english, media.title_romaji):
            q = normalize_query(query or "")
            if not q or q.lower() in tried:
                continue
            tried.add(q.lower())
            result, score = best_result_match(titles, self.hianime.search(q))
            if result and score >= AUTO_MATCH:
                self.store.upsert_show(result.anime_id, result.title, result.poster)
                self.store.set_anilist_match(result.anime_id, media.anilist_id, score)
                return result
        self.store.cache_put(miss_key, "1", NOT_STREAMABLE_TTL)
        return None

    # anime_id -> the (query, index) pair ani-cli -S needs
    def locate(self, anime_id: str, title: str | None = None) -> Located:
        cache_key = f"locate:{anime_id}"
        cached = self.store.cache_get_json(cache_key)
        if cached:
            return Located(cached["query"], cached["index"],
                           SearchResult(cached["index"], anime_id, cached["title"], cached.get("poster")))

        if title is None:
            show = self.store.get_show(anime_id)
            if not show:
                raise CatalogError(f"Unknown show {anime_id}")
            title = show.title

        base = normalize_query(title)
        words = base.split()
        queries = [base]
        if len(words) > 4:
            queries.append(" ".join(words[:4]))  # long titles: hianime search can be picky
        for query in dict.fromkeys(q for q in queries if q):
            for result in self.hianime.search(query):
                if result.anime_id == anime_id:
                    self.store.cache_put_json(cache_key, {
                        "query": query, "index": result.index,
                        "title": result.title, "poster": result.poster,
                    }, LOCATE_TTL)
                    return Located(query, result.index, result)
        raise CatalogError(f"Couldn't find {title} on hianime anymore")

    def episodes(self, anime_id: str) -> list[Episode]:
        return self.hianime.episodes(anime_id)

    def episodes_for(self, anime_id: str, title: str) -> tuple[str, str, list[Episode]]:
        """Episodes for a saved show, repairing stale ids. Returns (anime_id, title, episodes).

        Ids saved by older ani-cli providers can later point at a different show and
        list nothing for the slug we have. Then search hianime by title, and on a
        confident match move the show's progress to the current id.
        """
        eps = self.hianime.episodes(anime_id)
        if eps:
            return anime_id, title, eps
        fresh = self.relink(anime_id, title)
        if fresh is None:
            return anime_id, title, []
        return fresh.anime_id, fresh.title, self.hianime.episodes(fresh.anime_id)

    def relink(self, anime_id: str, title: str) -> SearchResult | None:
        query = normalize_query(title)
        if not query:
            return None
        candidates = [r for r in self.hianime.search(query) if r.anime_id != anime_id]
        result, score = best_result_match((title,), candidates)
        if not result or score < AUTO_MATCH:
            return None
        self.store.rename_show(anime_id, result.anime_id, result.title, result.poster)
        self.store.cache_delete(f"locate:{anime_id}")
        return result

    def play_request(self, anime_id: str, episode: str, *, title: str | None = None,
                     dub: bool = False, quality: str = "best", skip_intro: bool = False) -> ResolveRequest:
        located = self.locate(anime_id, title)
        return ResolveRequest(query=located.query, index=located.index, episode=episode,
                              dub=dub, quality=quality, skip_intro=skip_intro)

    def verify_stream(self, anime_id: str, stream_title: str | None) -> None:
        """Guard against search order shifting between locate() and ani-cli's own search.

        ani-cli titles streams "<show title> Episode <n>". On a mismatch the cached
        location is dropped and CatalogError is raised so the caller can retry once.
        """
        key = f"locate:{anime_id}"
        located = self.store.cache_get_json(key)
        show = self.store.get_show(anime_id)
        expected = located["title"] if located else (show.title if show else None)
        if not expected or not stream_title:
            return
        if not stream_title.startswith(expected + " Episode "):
            self.store.cache_delete(key)
            raise CatalogError(f"ani-cli picked “{stream_title}” instead of {expected}")

    def mal_id(self, anime_id: str, title: str) -> int | None:
        """MyAnimeList id (for AniSkip) via the show's AniList match."""
        try:
            media = self.enrich(anime_id, title)
        except Exception:  # noqa: BLE001 - AniList down: just no skip times
            return None
        return media.mal_id if media else None

    def cover_for(self, anime_id: str, title: str) -> str | None:
        """Poster URL for a saved show, looking it up on AniList (and saving it) if missing."""
        show = self.store.get_show(anime_id)
        if show and show.poster:
            return show.poster
        media = self.enrich(anime_id, title)
        if media and media.cover:
            self.store.upsert_show(anime_id, title, media.cover)
            return media.cover
        return None

    def resume_episode(self, anime_id: str, episodes: list[Episode]) -> tuple[Episode | None, str]:
        """What the main Play button should do: ("play" | "resume" | "next" | "rewatch")."""
        if not episodes:
            return None, "play"
        progress = self.store.show_progress(anime_id)
        if not progress:
            return episodes[0], "play"
        last = max(progress.values(), key=lambda p: p.updated_at)
        nxt = self.next_episode(ContinueItem(show=None, last=last), episodes)  # type: ignore[arg-type]
        if nxt is None:
            return episodes[0], "rewatch"
        return nxt, ("resume" if nxt.number == last.episode else "next")

    # Continue Watching
    @staticmethod
    def next_episode(item: ContinueItem, episodes: list[Episode]) -> Episode | None:
        """Resume an unfinished episode, otherwise the one after it. None when caught up."""
        numbers = [e.number for e in episodes]
        if item.last.episode not in numbers:
            return episodes[0] if episodes else None
        i = numbers.index(item.last.episode)
        if not item.last.completed:
            return episodes[i]
        return episodes[i + 1] if i + 1 < len(episodes) else None
