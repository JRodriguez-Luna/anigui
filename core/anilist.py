"""AniList GraphQL client: trending, seasonal, search, and lookup by id.

AniList supplies cover art, banners, synopses and scores. hianime stays the source
of truth for what can actually be streamed; core/catalog.py links the two.
Responses are cached in the Store, and HTTP 429 is retried using Retry-After.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from . import http

API_URL = "https://graphql.anilist.co"

TTL_TRENDING = 6 * 3600
TTL_SEASON = 12 * 3600
TTL_SEARCH = 7 * 24 * 3600
TTL_MEDIA = 24 * 3600
TTL_AIRING = 30 * 60
TTL_RELATED = 24 * 3600
TTL_BROWSE = 6 * 3600
TTL_SCHEDULE = 30 * 60
MAX_SCHEDULE_PAGES = 8   # 50 per page; a busy week has ~150 episodes

# AniList's genre list (minus adult-only ones), for the search filters
GENRES = ("Action", "Adventure", "Comedy", "Drama", "Ecchi", "Fantasy", "Horror", "Mahou Shoujo", "Mecha", "Music",
          "Mystery", "Psychological", "Romance", "Sci-Fi", "Slice of Life", "Sports", "Supernatural", "Thriller")
MAX_RETRY_WAIT = 60.0

_FIELDS = """
fragment f on Media {
  id idMal
  title { romaji english native }
  synonyms
  coverImage { extraLarge large color }
  bannerImage
  description(asHtml: false)
  episodes status format genres averageScore season seasonYear popularity
  nextAiringEpisode { episode airingAt }
}
"""

Q_TRENDING = _FIELDS + """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(type: ANIME, sort: TRENDING_DESC, isAdult: false) { ...f }
  }
}"""

Q_SEASON = _FIELDS + """
query ($season: MediaSeason, $year: Int, $page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(type: ANIME, season: $season, seasonYear: $year, sort: POPULARITY_DESC, isAdult: false) { ...f }
  }
}"""

Q_SEARCH = _FIELDS + """
query ($search: String, $perPage: Int) {
  Page(page: 1, perPage: $perPage) {
    media(type: ANIME, search: $search, isAdult: false) { ...f }
  }
}"""

Q_AIRING = _FIELDS + """
query ($ids: [Int], $perPage: Int) {
  Page(page: 1, perPage: $perPage) {
    media(id_in: $ids, type: ANIME) { ...f }
  }
}"""

Q_BROWSE = _FIELDS + """
query ($search: String, $genres: [String], $year: Int, $season: MediaSeason, $formats: [MediaFormat],
       $status: MediaStatus, $sort: [MediaSort], $page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(type: ANIME, isAdult: false, search: $search, genre_in: $genres, seasonYear: $year, season: $season,
          format_in: $formats, status: $status, sort: $sort) { ...f }
  }
}"""

Q_SCHEDULE = _FIELDS + """
query ($start: Int, $end: Int, $ids: [Int], $page: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    airingSchedules(airingAt_greater: $start, airingAt_lesser: $end, mediaId_in: $ids, sort: TIME) {
      episode airingAt media { isAdult ...f }
    }
  }
}"""

Q_RELATED = _FIELDS + """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    relations { edges { relationType(version: 2) node { type ...f } } }
    recommendations(sort: RATING_DESC, perPage: 16) { nodes { rating mediaRecommendation { type ...f } } }
  }
}"""

# Order and wording for the Related row; anything else falls under "Related"
RELATION_LABELS = {
    "PREQUEL": "Prequel", "SEQUEL": "Sequel", "PARENT": "Main story", "SIDE_STORY": "Side story",
    "SPIN_OFF": "Spin-off", "ALTERNATIVE": "Alternate version", "SUMMARY": "Recap", "COMPILATION": "Compilation",
    "CONTAINS": "Part of", "OTHER": "Related", "CHARACTER": "Crossover",
}
RELATION_ORDER = list(RELATION_LABELS)

Q_MEDIA = _FIELDS + """
query ($id: Int) { Media(id: $id, type: ANIME) { ...f } }
"""

_TAGS = re.compile(r"<[^>]+>")


class AniListError(RuntimeError):
    pass


class Cache(Protocol):
    def cache_get_json(self, key: str) -> Any | None: ...
    def cache_put_json(self, key: str, value: Any, ttl: float) -> None: ...


Transport = Callable[[bytes], http.Response]


def _default_transport(payload: bytes) -> http.Response:
    return http.request(
        API_URL, data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )


@dataclass(frozen=True)
class Media:
    anilist_id: int
    mal_id: int | None
    title_romaji: str | None
    title_english: str | None
    title_native: str | None
    synonyms: tuple[str, ...]
    cover: str | None
    cover_color: str | None
    banner: str | None
    description: str
    episodes: int | None
    status: str | None
    format: str | None
    genres: tuple[str, ...]
    score: int | None
    season: str | None
    year: int | None
    next_episode: int | None = None
    next_airing_at: int | None = None
    popularity: int | None = None

    @property
    def display_title(self) -> str:
        return self.title_english or self.title_romaji or self.title_native or f"#{self.anilist_id}"

    @property
    def all_titles(self) -> tuple[str, ...]:
        seen: list[str] = []
        for t in (self.title_english, self.title_romaji, *self.synonyms):
            if t and t not in seen:
                seen.append(t)
        return tuple(seen)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Media":
        title = d.get("title") or {}
        cover = d.get("coverImage") or {}
        nxt = d.get("nextAiringEpisode") or {}
        return cls(
            anilist_id=int(d["id"]),
            mal_id=d.get("idMal"),
            title_romaji=title.get("romaji"),
            title_english=title.get("english"),
            title_native=title.get("native"),
            synonyms=tuple(d.get("synonyms") or ()),
            cover=cover.get("extraLarge") or cover.get("large"),
            cover_color=cover.get("color"),
            banner=d.get("bannerImage"),
            description=clean_description(d.get("description")),
            episodes=d.get("episodes"),
            status=d.get("status"),
            format=d.get("format"),
            genres=tuple(d.get("genres") or ()),
            score=d.get("averageScore"),
            season=d.get("season"),
            year=d.get("seasonYear"),
            next_episode=nxt.get("episode"),
            next_airing_at=nxt.get("airingAt"),
            popularity=d.get("popularity"),
        )


@dataclass(frozen=True)
class Airing:
    media: Media
    episode: int
    airing_at: int       # unix time


@dataclass(frozen=True)
class Related:
    media: Media
    relation: str        # AniList relationType, e.g. SEQUEL

    @property
    def label(self) -> str:
        return RELATION_LABELS.get(self.relation, "Related")


def clean_description(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = html.unescape(_TAGS.sub("", text))
    text = re.sub(r"\n{3,}", "\n\n", text)
    # AniList appends "(Source: ...)" credits; keep the synopsis itself.
    text = re.sub(r"\s*\(Source:[^)]*\)\s*$", "", text.strip())
    return text.strip()


def current_season(today: dt.date | None = None) -> tuple[str, int]:
    """AniList season for a date. December belongs to next year's WINTER."""
    today = today or dt.date.today()
    m, y = today.month, today.year
    if m == 12:
        return "WINTER", y + 1
    if m <= 2:
        return "WINTER", y
    if m <= 5:
        return "SPRING", y
    if m <= 8:
        return "SUMMER", y
    return "FALL", y


class AniListClient:
    def __init__(self, cache: Cache | None = None, transport: Transport | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.cache = cache
        self.transport = transport or _default_transport
        self.sleep = sleep

    # -- public API ----------------------------------------------------------------

    def trending(self, page: int = 1, per_page: int = 24) -> list[Media]:
        data = self._query(Q_TRENDING, {"page": page, "perPage": per_page}, TTL_TRENDING)
        return [Media.from_json(m) for m in data["Page"]["media"]]

    def season(self, season: str | None = None, year: int | None = None,
               page: int = 1, per_page: int = 24) -> list[Media]:
        if season is None or year is None:
            season, year = current_season()
        data = self._query(Q_SEASON, {"season": season, "year": year, "page": page, "perPage": per_page}, TTL_SEASON)
        return [Media.from_json(m) for m in data["Page"]["media"]]

    def search(self, text: str, per_page: int = 8) -> list[Media]:
        text = " ".join(text.split())
        if not text:
            return []
        data = self._query(Q_SEARCH, {"search": text, "perPage": per_page}, TTL_SEARCH)
        return [Media.from_json(m) for m in data["Page"]["media"]]

    def media(self, anilist_id: int) -> Media | None:
        data = self._query(Q_MEDIA, {"id": anilist_id}, TTL_MEDIA, allow_not_found=True)
        return Media.from_json(data["Media"]) if data and data.get("Media") else None

    def browse(self, *, search: str | None = None, genres: list[str] | None = None, year: int | None = None,
               season: str | None = None, formats: list[str] | None = None, status: str | None = None,
               sort: str | None = None, page: int = 1, per_page: int = 50) -> list[Media]:
        """Filtered search. Any argument left as None isn't filtered on.

        sort: AniList MediaSort, e.g. POPULARITY_DESC. None means best match when
        there's text, most popular when there isn't.
        """
        search = " ".join((search or "").split()) or None
        order = [sort] if sort else (["SEARCH_MATCH", "POPULARITY_DESC"] if search else ["POPULARITY_DESC"])
        variables = {"search": search, "genres": list(genres) if genres else None, "year": year,
                     "season": season, "formats": list(formats) if formats else None, "status": status,
                     "sort": order, "page": page, "perPage": per_page}
        data = self._query(Q_BROWSE, variables, TTL_BROWSE)
        return [Media.from_json(m) for m in data["Page"]["media"]]

    def schedule(self, start: int, end: int, anilist_ids: list[int] | None = None) -> list[Airing]:
        """Episodes airing between two unix times, in airing order. `anilist_ids` limits it to
        those shows (None = everything airing). Adult titles are left out."""
        if anilist_ids is not None and not anilist_ids:
            return []
        ids = sorted({int(i) for i in anilist_ids}) if anilist_ids else None
        found: list[Airing] = []
        for page in range(1, MAX_SCHEDULE_PAGES + 1):
            data = self._query(Q_SCHEDULE, {"start": start - 1, "end": end, "ids": ids, "page": page}, TTL_SCHEDULE)
            block = data["Page"]
            for item in block.get("airingSchedules") or []:
                m = item.get("media") or {}
                if m and not m.get("isAdult"):
                    found.append(Airing(Media.from_json(m), int(item["episode"]), int(item["airingAt"])))
            if not (block.get("pageInfo") or {}).get("hasNextPage"):
                break
        return found

    def related(self, anilist_id: int) -> tuple[list[Related], list[Media]]:
        """(sequels, prequels, movies… in a sensible order; community recommendations, best first).
        Manga and novels are left out: only anime can be watched."""
        data = self._query(Q_RELATED, {"id": anilist_id}, TTL_RELATED, allow_not_found=True)
        node = (data or {}).get("Media") or {}
        related: list[Related] = []
        for edge in (node.get("relations") or {}).get("edges") or []:
            m = edge.get("node") or {}
            if m.get("type") == "ANIME" and edge.get("relationType") not in ("SOURCE", "ADAPTATION"):
                related.append(Related(Media.from_json(m), edge.get("relationType") or "OTHER"))
        related.sort(key=lambda r: (RELATION_ORDER.index(r.relation) if r.relation in RELATION_ORDER
                                    else len(RELATION_ORDER), r.media.year or 9999))
        recs: list[Media] = []
        seen = {anilist_id, *(r.media.anilist_id for r in related)}
        for rec in (node.get("recommendations") or {}).get("nodes") or []:
            m = rec.get("mediaRecommendation")
            if m and m.get("type") == "ANIME" and (rec.get("rating") or 0) > 0 and m["id"] not in seen:
                seen.add(m["id"])
                recs.append(Media.from_json(m))
        return related, recs

    def airing(self, anilist_ids: list[int]) -> dict[int, Media]:
        """Fresh status and next-episode info for several shows (cached briefly)."""
        ids = sorted({int(i) for i in anilist_ids if i})
        found: dict[int, Media] = {}
        for start in range(0, len(ids), 50):
            chunk = ids[start:start + 50]
            data = self._query(Q_AIRING, {"ids": chunk, "perPage": len(chunk)}, TTL_AIRING)
            for m in data["Page"]["media"]:
                media = Media.from_json(m)
                found[media.anilist_id] = media
        return found

    # -- transport -------------------------------------------------------------------

    def _query(self, query: str, variables: dict[str, Any], ttl: float,
               allow_not_found: bool = False) -> dict[str, Any]:
        payload = json.dumps({"query": query, "variables": variables}, sort_keys=True).encode()
        key = "anilist:" + hashlib.sha1(payload).hexdigest()
        if self.cache is not None:
            cached = self.cache.cache_get_json(key)
            if cached is not None:
                return cached

        for attempt in range(2):
            try:
                resp = self.transport(payload)
            except OSError as exc:
                raise AniListError(f"Could not reach AniList: {exc}") from exc
            if resp.status == 429 and attempt == 0:
                wait = _retry_after(resp.headers)
                if wait <= MAX_RETRY_WAIT:
                    self.sleep(wait)
                    continue
            break

        try:
            body = json.loads(resp.body or b"{}")
        except json.JSONDecodeError as exc:
            raise AniListError(f"AniList returned invalid JSON (HTTP {resp.status})") from exc

        if resp.status == 404 and allow_not_found:
            return {}
        if resp.status == 429:
            raise AniListError("AniList rate limit reached; try again in a minute")
        if resp.status != 200 or body.get("errors"):
            msgs = "; ".join(e.get("message", "?") for e in body.get("errors") or [])
            raise AniListError(f"AniList error (HTTP {resp.status}){': ' + msgs if msgs else ''}")

        data = body.get("data") or {}
        if self.cache is not None:
            self.cache.cache_put_json(key, data, ttl)
        return data


def _retry_after(headers: dict[str, str]) -> float:
    try:
        return max(1.0, float(headers.get("retry-after", "60")))
    except ValueError:
        return 60.0
