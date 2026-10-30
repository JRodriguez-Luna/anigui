"""Intro, ending and recap times from AniSkip (https://aniskip.com), a community database.

The same service ani-skip uses, called directly: AniGUI does the skipping itself
through the player's control socket, so it works with IINA and mpv and needs no
mpv script. Lookups are by MyAnimeList id and episode number.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from . import http

API = "https://api.aniskip.com/v2/skip-times/{mal_id}/{episode}"
TYPES = ("op", "ed", "mixed-op", "mixed-ed", "recap")
KIND = {"op": "intro", "mixed-op": "intro", "ed": "ending", "mixed-ed": "ending", "recap": "recap"}
TTL = 7 * 24 * 3600
MISS_TTL = 12 * 3600            # nobody has timed it yet; ask again later
LENGTH_TOLERANCE_S = 30.0       # times submitted for a different cut of the episode don't line up


@dataclass(frozen=True)
class Segment:
    kind: str        # intro | ending | recap
    start: float
    end: float

    def contains(self, position: float) -> bool:
        # The last second is left alone, so a seek that lands just short doesn't loop.
        return self.start <= position < self.end - 1.0


Fetch = Callable[[str], http.Response]


def _fetch(url: str) -> http.Response:
    return http.request(url, headers={"Accept": "application/json"}, timeout=10)


def episode_number(episode: str) -> int | None:
    """AniSkip only knows whole episodes."""
    try:
        value = float(episode)
    except ValueError:
        return None
    return int(value) if value.is_integer() and value > 0 else None


def parse(body: bytes | str, duration: float | None = None) -> list[Segment]:
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return []
    segments: list[Segment] = []
    for item in data.get("results") or []:
        kind = KIND.get(item.get("skipType", ""))
        interval = item.get("interval") or {}
        try:
            start, end = float(interval["startTime"]), float(interval["endTime"])
        except (KeyError, TypeError, ValueError):
            continue
        length = item.get("episodeLength")
        if duration and isinstance(length, (int, float)) and length > 0 and abs(length - duration) > LENGTH_TOLERANCE_S:
            continue
        if kind and end - start >= 5:
            segments.append(Segment(kind, start, end))
    # One segment per kind: the first (AniSkip orders by votes)
    seen: dict[str, Segment] = {}
    for seg in segments:
        seen.setdefault(seg.kind, seg)
    return sorted(seen.values(), key=lambda s: s.start)


def skip_times(mal_id: int, episode: str, duration: float | None = None, *, cache=None,
               fetch: Fetch = _fetch) -> list[Segment]:
    """Segments for one episode, or [] when there's nothing (or AniSkip is unreachable)."""
    number = episode_number(episode)
    if not mal_id or number is None:
        return []
    key = f"aniskip:{mal_id}:{number}"
    cached = cache.cache_get(key) if cache is not None else None
    if cached is None:
        # episodeLength=0 returns every submission; ones for a different cut are filtered in parse()
        query = "&".join(f"types[]={t}" for t in TYPES) + "&episodeLength=0"
        try:
            resp = fetch(API.format(mal_id=mal_id, episode=number) + "?" + query)
        except OSError:
            return []
        if resp.status == 404:
            if cache is not None:
                cache.cache_put(key, "{}", MISS_TTL)
            return []
        if resp.status != 200:
            return []
        cached = resp.body.decode("utf-8", "replace")
        if cache is not None:
            cache.cache_put(key, cached, TTL if parse(cached) else MISS_TTL)
    return parse(cached, duration)
