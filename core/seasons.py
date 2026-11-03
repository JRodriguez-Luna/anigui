"""A series' seasons, in order, from AniList's prequel/sequel links.

AniList lists each season as its own entry, linked PREQUEL <-> SEQUEL. Starting from any
entry (a season, or even a movie of the series), walk back to the first season and then
forward to the last. TV/ONA entries on that path are the seasons; movies, OVAs and
specials on it or hanging off it (side stories) are listed separately so they don't
break the numbering. Each step is one AniList request, cached like the Related row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .anilist import Media, Related

SEASON_FORMATS = ("TV", "TV_SHORT", "ONA")
EXTRA_FORMATS = ("MOVIE", "OVA", "SPECIAL", "ONA", "TV_SHORT")
EXTRA_RELATIONS = ("PREQUEL", "SEQUEL", "SIDE_STORY", "PARENT", "SUMMARY")
MAX_LOOKUPS = 24          # AniList requests for one series (each cached)

RelatedFn = Callable[[int], "list[Related]"]


@dataclass(frozen=True)
class Season:
    media: Media
    number: int            # 1-based position in the series
    label: str             # "Season 2", "Shippuden", "Final Season Part 2"


@dataclass(frozen=True)
class Series:
    seasons: tuple[Season, ...] = ()
    extras: tuple[Media, ...] = ()          # movies, OVAs, specials (by year)
    complete: bool = True                   # False: stopped early (lookup limit, AniList down)

    def find(self, anilist_id: int) -> Season | None:
        return next((s for s in self.seasons if s.media.anilist_id == anilist_id), None)

    def after(self, anilist_id: int) -> Season | None:
        """The season that follows this one, if any."""
        for i, s in enumerate(self.seasons[:-1]):
            if s.media.anilist_id == anilist_id:
                return self.seasons[i + 1]
        return None

    @property
    def worth_showing(self) -> bool:
        return len(self.seasons) >= 2 or (len(self.seasons) == 1 and bool(self.extras))


def _is_season(m: Media) -> bool:
    return (m.format or "") in SEASON_FORMATS


@dataclass
class _Walker:
    related: RelatedFn
    edges: dict[int, list[Related]] = field(default_factory=dict)
    complete: bool = True

    def links(self, media: Media) -> list[Related]:
        if media.anilist_id not in self.edges:
            if len(self.edges) >= MAX_LOOKUPS:
                self.complete = False
                return []
            try:
                self.edges[media.anilist_id] = list(self.related(media.anilist_id))
            except Exception:  # noqa: BLE001 - AniList down: show what we have
                self.complete = False
                return []
        return self.edges[media.anilist_id]

    def step(self, media: Media, relation: str, seen: set[int]) -> Media | None:
        """The PREQUEL or SEQUEL to follow: a season if there is one (by year), else a movie
        or special in between (Demon Slayer's Mugen Train sits between two seasons)."""
        options = [r.media for r in self.links(media) if r.relation == relation and r.media.anilist_id not in seen
                   and (r.media.format or "") != "MUSIC"]
        if not options:
            return None
        backward = relation == "PREQUEL"
        options.sort(key=lambda m: (not _is_season(m), -(m.year or 0) if backward else (m.year or 9999)))
        return options[0]


def build(start: Media, related: RelatedFn) -> Series:
    w = _Walker(related)
    first = start
    if not _is_season(start):
        # A movie or OVA page: start from the season it belongs to (its prequel, sequel or
        # main story), so the row still shows the whole series.
        links = [r for r in w.links(start) if _is_season(r.media) and r.relation in ("PREQUEL", "SEQUEL", "PARENT", "SIDE_STORY")]
        links.sort(key=lambda r: ("PREQUEL", "PARENT", "SEQUEL", "SIDE_STORY").index(r.relation))
        if links:
            first = links[0].media
    seen = {first.anilist_id}
    while (prev := w.step(first, "PREQUEL", seen)) is not None:
        seen.add(prev.anilist_id)
        first = prev
    path = [first]
    seen = {first.anilist_id}
    cur = first
    while (nxt := w.step(cur, "SEQUEL", seen)) is not None:
        seen.add(nxt.anilist_id)
        path.append(nxt)
        cur = nxt
    if start.anilist_id not in seen:       # the walk forward took another branch: keep the page's show
        path.append(start)
        seen.add(start.anilist_id)

    seasons = [m for m in path if _is_season(m)]
    extras: dict[int, Media] = {m.anilist_id: m for m in path if not _is_season(m) and (m.format or "") in EXTRA_FORMATS}
    for m in path:
        for r in w.edges.get(m.anilist_id, []):
            x = r.media
            if (x.anilist_id not in seen and r.relation in EXTRA_RELATIONS
                    and (x.format or "") in EXTRA_FORMATS and not (_is_season(x) and r.relation in ("PREQUEL", "SEQUEL"))):
                extras.setdefault(x.anilist_id, x)
    labels = season_labels_for(seasons)
    return Series(
        seasons=tuple(Season(m, i + 1, label) for i, (m, label) in enumerate(zip(seasons, labels))),
        extras=tuple(sorted(extras.values(), key=lambda m: (m.year or 9999, m.display_title))),
        complete=w.complete,
    )


_ORDINAL = re.compile(r"^(\d+)(?:st|nd|rd|th)\s+season$", re.I)        # '3rd Season' -> 'Season 3'


def _norm(words: list[str]) -> list[str]:
    return [w.strip(":-–—,.").lower() for w in words]


def season_labels_for(seasons: list[Media]) -> list[str]:
    """Labels from whichever title language the seasons share best. AniList often has
    no English title for a new season ('Sousou no Frieren 3rd Season'), so try the
    first season's English and romaji names as the shared part and keep the better fit."""
    if len(seasons) <= 1:
        return ["Season 1"] * len(seasons)
    first = seasons[0]
    best: list[str] | None = None
    best_hits = -1
    for base in dict.fromkeys(t for t in (first.title_english, first.title_romaji) if t):
        prefix = _norm(base.split())
        labels, hits = [], 0
        for i, m in enumerate(seasons):
            label = None
            for t in (m.title_english, m.title_romaji, *m.synonyms):
                words = (t or "").split()
                if t and _norm(words[:len(prefix)]) == prefix:
                    label = _tidy(" ".join(words[len(prefix):])) or ("Season 1" if i == 0 else None)
                    if label:
                        break
            if label:
                hits += 1
            labels.append(label or m.display_title)
        if hits > best_hits:
            best, best_hits = labels, hits
    if best is None or best_hits < 2:
        return season_labels([m.display_title for m in seasons])
    return best


def _tidy(rest: str) -> str:
    rest = _SEP.sub("", rest)
    if rest.upper() in _ROMAN:                       # 'Mob Psycho 100 II' -> 'Season 2'
        return f"Season {_ROMAN.index(rest.upper()) + 1}"
    m = _ORDINAL.match(rest)
    if m:
        return f"Season {int(m.group(1))}"
    if rest.isupper() and len(rest) > 3:              # 'FINAL SEASON' -> 'Final Season'
        return rest.title()
    return rest


_ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")
_SEP = re.compile(r"^[\s:\-–—,.]+|[\s:\-–—,.]+$")


def season_labels(titles: list[str]) -> list[str]:
    """Short names: the words every title shares are dropped. 'My Hero Academia Season 2'
    -> 'Season 2', and the first one (nothing left) -> 'Season 1'. Titles with nothing in
    common keep their full names."""
    if not titles:
        return []
    if len(titles) == 1:
        return ["Season 1"]
    split = [t.split() for t in titles]
    shared = 0
    for words in zip(*split):
        if len({w.strip(":-–—,.").lower() for w in words}) != 1:
            break
        shared += 1
    if shared == 0:
        return list(titles)
    labels = []
    for i, words in enumerate(split):
        rest = _tidy(" ".join(words[shared:]))
        labels.append(rest or ("Season 1" if i == 0 else titles[i]))
    return labels
