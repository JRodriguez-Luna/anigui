"""Wrapped (2.0): your year in anime, worked out on this Mac from what AniGUI already keeps.
Nothing is sent anywhere to make it."""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable

from .store import Store


@dataclass(frozen=True)
class TopShow:
    anime_id: str
    title: str
    poster: str | None
    seconds: float
    episodes: int


@dataclass
class Wrapped:
    year: int
    seconds: float = 0.0
    episodes: int = 0
    shows: int = 0
    days_watched: int = 0
    top: list[TopShow] = field(default_factory=list)
    genres: list[tuple[str, int]] = field(default_factory=list)
    longest_streak: int = 0
    busiest_day: tuple[dt.date, float] | None = None
    busiest_month: tuple[int, float] | None = None
    hours_of_day: Counter = field(default_factory=Counter)   # hour -> episodes finished then
    first_show: str | None = None
    rated: int = 0
    favorite: tuple[str, str | None, int] | None = None       # (title, poster, rating)
    lists_made: int = 0

    @property
    def empty(self) -> bool:
        return self.seconds < 600

    @property
    def hours(self) -> int:
        return round(self.seconds / 3600)

    @property
    def per_day(self) -> float:
        return self.episodes / self.days_watched if self.days_watched else 0.0

    @property
    def kind(self) -> tuple[str, str]:
        """(what kind of watcher, why), for the last slide."""
        night = sum(n for h, n in self.hours_of_day.items() if h >= 22 or h < 4)
        total = sum(self.hours_of_day.values()) or 1
        if night / total >= 0.4:
            return "Night owl", "Most of your episodes ended after 10 PM."
        if self.per_day >= 4:
            return "Binge-watcher", f"About {self.per_day:.0f} episodes on the days you watched."
        if self.longest_streak >= 14:
            return "Devoted", f"{self.longest_streak} days in a row, at your best."
        if len(self.top) >= 5 and self.top[0].seconds < self.seconds * 0.3:
            return "Explorer", "You spread your time across lots of shows."
        if self.top and self.top[0].seconds >= self.seconds * 0.5:
            return "Loyal", f"Half your time went to {self.top[0].title}."
        return "Steady", "A little anime, often. Nice."


def compute(store: Store, year: int | None = None, media_for: Callable[[int], object] | None = None,
            today: dt.date | None = None) -> Wrapped:
    today = today or dt.date.today()
    year = year or today.year
    w = Wrapped(year)
    per_show: dict[str, float] = defaultdict(float)
    per_show_eps: Counter[str] = Counter()
    by_day: dict[dt.date, float] = defaultdict(float)
    first: tuple[str, str] | None = None
    for day, anime_id, _ep, seconds in store.watch_log():
        d = dt.date.fromisoformat(day)
        if d.year != year:
            continue
        per_show[anime_id] += seconds
        by_day[d] += seconds
        if first is None or day < first[0]:
            first = (day, anime_id)
    for p in store.all_progress():
        when = dt.datetime.fromtimestamp(p.updated_at)
        if p.completed and when.year == year:
            w.episodes += 1
            per_show_eps[p.anime_id] += 1
            w.hours_of_day[when.hour] += 1
    w.seconds = sum(per_show.values())
    w.shows = len(set(per_show) | set(per_show_eps))
    days = sorted(d for d, s in by_day.items() if s >= 60)
    w.days_watched = len(days)
    best = cur = 0
    prev = None
    for d in days:
        cur = cur + 1 if prev and d - prev == dt.timedelta(days=1) else 1
        best, prev = max(best, cur), d
    w.longest_streak = best
    if by_day:
        d, s = max(by_day.items(), key=lambda kv: kv[1])
        w.busiest_day = (d, s)
        months: dict[int, float] = defaultdict(float)
        for d, s in by_day.items():
            months[d.month] += s
        w.busiest_month = max(months.items(), key=lambda kv: kv[1])
    shows = {a: store.get_show(a) for a in set(per_show) | set(per_show_eps)}
    ranked = sorted(per_show, key=lambda a: -per_show[a])
    w.top = [TopShow(a, shows[a].title, shows[a].poster, per_show[a], per_show_eps[a])
             for a in ranked[:5] if shows.get(a)]
    if first and shows.get(first[1]):
        w.first_show = shows[first[1]].title
    genres: Counter[str] = Counter()
    if media_for is not None:
        for a, show in shows.items():
            if show is None or not show.anilist_id:
                continue
            try:
                media = media_for(show.anilist_id)
            except Exception:  # noqa: BLE001 (no genres when AniList is away)
                media = None
            for g in getattr(media, "genres", ()) or ():
                genres[g] += per_show_eps[a] or 1
    w.genres = genres.most_common(3)
    # Yours: ratings and lists made this year
    start = dt.datetime(year, 1, 1).timestamp()
    end = dt.datetime(year + 1, 1, 1).timestamp()
    c = store._conn()
    w.rated = c.execute("SELECT COUNT(DISTINCT anime_id) FROM events WHERE kind = 'rated' AND at >= ? AND at < ?",
                        (start, end)).fetchone()[0]
    w.lists_made = c.execute("SELECT COUNT(*) FROM lists WHERE created_at >= ? AND created_at < ?",
                             (start, end)).fetchone()[0]
    rated = store.rated()
    if rated:
        show, r = rated[0]
        w.favorite = (show.title, show.poster, r)
    return w
