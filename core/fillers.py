"""Which episodes are filler or recap, from MyAnimeList (through Jikan's public API).

MyAnimeList marks episodes as filler (not from the source manga) or recap (mostly
earlier scenes). Coverage is good for the long-running shows where it matters (Naruto,
Bleach, One Piece…) and empty for most seasonal shows, which have no filler anyway.
No data means no badges, never a guess. Network trouble never raises.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import http
from .stills import number_key

JIKAN_EPISODES = "https://api.jikan.moe/v4/anime/{mal}/episodes?page={page}"
MAX_PAGES = 20                    # 100 episodes each: enough for One Piece
PAGE_GAP_S = 0.4                  # Jikan allows 3 requests a second
TTL_FULL_PAGE = 30 * 24 * 3600    # an older, full page of episodes rarely changes
TTL_LAST_PAGE = 24 * 3600         # the newest page fills in as a show airs

FILLER, RECAP = "filler", "recap"

Fetch = Callable[[str], "http.Response"]


class Cache:  # what Store provides
    def cache_get_json(self, key: str) -> Any | None: ...
    def cache_put_json(self, key: str, value: Any, ttl: float) -> None: ...


def _fetch(url: str) -> http.Response:
    return http.request(url, headers={"Accept": "application/json"}, timeout=20)


@dataclass(frozen=True)
class FillerInfo:
    kinds: dict[str, str] = field(default_factory=dict)   # episode number -> "filler" | "recap"
    complete: bool = False                                # every page loaded (counts are exact)

    def kind(self, number: str) -> str | None:
        key = number_key(number)
        return self.kinds.get(key) if key else None

    def skippable(self, numbers: list[str]) -> set[str]:
        """The episodes (as given) that Skip / Hide fillers leaves out: fillers and recaps."""
        return {n for n in numbers if self.kind(n)}

    def summary(self, numbers: list[str]) -> str | None:
        """'92 of 220 episodes are filler · 4 recaps', or None when there's nothing to say."""
        if not self.complete or not numbers:
            return None
        fillers = sum(1 for n in numbers if self.kind(n) == FILLER)
        recaps = sum(1 for n in numbers if self.kind(n) == RECAP)
        if not fillers and not recaps:
            return None
        parts = []
        if fillers:
            parts.append(f"{fillers:,} of {len(numbers):,} episodes {'is' if fillers == 1 else 'are'} filler")
        if recaps:
            parts.append(f"{recaps} recap{'' if recaps == 1 else 's'}")
        return " · ".join(parts)


class FillerGuide:
    def __init__(self, cache: Cache | None = None, fetch: Fetch = _fetch,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.cache = cache
        self.fetch = fetch
        self.sleep = sleep

    def for_mal(self, mal_id: int | None) -> FillerInfo:
        if not mal_id:
            return FillerInfo()
        kinds: dict[str, str] = {}
        for page in range(1, MAX_PAGES + 1):
            data = self._page(int(mal_id), page)
            if data is None:
                return FillerInfo(kinds, complete=False)
            for ep in data.get("data") or []:
                if not isinstance(ep, dict):
                    continue
                key = number_key(ep.get("mal_id"))
                if key and ep.get("filler") is True:
                    kinds[key] = FILLER
                elif key and ep.get("recap") is True:
                    kinds[key] = RECAP
            if not (data.get("pagination") or {}).get("has_next_page"):
                return FillerInfo(kinds, complete=True)
        return FillerInfo(kinds, complete=False)

    def _page(self, mal_id: int, page: int) -> dict | None:
        url = JIKAN_EPISODES.format(mal=mal_id, page=page)
        key = "jikan:" + url
        if self.cache is not None:
            hit = self.cache.cache_get_json(key)
            if hit is not None:
                return hit
        if page > 1:
            self.sleep(PAGE_GAP_S)
        for attempt in range(2):
            try:
                resp = self.fetch(url)
            except OSError:
                return None
            if resp.status == 429 and attempt == 0:   # rate limited: one polite retry
                self.sleep(1.5)
                continue
            break
        if resp.status == 404:
            data: dict = {"data": [], "pagination": {"has_next_page": False}}   # not on MAL: no fillers
        elif resp.status != 200:
            return None
        else:
            try:
                data = json.loads(resp.body or b"{}")
            except ValueError:
                return None
            if not isinstance(data, dict):
                return None
        more = bool((data.get("pagination") or {}).get("has_next_page"))
        data = {"data": [{k: ep.get(k) for k in ("mal_id", "filler", "recap")}   # keep only what's used
                         for ep in data.get("data") or [] if isinstance(ep, dict)],
                "pagination": {"has_next_page": more}}
        if self.cache is not None:
            self.cache.cache_put_json(key, data, TTL_FULL_PAGE if more else TTL_LAST_PAGE)
        return data
