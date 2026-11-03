"""Which episodes are filler, from Anime Filler List (animefillerlist.com).

Anime Filler List is the community's filler guide: for each long-running show it marks
every episode as Manga Canon, Mixed Canon/Filler, Filler or Anime Canon. AniGUI treats
only "Filler" as filler; mixed and anime-canon episodes have story in them.

Shows are matched by exact title (any of AniList's titles or hianime's), so "Naruto"
never picks up "Naruto Shippuden", and a "Season 2" entry never borrows season 1's
numbering. No match means no badges, never a guess. Network trouble never raises.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from . import http
from .stills import number_key

SITE = "https://www.animefillerlist.com"
SHOWS_URL = SITE + "/shows"
SHOW_URL = SITE + "/shows/{slug}"
TTL_SHOWS = 7 * 24 * 3600
TTL_SHOW = 2 * 24 * 3600          # airing shows (One Piece) get new episodes weekly

FILLER, RECAP = "filler", "recap"

_SHOW_LINK = re.compile(r'<a href="/shows/([A-Za-z0-9%\-]+)"[^<>]*>([^<]{1,200})</a>')
_EPISODE_ROW = re.compile(r'<tr class="([^"]*)"[^<>]*\bid="eps-(\d+(?:\.\d+)?)"')
_NOT_WORD = re.compile(r"[^a-z0-9]+")

Fetch = Callable[[str], "http.Response"]


class Cache:  # what Store provides
    def cache_get_json(self, key: str) -> Any | None: ...
    def cache_put_json(self, key: str, value: Any, ttl: float) -> None: ...


def _fetch(url: str) -> http.Response:
    return http.request(url, headers={"Accept": "text/html"}, timeout=20)


def normalize(title: str) -> str:
    """'Naruto: Shippuden' -> 'naruto shippuden'."""
    return _NOT_WORD.sub(" ", html.unescape(title).lower()).strip()


def parse_shows(page: str) -> dict[str, str]:
    """{normalized name: slug} from the show index. 'Bleach: TYBW (Sennen Kessen-hen)' gives
    both the full name and each half. A show's own name always wins over another show's
    half: 'One Pace (One Piece)' is a fan edit, so "One Piece" must stay One Piece."""
    links = [(slug, html.unescape(name).strip()) for slug, name in _SHOW_LINK.findall(page)]
    names: dict[str, str] = {}
    for slug, name in links:
        key = normalize(name)
        if key and key not in names:
            names[key] = slug
    for slug, name in links:
        main, _, alt = name.partition(" (")
        for candidate in (main, alt.rstrip(")")):
            key = normalize(candidate)
            if key and key not in names:
                names[key] = slug
    return names


def parse_episodes(page: str) -> dict[str, str]:
    """{episode number: "filler"} for the episodes marked Filler."""
    kinds: dict[str, str] = {}
    for classes, number in _EPISODE_ROW.findall(page):
        key = number_key(number)
        if key and classes.split()[:1] == ["filler"]:
            kinds[key] = FILLER
    return kinds


@dataclass(frozen=True)
class FillerInfo:
    kinds: dict[str, str] = field(default_factory=dict)   # episode number -> "filler" | "recap"
    complete: bool = False                                # the show's whole list was read

    def kind(self, number: str) -> str | None:
        key = number_key(number)
        return self.kinds.get(key) if key else None

    def skippable(self, numbers: list[str]) -> set[str]:
        """The episodes (as given) that Skip / Hide fillers leaves out."""
        return {n for n in numbers if self.kind(n)}

    def summary(self, numbers: list[str]) -> str | None:
        """'92 of 220 episodes are filler', or None when there's nothing to say."""
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
    def __init__(self, cache: Cache | None = None, fetch: Fetch = _fetch) -> None:
        self.cache = cache
        self.fetch = fetch

    def for_titles(self, titles: Iterable[str | None]) -> FillerInfo:
        """Filler info for the show with one of these titles (best title first)."""
        try:
            slug = self.find_show(titles)
            if not slug:
                return FillerInfo()
            page = self._get(SHOW_URL.format(slug=slug), TTL_SHOW)
            if page is None:
                return FillerInfo()
            return FillerInfo(parse_episodes(page), complete=bool(_EPISODE_ROW.search(page)))
        except (OSError, ValueError, TypeError):
            return FillerInfo()

    def find_show(self, titles: Iterable[str | None]) -> str | None:
        wanted = [normalize(t) for t in titles if t]
        if not any(wanted):
            return None
        index = self._get(SHOWS_URL, TTL_SHOWS)
        if index is None:
            return None
        shows = parse_shows(index)
        for title in wanted:
            slug = shows.get(title)
            if slug:
                return urllib.parse.quote(urllib.parse.unquote(slug), safe="-")
        return None

    def _get(self, url: str, ttl: float) -> str | None:
        key = "afl:" + url
        if self.cache is not None:
            hit = self.cache.cache_get_json(key)
            if hit is not None:
                return hit
        try:
            resp = self.fetch(url)
        except OSError:
            return None
        if resp.status != 200:
            return None
        text = resp.body.decode("utf-8", "replace")
        pattern = _SHOW_LINK if url == SHOWS_URL else _EPISODE_ROW
        text = "\n".join(m.group(0) for m in pattern.finditer(text))   # keep only what's parsed
        if self.cache is not None and text:
            self.cache.cache_put_json(key, text, ttl)
        return text
