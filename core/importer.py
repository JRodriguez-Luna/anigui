"""Bring your lists over from AniList or MyAnimeList, once, without signing in (2.0).

AniList: your public list, by username (AniList shows public lists to anyone; nothing to log
into). MyAnimeList: the export file from myanimelist.net/panel.php?go=export (.xml or .xml.gz).

Each show is found on hianime the same way opening it from Home does. Then your status becomes
a list (Watching, Completed, Plan to watch, On hold, Dropped), your score becomes your rating,
and your progress marks those episodes watched. Nothing is sent back; AniGUI never writes to
your AniList or MAL.
"""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .anilist import _FIELDS, AniListClient, Media

STATUS_LISTS = {               # status -> (list name, emoji)
    "CURRENT": ("Watching", "▶️"),
    "REPEATING": ("Watching", "▶️"),
    "COMPLETED": ("Completed", "✅"),
    "PLANNING": ("Plan to watch", "📌"),
    "PAUSED": ("On hold", "⏸"),
    "DROPPED": ("Dropped", "🗑"),
}
MAL_STATUS = {"Watching": "CURRENT", "Completed": "COMPLETED", "On-Hold": "PAUSED", "Dropped": "DROPPED",
              "Plan to Watch": "PLANNING", "1": "CURRENT", "2": "COMPLETED", "3": "PAUSED", "4": "DROPPED",
              "6": "PLANNING"}

Q_USER_LIST = _FIELDS + """
query ($user: String) {
  MediaListCollection(userName: $user, type: ANIME) {
    lists { entries { status score(format: POINT_10_DECIMAL) progress media { ...f } } }
  }
}"""

Q_BY_MAL = _FIELDS + """
query ($ids: [Int], $page: Int) {
  Page(page: $page, perPage: 50) { media(idMal_in: $ids, type: ANIME) { ...f } }
}"""


class ImportError_(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    media: Media
    status: str            # AniList status (CURRENT, COMPLETED, …)
    score: float           # 0..10 (0 = not scored)
    progress: int          # episodes watched


def rating_from(score: float) -> int | None:
    """0..10 score -> 1..10 half stars (0 = no rating)."""
    if not score or score <= 0:
        return None
    return max(1, min(10, round(score)))


def from_anilist(client: AniListClient, username: str) -> list[Entry]:
    username = username.strip().lstrip("@")
    if not username:
        raise ImportError_("Type your AniList username.")
    try:
        data = client._query(Q_USER_LIST, {"user": username}, ttl=0, allow_not_found=True)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "Private User" in msg or "private" in msg.lower():
            raise ImportError_("That AniList list is private. Make it public for a minute (AniList → Settings "
                               "→ Lists), import, then switch it back.") from exc
        raise ImportError_(f"Couldn't read that AniList list: {msg}") from exc
    coll = (data or {}).get("MediaListCollection")
    if not coll:
        raise ImportError_(f"No AniList user called “{username}” (or their list is empty).")
    out: dict[int, Entry] = {}
    for lst in coll.get("lists") or []:
        for e in lst.get("entries") or []:
            m = e.get("media")
            if not m:
                continue
            media = Media.from_json(m)
            out[media.anilist_id] = Entry(media, e.get("status") or "PLANNING", float(e.get("score") or 0),
                                          int(e.get("progress") or 0))
    return list(out.values())


def parse_mal(path: Path) -> list[tuple[int, str, str, float, int]]:
    """(mal_id, title, status, score, watched) from a MAL export."""
    raw = Path(path).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ImportError_("That isn't a MyAnimeList export (.xml or .xml.gz).") from exc
    rows = []
    for a in root.iter("anime"):
        def text(tag: str) -> str:
            el = a.find(tag)
            return (el.text or "").strip() if el is not None else ""
        try:
            mal_id = int(text("series_animedb_id"))
        except ValueError:
            continue
        status = MAL_STATUS.get(text("my_status"), "PLANNING")
        try:
            score = float(text("my_score") or 0)
            watched = int(text("my_watched_episodes") or 0)
        except ValueError:
            score, watched = 0.0, 0
        rows.append((mal_id, text("series_title"), status, score, watched))
    if not rows:
        raise ImportError_("No anime found in that file. Use MyAnimeList's export (Profile → Export).")
    return rows


def from_mal(client: AniListClient, path: Path) -> list[Entry]:
    rows = parse_mal(path)
    by_mal: dict[int, Media] = {}
    ids = [r[0] for r in rows]
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        data = client._query(Q_BY_MAL, {"ids": chunk, "page": 1}, ttl=7 * 86400)
        for m in ((data or {}).get("Page") or {}).get("media") or []:
            media = Media.from_json(m)
            if m.get("idMal"):
                by_mal[int(m["idMal"])] = media
    return [Entry(by_mal[mal_id], status, score, watched)
            for mal_id, _title, status, score, watched in rows if mal_id in by_mal]


@dataclass
class Result:
    added: int = 0
    rated: int = 0
    episodes: int = 0
    not_found: list[str] = None   # titles hianime doesn't have

    def __post_init__(self):
        if self.not_found is None:
            self.not_found = []


def apply(store, catalog, entries: list[Entry], progress: Callable[[int, int, str], None] | None = None,
          cancelled: Callable[[], bool] = lambda: False) -> Result:
    """Find each show on hianime and put it in your lists. Safe to run again: nothing doubles,
    and ratings or progress you already have are kept."""
    result = Result()
    list_ids: dict[str, int] = {}
    existing = {sl.name: sl.list_id for sl in store.lists()}
    for i, e in enumerate(entries):
        if cancelled():
            break
        if progress:
            progress(i, len(entries), e.media.display_title)
        try:
            found = catalog.find_streamable(e.media)
        except Exception:  # noqa: BLE001 (one bad lookup shouldn't stop the rest)
            found = None
        if found is None:
            result.not_found.append(e.media.display_title)
            continue
        aid = found.anime_id
        store.upsert_show(aid, found.title, found.poster or e.media.cover)
        name, emoji = STATUS_LISTS.get(e.status, STATUS_LISTS["PLANNING"])
        lid = list_ids.get(name) or existing.get(name)
        if lid is None:
            lid = store.create_list(name, emoji)
        list_ids[name] = lid
        store.add_to_list(lid, aid)
        result.added += 1
        rating = rating_from(e.score)
        if rating is not None and store.notes(aid).rating is None:
            store.set_rating(aid, rating)
            result.rated += 1
        done = min(e.progress, e.media.episodes or e.progress)
        if done > 0:
            have = store.show_progress(aid)
            for n in range(1, done + 1):
                if not (have.get(str(n)) and have[str(n)].completed):
                    store.mark_watched(aid, str(n), True)
                    result.episodes += 1
    if progress:
        progress(len(entries), len(entries), "")
    return result
