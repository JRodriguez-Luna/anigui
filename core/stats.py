"""Watch statistics from the watch log (exact, AniGUI 1.3+) and watch progress (estimated).

Per episode, logged time wins. Episodes with no log (watched before 1.3, or with
ani-cli in Terminal) are estimated from their progress: the full length if
finished, the position reached if not, and a typical episode length when the
length was never known.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable

from .store import Store

TYPICAL_EPISODE_S = 24 * 60
WEEKS = 12
MAX_MATCHES = 25     # unmatched shows looked up on AniList per refresh (results are remembered)


@dataclass(frozen=True)
class ShowTime:
    anime_id: str
    title: str
    poster: str | None
    seconds: float
    episodes: int


@dataclass
class Stats:
    total_seconds: float = 0.0
    estimated_seconds: float = 0.0          # part of the total that's an estimate
    episodes: int = 0                       # finished episodes
    shows_started: int = 0
    shows_finished: int = 0
    week_seconds: float = 0.0               # this calendar week (Mon-Sun)
    month_seconds: float = 0.0              # this calendar month
    weeks: list[tuple[dt.date, float]] = field(default_factory=list)   # (Monday, seconds), oldest first
    streak_days: int = 0
    best_streak_days: int = 0
    top_genres: list[tuple[str, int]] = field(default_factory=list)  # (genre, episodes)
    top_shows: list[ShowTime] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return self.total_seconds <= 0 and self.episodes == 0


def compute(store: Store, media_for: Callable[[int], object] | None = None,
            today: dt.date | None = None, match: Callable[[str, str], object] | None = None) -> Stats:
    """`media_for(anilist_id)` returns AniList Media (for genres and episode counts), or None.
    `match(anime_id, title)` links a show that has no AniList match yet (catalog.enrich)."""
    today = today or dt.date.today()
    logged: dict[tuple[str, str], float] = defaultdict(float)
    by_day: dict[dt.date, float] = defaultdict(float)
    for day, anime_id, episode, seconds in store.watch_log():
        logged[(anime_id, episode)] += seconds
        by_day[dt.date.fromisoformat(day)] += seconds

    st = Stats()
    per_show_s: dict[str, float] = defaultdict(float)
    per_show_eps: Counter[str] = Counter()
    for p in store.all_progress():
        key = (p.anime_id, p.episode)
        if p.completed:
            st.episodes += 1
            per_show_eps[p.anime_id] += 1
        if key in logged:
            continue
        # No log for this episode: estimate it, on the day it was last touched
        if p.completed:
            seconds = p.duration or TYPICAL_EPISODE_S
        else:
            seconds = p.position or 0.0
        if seconds > 0:
            st.estimated_seconds += seconds
            per_show_s[p.anime_id] += seconds
            by_day[dt.datetime.fromtimestamp(p.updated_at).date()] += seconds
    for (anime_id, _ep), seconds in logged.items():
        per_show_s[anime_id] += seconds

    st.total_seconds = sum(per_show_s.values())
    started = set(per_show_s) | set(per_show_eps)
    st.shows_started = len(started)

    # This week, this month, last 12 weeks
    monday = today - dt.timedelta(days=today.weekday())
    first = today.replace(day=1)
    st.week_seconds = sum(s for d, s in by_day.items() if monday <= d <= today)
    st.month_seconds = sum(s for d, s in by_day.items() if first <= d <= today)
    for k in range(WEEKS - 1, -1, -1):
        start = monday - dt.timedelta(weeks=k)
        end = start + dt.timedelta(days=6)
        st.weeks.append((start, sum(s for d, s in by_day.items() if start <= d <= end)))

    # Streaks: consecutive days with any watching. Today not watched yet doesn't break it.
    days = {d for d, s in by_day.items() if s >= 60}
    run, cursor = 0, today if today in days else today - dt.timedelta(days=1)
    while cursor in days:
        run += 1
        cursor -= dt.timedelta(days=1)
    st.streak_days = run
    best = cur = 0
    prev = None
    for d in sorted(days):
        cur = cur + 1 if prev and d - prev == dt.timedelta(days=1) else 1
        best, prev = max(best, cur), d
    st.best_streak_days = best

    # Shows: most watched, finished, genres
    shows = {anime_id: store.get_show(anime_id) for anime_id in started}
    genres: Counter[str] = Counter()
    matches = 0
    for anime_id, show in shows.items():
        if show is None:
            continue
        try:
            if show.anilist_id and media_for is not None:
                media = media_for(show.anilist_id)
            elif match is not None and matches < MAX_MATCHES:
                matches += 1
                media = match(anime_id, show.title)
            else:
                media = None
        except Exception:  # noqa: BLE001 - AniList down: stats without genres
            media = None
        if media is None:
            continue
        weight = per_show_eps[anime_id] or (1 if per_show_s[anime_id] else 0)
        for g in media.genres:
            genres[g] += weight
        if media.status == "FINISHED" and media.episodes and per_show_eps[anime_id] >= media.episodes:
            st.shows_finished += 1
    st.top_genres = genres.most_common(6)
    ranked = sorted(started, key=lambda a: -per_show_s[a])
    st.top_shows = [ShowTime(a, shows[a].title if shows[a] else a, shows[a].poster if shows[a] else None,
                             per_show_s[a], per_show_eps[a]) for a in ranked[:8] if per_show_s[a] > 0]
    return st


def hours_text(seconds: float) -> str:
    """'3h 20m', '45m', '0m'."""
    minutes = int(round(seconds / 60))
    h, m = divmod(minutes, 60)
    if h >= 100:
        return f"{h}h"
    return f"{h}h {m}m" if h else f"{m}m"
