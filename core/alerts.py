"""New-episode checks for the shows the user follows.

AniList says when an episode has aired; hianime decides when it's actually
watchable (usually a few hours later, dubs later still). So AniList picks which
shows are due, and only those get their hianime episode list fetched.
"""

from __future__ import annotations

from .catalog import Catalog
from .store import NewEpisodes, Show, Store, episode_key

MAX_LINK_LOOKUPS = 8   # unmatched shows get an AniList match attempt, a few per check


def followed(store: Store, scope: str) -> list[Show]:
    shows = {s.anime_id: s for s in store.library()}
    if scope == "library+continue":
        for item in store.continue_watching(limit=40):
            shows.setdefault(item.show.anime_id, item.show)
    return list(shows.values())


def expected_episode(media) -> int | None:
    """The newest episode that has aired according to AniList."""
    if media is None or media.status in (None, "NOT_YET_RELEASED", "CANCELLED"):
        return None
    if media.next_episode:
        return media.next_episode - 1 or None
    return media.episodes


def check(store: Store, catalog: Catalog, scope: str = "library") -> list[NewEpisodes]:
    """Refresh the newest episode of every followed show that's due. Returns the
    new episodes nobody has been notified about yet (and marks them notified)."""
    shows = followed(store, scope)
    linked: list[Show] = []
    lookups = 0
    for show in shows:
        if show.anilist_id:
            linked.append(show)
        elif lookups < MAX_LINK_LOOKUPS:
            lookups += 1
            try:
                media = catalog.enrich(show.anime_id, show.title, show.poster)
            except Exception:  # noqa: BLE001 - AniList down: try again next time
                media = None
            if media:
                linked.append(store.get_show(show.anime_id) or show)

    airing = catalog.anilist.airing([s.anilist_id for s in linked if s.anilist_id])
    for show in linked:
        expected = expected_episode(airing.get(show.anilist_id))
        if expected is None:
            continue
        known = store.watched_latest(show.anime_id)
        if known is not None and episode_key(known) >= expected:
            continue  # nothing new has aired since we last looked
        try:
            episodes = catalog.episodes(show.anime_id)
        except Exception:  # noqa: BLE001 - hianime unreachable: try again next time
            continue
        if episodes:
            newest = max(episodes, key=lambda e: episode_key(e.number)).number
            store.set_latest(show.anime_id, newest)
    return store.take_unnotified()
