"""'Because you watched …' rows for Home: AniList's community recommendations for the
shows you've spent the most time on."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from .stats import TYPICAL_EPISODE_S
from .store import Store

MAX_ROWS = 3
MIN_CARDS = 4           # a row with fewer isn't worth showing
MAX_CARDS = 12
CANDIDATES = 6          # top shows looked at (some get skipped)


@dataclass(frozen=True)
class BecauseRow:
    anilist_id: int
    title: str           # the show you watched
    picks: list           # Media, best first


def top_shows(store: Store, limit: int = CANDIDATES) -> list[tuple[int, str]]:
    """(AniList id, title) of the shows you've watched most: logged time, or finished
    episodes at a typical length for older history. Shows with no AniList match are skipped."""
    seconds: dict[str, float] = defaultdict(float)
    logged: set[tuple[str, str]] = set()
    for _day, anime_id, episode, secs in store.watch_log():
        seconds[anime_id] += secs
        logged.add((anime_id, episode))
    last: dict[str, float] = {}
    for p in store.all_progress():
        last[p.anime_id] = max(last.get(p.anime_id, 0.0), p.updated_at)
        if p.completed and (p.anime_id, p.episode) not in logged:
            seconds[p.anime_id] += p.duration or TYPICAL_EPISODE_S
    out = []
    for anime_id in sorted(seconds, key=lambda a: (-seconds[a], -last.get(a, 0.0))):
        show = store.get_show(anime_id)
        if show and show.anilist_id and seconds[anime_id] > 0:
            out.append((show.anilist_id, show.title))
        if len(out) >= limit:
            break
    return out


def because_rows(store: Store, related: Callable[[int], tuple[list, list]],
                 mine: set[int] | None = None) -> list[BecauseRow]:
    """Up to three rows. Each skips what you already have (watched or saved), other seasons
    of the same series, and anything an earlier row already shows. A show that's part of a
    series an earlier row came from doesn't get its own row (season 2 after season 1)."""
    if mine is None:
        mine = set()
        for p in store.all_progress():
            show = store.get_show(p.anime_id)
            if show and show.anilist_id:
                mine.add(show.anilist_id)
        mine |= {s.anilist_id for s in store.library() if s.anilist_id}
    rows: list[BecauseRow] = []
    shown: set[int] = set()
    franchises: set[int] = set()
    for anilist_id, title in top_shows(store):
        if anilist_id in franchises:
            continue
        try:
            rel, recs = related(anilist_id)
        except Exception:  # noqa: BLE001 - AniList trouble: no row, not an error
            continue
        family = {anilist_id, *(r.media.anilist_id for r in rel)}
        franchises |= family
        picks = [m for m in recs if m.anilist_id not in mine and m.anilist_id not in shown
                 and m.anilist_id not in family][:MAX_CARDS]
        if len(picks) < MIN_CARDS:
            continue
        shown |= {m.anilist_id for m in picks}
        rows.append(BecauseRow(anilist_id, title, picks))
        if len(rows) >= MAX_ROWS:
            break
    return rows
