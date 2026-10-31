"""The airing calendar: a week of episodes from AniList, in local time, with whether
each one can be watched yet.

"Watchable" means hianime lists the episode. For followed shows that aired this week,
the hianime episode list is checked (a few shows per refresh; the newest-episode
record it fills in is the same one the new-episode alerts use).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from .alerts import followed
from .anilist import Airing
from .catalog import Catalog
from .store import Store, episode_key

MAX_MATCHES = 10         # unmatched followed shows linked to AniList per refresh
TRENDING_COUNT = 30      # Trending: AniList's top airing shows by recent activity
WEEK_S = 7 * 86400
MAX_HIANIME_CHECKS = 12  # aired episodes of followed shows checked on hianime per refresh

UPCOMING, AVAILABLE, AIRED, PENDING = "upcoming", "available", "aired", "pending"


@dataclass(frozen=True)
class Entry:
    media: object            # AniList Media
    episode: int
    when: dt.datetime        # local time
    anime_id: str | None     # the hianime show, when AniGUI knows it
    in_library: bool
    state: str               # upcoming | available (on hianime) | pending (aired, not on hianime yet) | aired (unknown)
    rank: int | None = None  # Trending position, 1 = hottest

    @property
    def title(self) -> str:
        return self.media.display_title


@dataclass(frozen=True)
class Week:
    monday: dt.date
    days: list[list[Entry]]   # Monday..Sunday

    @property
    def count(self) -> int:
        return sum(len(d) for d in self.days)


def week_start(today: dt.date | None = None, offset: int = 0) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=today.weekday()) + dt.timedelta(weeks=offset)


def _bounds(monday: dt.date) -> tuple[int, int]:
    start = dt.datetime.combine(monday, dt.time.min).astimezone()   # local midnight
    end = start + dt.timedelta(days=7)
    return int(start.timestamp()), int(end.timestamp())


def build(store: Store, catalog: Catalog, *, mine: bool = True, scope: str = "library",
          monday: dt.date | None = None, now: dt.datetime | None = None) -> Week:
    monday = monday or week_start()
    now = now or dt.datetime.now().astimezone()
    start, end = _bounds(monday)

    shows = followed(store, scope)
    ids: list[int] = []
    matches = 0
    for show in shows:
        if show.anilist_id:
            ids.append(show.anilist_id)
        elif matches < MAX_MATCHES:
            matches += 1
            try:
                media = catalog.enrich(show.anime_id, show.title, show.poster)
            except Exception:  # noqa: BLE001 - AniList down: try next refresh
                media = None
            if media:
                ids.append(media.anilist_id)
    followed_ids = set(ids)

    if mine:
        airings = catalog.anilist.schedule(start, end, ids)
        ranks: dict[int, int] = {}
    else:
        trending = catalog.anilist.browse(status="RELEASING", sort="TRENDING_DESC", per_page=TRENDING_COUNT)
        airings = weekly_airings(trending, start, end)
        ranks = {m.anilist_id: i for i, m in enumerate(trending, start=1)}

    checks = 0
    days: list[list[Entry]] = [[] for _ in range(7)]
    for a in airings:
        when = dt.datetime.fromtimestamp(a.airing_at).astimezone()
        index = (when.date() - monday).days
        if not 0 <= index < 7:
            continue
        show = store.find_by_anilist(a.media.anilist_id)
        anime_id = show.anime_id if show else None
        state = UPCOMING
        if when <= now:
            state = AIRED
            if anime_id and a.media.anilist_id in followed_ids:
                latest = store.watched_latest(anime_id)
                if (latest is None or episode_key(latest) < a.episode) and checks < MAX_HIANIME_CHECKS:
                    checks += 1
                    try:
                        eps = catalog.episodes(anime_id)
                    except Exception:  # noqa: BLE001 - hianime unreachable: state stays "aired"
                        eps = []
                    if eps:
                        newest = max(eps, key=lambda e: episode_key(e.number)).number
                        store.set_latest(anime_id, newest)
                        latest = store.watched_latest(anime_id)
                if latest is not None:
                    state = AVAILABLE if episode_key(latest) >= a.episode else PENDING
        days[index].append(Entry(a.media, a.episode, when, anime_id, bool(show and show.in_library), state,
                                 ranks.get(a.media.anilist_id)))
    for day in days:
        day.sort(key=lambda e: (e.rank or 0, e.when))
    return Week(monday, days)


def weekly_airings(shows, start: int, end: int) -> list[Airing]:
    """Where each show's episode falls in [start, end), from its next airing time.

    One trending request carries every show's next episode; weekly shows air at the
    same time each week, so stepping by 7 days places this week's episode (or an
    earlier or later week's). Shows with no known next episode are left out.
    """
    found = []
    for m in shows:
        if not m.next_airing_at or not m.next_episode:
            continue
        steps = math.ceil((start - m.next_airing_at) / WEEK_S)
        at = m.next_airing_at + steps * WEEK_S
        episode = m.next_episode + steps
        if at < end and episode >= 1 and (not m.episodes or episode <= m.episodes):
            found.append(Airing(m, episode, at))
    return found
