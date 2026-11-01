"""Episode stills (thumbnails) for the show page.

Three sources, best first:
- AniList's `streamingEpisodes` (Crunchyroll's episode thumbnails). Often complete for
  shows on Crunchyroll, partial for long ones, and sometimes attached to the wrong
  season (My Hero Academia season 1 lists episodes 139-159).
- Kitsu's episode list, which fills the gaps for most popular shows.
- ani.zip (TheTVDB's episode images, keyed by AniList id), which usually has shows
  that are airing right now, days before the other two.

No source is trusted blindly: a still is only used for an episode number the show
actually has, and when both sides have a real episode title, the titles must agree.
Anything doubtful falls back to the numbered tile in the UI. Network trouble never
raises: the page just shows fewer stills.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Callable, Iterable

from . import http
from .anilist import AniListClient, AniListError, Cache

KITSU_API = "https://kitsu.app/api/edge"
KITSU_PAGE = 20                 # Kitsu's maximum page size
MAX_KITSU_PAGES = 6             # per request: enough for one 100-episode page of the grid
TTL_KITSU_ID = 30 * 24 * 3600
TTL_KITSU_EPISODES = 3 * 24 * 3600
ANIZIP_API = "https://api.ani.zip/mappings?anilist_id={id}"
TTL_ANIZIP = 24 * 3600          # airing shows gain an episode a week

_EP_PREFIX = re.compile(r"^\s*(?:episode|ep\.?)\s*(\d+(?:\.\d+)?)\s*(?:[-:–—]\s*)?", re.I)
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "to", "and", "in", "on", "is", "for", "at", "with", "part"}

Fetch = Callable[[str], bytes]


def _kitsu_fetch(url: str) -> bytes:
    resp = http.request(url, headers={"Accept": "application/vnd.api+json"}, timeout=20)
    if resp.status != 200:
        raise OSError(f"Kitsu HTTP {resp.status}")
    return resp.body


def _anizip_fetch(url: str) -> bytes:
    resp = http.request(url, headers={"Accept": "application/json"}, timeout=20)
    if resp.status != 200:
        raise OSError(f"ani.zip HTTP {resp.status}")
    return resp.body


def number_key(number: str | float | int | None) -> str | None:
    """'7', '7.0', 7 -> '7'; '12.5' stays '12.5'. None for anything that isn't a number."""
    try:
        value = float(number)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return str(int(value)) if value.is_integer() else f"{value:g}"


def parse_streaming_title(title: str) -> tuple[str | None, str]:
    """'Episode 12 - The Wind Rises' -> ('12', 'The Wind Rises')."""
    m = _EP_PREFIX.match(title or "")
    if not m:
        return None, (title or "").strip()
    return number_key(m.group(1)), title[m.end():].strip()


def _words(title: str | None) -> set[str]:
    return {w for w in _WORD.findall((title or "").lower()) if w not in _STOP}


def real_title(title: str | None, number: str) -> bool:
    """False for empty titles and placeholders like 'Episode 7'."""
    words = _words(title)
    return bool(words - {"episode", "ep", number})


def titles_agree(ours: str | None, theirs: str | None, number: str) -> bool:
    """True unless both titles are real and clearly different."""
    if not (real_title(ours, number) and real_title(theirs, number)):
        return True
    a, b = _words(ours), _words(theirs)
    shared = len(a & b)
    return shared / min(len(a), len(b)) >= 0.5


class EpisodeStills:
    def __init__(self, anilist: AniListClient, cache: Cache | None = None,
                 kitsu_fetch: Fetch = _kitsu_fetch, anizip_fetch: Fetch = _anizip_fetch) -> None:
        self.anilist = anilist
        self.cache = cache
        self.kitsu_fetch = kitsu_fetch
        self.anizip_fetch = anizip_fetch

    def for_episodes(self, anilist_id: int | None, mal_id: int | None,
                     episodes: Iterable[tuple[str, str | None]]) -> dict[str, str]:
        """Still URL per episode number, for the given (number, title) pairs. Never raises."""
        wanted = {}
        for number, title in episodes:
            key = number_key(number)
            if key:
                wanted[key] = (number, title)
        if not wanted:
            return {}
        found: dict[str, str] = {}

        def take(candidates: dict[str, tuple[str, str | None]]) -> None:
            for key, (url, title) in candidates.items():
                if key in wanted and key not in found:
                    number, ours = wanted[key]
                    if titles_agree(ours, title, key):
                        found[key] = url

        if anilist_id:
            try:
                take(self._from_anilist(anilist_id))
            except (AniListError, OSError, ValueError, KeyError, TypeError):
                pass
        missing = [k for k in wanted if k not in found]
        if missing and mal_id:
            try:
                take(self._from_kitsu(mal_id, missing))
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                pass
        if anilist_id and any(k not in found for k in wanted):
            try:
                take(self._from_anizip(anilist_id))
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                pass
        return {wanted[k][0]: url for k, url in found.items()}

    # -- AniList -------------------------------------------------------------------------

    def _from_anilist(self, anilist_id: int) -> dict[str, tuple[str, str | None]]:
        out: dict[str, tuple[str, str | None]] = {}
        for title, thumb in self.anilist.streaming_episodes(anilist_id):
            number, name = parse_streaming_title(title)
            if number and _web_image(thumb) and number not in out:
                out[number] = (thumb, name)
        return out

    # -- Kitsu ---------------------------------------------------------------------------

    def _kitsu_json(self, url: str, ttl: float):
        key = "kitsu:" + url
        if self.cache is not None:
            hit = self.cache.cache_get_json(key)
            if hit is not None:
                return hit
        data = json.loads(self.kitsu_fetch(url))
        if self.cache is not None:
            self.cache.cache_put_json(key, data, ttl)
        return data

    def kitsu_id(self, mal_id: int) -> str | None:
        query = urllib.parse.urlencode({"filter[externalSite]": "myanimelist/anime",
                                        "filter[externalId]": int(mal_id), "include": "item"})
        data = self._kitsu_json(f"{KITSU_API}/mappings?{query}", TTL_KITSU_ID)
        for item in data.get("included") or []:
            if item.get("type") == "anime" and str(item.get("id", "")).isdigit():
                return str(item["id"])
        return None

    def _from_kitsu(self, mal_id: int, numbers: list[str]) -> dict[str, tuple[str, str | None]]:
        kid = self.kitsu_id(mal_id)
        if not kid:
            return {}
        offsets = sorted({(int(float(n)) - 1) // KITSU_PAGE * KITSU_PAGE for n in numbers})[:MAX_KITSU_PAGES]
        out: dict[str, tuple[str, str | None]] = {}
        for offset in offsets:
            query = urllib.parse.urlencode({"page[limit]": KITSU_PAGE, "page[offset]": offset, "sort": "number"})
            data = self._kitsu_json(f"{KITSU_API}/anime/{kid}/episodes?{query}", TTL_KITSU_EPISODES)
            for ep in data.get("data") or []:
                attrs = ep.get("attributes") or {}
                number = number_key(attrs.get("number"))
                thumb = (attrs.get("thumbnail") or {}).get("original")
                if number and _web_image(thumb) and number not in out:
                    out[number] = (thumb, attrs.get("canonicalTitle"))
        return out

    # -- ani.zip -------------------------------------------------------------------------

    def _from_anizip(self, anilist_id: int) -> dict[str, tuple[str, str | None]]:
        url = ANIZIP_API.format(id=int(anilist_id))
        key = "anizip:" + url
        data = self.cache.cache_get_json(key) if self.cache is not None else None
        if data is None:
            raw = json.loads(self.anizip_fetch(url))
            episodes = raw.get("episodes") if isinstance(raw, dict) else None
            data = {}   # keep only number -> (image, English title)
            for number, ep in (episodes or {}).items():
                if isinstance(ep, dict) and number_key(number) and _web_image(ep.get("image")):
                    title = ep.get("title") if isinstance(ep.get("title"), dict) else {}
                    data[number_key(number)] = [ep["image"], title.get("en")]
            if self.cache is not None:
                self.cache.cache_put_json(key, data, TTL_ANIZIP)
        return {number: (image, title) for number, (image, title) in data.items()}


def _web_image(url) -> bool:
    return isinstance(url, str) and url.startswith("https://") and len(url) < 2048
