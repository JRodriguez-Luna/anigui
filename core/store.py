"""SQLite state: shows, library, watch progress, and a TTL cache.

Safe to use from worker threads: each thread gets its own connection, and the
database runs in WAL mode so readers never block the writer.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths

SCHEMA_VERSION = 3          # 3: My Library (lists, ratings, tags, notes, timeline), 2.0
COMPLETE_RATIO = 0.90  # past 90% counts as watched (credits)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shows (
    anime_id         TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    poster           TEXT,
    anilist_id       INTEGER,
    match_score      REAL,
    match_manual     INTEGER NOT NULL DEFAULT 0,
    in_library       INTEGER NOT NULL DEFAULT 0,
    library_added_at REAL,
    updated_at       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS progress (
    anime_id   TEXT NOT NULL REFERENCES shows(anime_id) ON DELETE CASCADE,
    episode    TEXT NOT NULL,
    position   REAL NOT NULL DEFAULT 0,
    duration   REAL,
    completed  INTEGER NOT NULL DEFAULT 0,
    source     TEXT NOT NULL DEFAULT 'gui',
    updated_at REAL NOT NULL,
    PRIMARY KEY (anime_id, episode)
);
CREATE INDEX IF NOT EXISTS progress_recent ON progress(updated_at DESC);
CREATE TABLE IF NOT EXISTS history_hidden (
    anime_id TEXT NOT NULL,
    episode  TEXT NOT NULL,
    PRIMARY KEY (anime_id, episode)
);
CREATE TABLE IF NOT EXISTS episode_watch (
    anime_id   TEXT PRIMARY KEY REFERENCES shows(anime_id) ON DELETE CASCADE,
    latest     TEXT NOT NULL,     -- newest episode hianime lists
    seen       TEXT NOT NULL,     -- newest episode the user has seen listed (opened the show)
    notified   TEXT NOT NULL,     -- newest episode a notification went out for
    checked_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS watch_log (
    day      TEXT NOT NULL,       -- local date, YYYY-MM-DD
    anime_id TEXT NOT NULL,
    episode  TEXT NOT NULL,
    seconds  REAL NOT NULL,       -- time actually spent playing (seeks and skips don't count)
    PRIMARY KEY (day, anime_id, episode)
);
CREATE TABLE IF NOT EXISTS mature_flags (
    anilist_id INTEGER PRIMARY KEY,
    mature     INTEGER NOT NULL,      -- 18+ (core/maturity.py)
    notes      TEXT NOT NULL,         -- content notes, joined with '|'
    allowed    INTEGER NOT NULL DEFAULT 0   -- "Don't ask again for this show"
);
CREATE TABLE IF NOT EXISTS lists (               -- My Library: your own lists (2.0)
    list_id    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    emoji      TEXT,
    position   REAL NOT NULL,             -- order in the sidebar
    locked     INTEGER NOT NULL DEFAULT 0,  -- needs Touch ID to open
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS list_items (
    list_id  INTEGER NOT NULL REFERENCES lists(list_id) ON DELETE CASCADE,
    anime_id TEXT NOT NULL REFERENCES shows(anime_id) ON DELETE CASCADE,
    added_at REAL NOT NULL,
    PRIMARY KEY (list_id, anime_id)
);
CREATE TABLE IF NOT EXISTS show_notes (           -- your rating, tags and note for a show
    anime_id   TEXT PRIMARY KEY REFERENCES shows(anime_id) ON DELETE CASCADE,
    rating     INTEGER,                   -- 1..10 = half stars (10 = five stars)
    tags       TEXT NOT NULL DEFAULT '',  -- joined with '|'
    note       TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (               -- for your timeline: saved, listed, rated
    at       REAL NOT NULL,
    kind     TEXT NOT NULL,
    anime_id TEXT NOT NULL,
    detail   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS events_recent ON events(at DESC);
CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""


@dataclass(frozen=True)
class Show:
    anime_id: str
    title: str
    poster: str | None
    anilist_id: int | None
    match_score: float | None
    match_manual: bool
    in_library: bool
    library_added_at: float | None


@dataclass(frozen=True)
class Progress:
    anime_id: str
    episode: str
    position: float
    duration: float | None
    completed: bool
    source: str
    updated_at: float

    @property
    def fraction(self) -> float:
        if self.completed:
            return 1.0
        if not self.duration:
            return 0.0
        return max(0.0, min(1.0, self.position / self.duration))


@dataclass(frozen=True)
class NewEpisodes:
    show: Show
    latest: str      # newest episode out
    seen: str        # newest one the user already knew about

    @property
    def count(self) -> int:
        return max(1, int(episode_key(self.latest) - episode_key(self.seen)))


SAVED = 0     # the built-in Saved list (shows.in_library: My List before 2.0)


@dataclass(frozen=True)
class ShowList:
    list_id: int
    name: str
    emoji: str | None
    locked: bool
    count: int


@dataclass(frozen=True)
class ShowNotes:
    rating: int | None        # 1..10 half stars
    tags: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class Moment:
    at: float
    day: str                  # YYYY-MM-DD
    kind: str                 # watched | saved | listed | rated
    anime_id: str
    detail: str               # episodes ("3, 4, 5"), list name, or the rating
    title: str = ""
    poster: str | None = None


def stars(rating: int | None) -> str:
    """10 -> ★★★★★, 7 -> ★★★½"""
    if not rating:
        return ""
    return "★" * (rating // 2) + ("½" if rating % 2 else "")


def episode_key(number: str | None) -> float:
    try:
        return float(number) if number is not None else -1.0
    except ValueError:
        return -1.0


@dataclass(frozen=True)
class ContinueItem:
    show: Show
    last: Progress  # most recently touched episode; the catalog decides what plays next


class Store:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else paths.database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self.private = False          # Private mode: nothing new goes into your history (2.0)
        self._migrate()

    # -- connection handling -------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def _tx(self) -> "_Tx":
        return _Tx(self._conn())

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def _migrate(self) -> None:
        conn = self._conn()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"Database {self.path} is from a newer AniGUI (schema {version})")
        # Every table is CREATE IF NOT EXISTS, so running the schema also adds tables
        # that are new since this database was made.
        conn.executescript(_SCHEMA)
        if version < SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    # -- shows ---------------------------------------------------------------------

    def upsert_show(self, anime_id: str, title: str, poster: str | None = None) -> None:
        """Insert or refresh a show. Never clears a poster or AniList link already set."""
        with self._tx() as c:
            c.execute(
                """INSERT INTO shows (anime_id, title, poster, updated_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(anime_id) DO UPDATE SET
                       title = excluded.title,
                       poster = COALESCE(excluded.poster, shows.poster),
                       updated_at = excluded.updated_at""",
                (anime_id, title, poster, time.time()),
            )

    def get_show(self, anime_id: str) -> Show | None:
        row = self._conn().execute("SELECT * FROM shows WHERE anime_id = ?", (anime_id,)).fetchone()
        return _show(row) if row else None

    def set_anilist_match(self, anime_id: str, anilist_id: int | None, score: float | None, manual: bool = False) -> None:
        """Link a show to AniList. Automatic matches never overwrite a manual one."""
        with self._tx() as c:
            c.execute(
                """UPDATE shows SET anilist_id = ?, match_score = ?, match_manual = ?, updated_at = ?
                   WHERE anime_id = ? AND (? = 1 OR match_manual = 0)""",
                (anilist_id, score, int(manual), time.time(), anime_id, int(manual)),
            )

    def rename_show(self, old_id: str, new_id: str, title: str, poster: str | None = None) -> None:
        """Move a show (progress, My List, AniList link) to a new hianime id.

        Used when an old id stops resolving. If the new id already has data, both merge;
        existing rows under the new id win.
        """
        if old_id == new_id:
            return
        now = time.time()
        with self._tx() as c:
            old = c.execute("SELECT * FROM shows WHERE anime_id = ?", (old_id,)).fetchone()
            c.execute(
                """INSERT INTO shows (anime_id, title, poster, anilist_id, match_score, match_manual,
                                      in_library, library_added_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(anime_id) DO UPDATE SET
                       poster = COALESCE(shows.poster, excluded.poster),
                       anilist_id = COALESCE(shows.anilist_id, excluded.anilist_id),
                       in_library = MAX(shows.in_library, excluded.in_library),
                       library_added_at = COALESCE(shows.library_added_at, excluded.library_added_at)""",
                (new_id, title, poster or (old["poster"] if old else None),
                 old["anilist_id"] if old else None, old["match_score"] if old else None,
                 old["match_manual"] if old else 0, old["in_library"] if old else 0,
                 old["library_added_at"] if old else None, now),
            )
            c.execute(
                """INSERT OR IGNORE INTO progress (anime_id, episode, position, duration, completed, source, updated_at)
                   SELECT ?, episode, position, duration, completed, source, updated_at
                   FROM progress WHERE anime_id = ?""",
                (new_id, old_id),
            )
            c.execute("UPDATE OR IGNORE episode_watch SET anime_id = ? WHERE anime_id = ?", (new_id, old_id))
            c.execute("UPDATE OR IGNORE watch_log SET anime_id = ? WHERE anime_id = ?", (new_id, old_id))
            c.execute("UPDATE OR IGNORE list_items SET anime_id = ? WHERE anime_id = ?", (new_id, old_id))
            c.execute("UPDATE OR IGNORE show_notes SET anime_id = ? WHERE anime_id = ?", (new_id, old_id))
            c.execute("UPDATE events SET anime_id = ? WHERE anime_id = ?", (new_id, old_id))
            c.execute("DELETE FROM shows WHERE anime_id = ?", (old_id,))  # cascades old progress

    def find_by_anilist(self, anilist_id: int) -> Show | None:
        row = self._conn().execute(
            "SELECT * FROM shows WHERE anilist_id = ? ORDER BY match_manual DESC, match_score DESC LIMIT 1",
            (anilist_id,),
        ).fetchone()
        return _show(row) if row else None

    # -- library ("My List") ------------------------------------------------------

    def set_in_library(self, anime_id: str, value: bool) -> None:
        """The Saved list (My List before 2.0)."""
        with self._tx() as c:
            was = c.execute("SELECT in_library FROM shows WHERE anime_id = ?", (anime_id,)).fetchone()
            if value and was is not None and not was[0] and not self.private:
                c.execute("INSERT INTO events (at, kind, anime_id, detail) VALUES (?, 'saved', ?, '')",
                          (time.time(), anime_id))
            c.execute(
                """UPDATE shows SET in_library = ?,
                       library_added_at = CASE WHEN ? THEN COALESCE(library_added_at, ?) ELSE NULL END
                   WHERE anime_id = ?""",
                (int(value), int(value), time.time(), anime_id),
            )

    def library(self) -> list[Show]:
        rows = self._conn().execute(
            "SELECT * FROM shows WHERE in_library = 1 ORDER BY library_added_at DESC"
        ).fetchall()
        return [_show(r) for r in rows]

    # -- My Library: lists (2.0) -----------------------------------------------------

    def lists(self) -> list["ShowList"]:
        """Saved (the old My List) first, then your lists in their order."""
        c = self._conn()
        saved = c.execute("SELECT COUNT(*) FROM shows WHERE in_library = 1").fetchone()[0]
        out = [ShowList(SAVED, "Saved", None, False, saved)]
        for r in c.execute(
            """SELECT l.*, (SELECT COUNT(*) FROM list_items i WHERE i.list_id = l.list_id) AS n
               FROM lists l ORDER BY position, list_id"""
        ):
            out.append(ShowList(r["list_id"], r["name"], r["emoji"], bool(r["locked"]), r["n"]))
        return out

    def library_all(self) -> list[Show]:
        """Every show that's yours: saved, in a list, rated, tagged or noted. Newest first."""
        rows = self._conn().execute(
            """SELECT s.*, MAX(COALESCE(s.library_added_at, 0),
                              COALESCE((SELECT MAX(added_at) FROM list_items i WHERE i.anime_id = s.anime_id), 0),
                              COALESCE((SELECT updated_at FROM show_notes n WHERE n.anime_id = s.anime_id), 0)) AS mine
               FROM shows s
               WHERE s.in_library = 1
                  OR EXISTS (SELECT 1 FROM list_items i WHERE i.anime_id = s.anime_id)
                  OR EXISTS (SELECT 1 FROM show_notes n WHERE n.anime_id = s.anime_id)
               ORDER BY mine DESC""").fetchall()
        return [_show(r) for r in rows]

    def get_list(self, list_id: int) -> "ShowList | None":
        return next((sl for sl in self.lists() if sl.list_id == list_id), None)

    def create_list(self, name: str, emoji: str | None = None) -> int:
        name = name.strip() or "New list"
        with self._tx() as c:
            pos = c.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM lists").fetchone()[0]
            cur = c.execute("INSERT INTO lists (name, emoji, position, created_at) VALUES (?, ?, ?, ?)",
                            (name, emoji or None, pos, time.time()))
            return int(cur.lastrowid)

    def rename_list(self, list_id: int, name: str, emoji: str | None = None) -> None:
        if list_id == SAVED:
            return
        with self._tx() as c:
            c.execute("UPDATE lists SET name = ?, emoji = ? WHERE list_id = ?",
                      (name.strip() or "Untitled", emoji or None, list_id))

    def delete_list(self, list_id: int) -> None:
        """Deletes the list, not the shows (or anything you watched)."""
        if list_id == SAVED:
            return
        with self._tx() as c:
            c.execute("DELETE FROM lists WHERE list_id = ?", (list_id,))

    def move_list(self, list_id: int, index: int) -> None:
        """Put a list at `index` among your lists (Saved always stays first)."""
        ids = [sl.list_id for sl in self.lists() if sl.list_id != SAVED]
        if list_id not in ids:
            return
        ids.remove(list_id)
        ids.insert(max(0, min(index, len(ids))), list_id)
        with self._tx() as c:
            for pos, lid in enumerate(ids, 1):
                c.execute("UPDATE lists SET position = ? WHERE list_id = ?", (pos, lid))

    def set_list_locked(self, list_id: int, locked: bool) -> None:
        with self._tx() as c:
            c.execute("UPDATE lists SET locked = ? WHERE list_id = ?", (int(locked), list_id))

    def list_shows(self, list_id: int) -> list[Show]:
        if list_id == SAVED:
            return self.library()
        rows = self._conn().execute(
            """SELECT s.* FROM list_items i JOIN shows s ON s.anime_id = i.anime_id
               WHERE i.list_id = ? ORDER BY i.added_at DESC""", (list_id,)).fetchall()
        return [_show(r) for r in rows]

    def add_to_list(self, list_id: int, anime_id: str) -> None:
        if list_id == SAVED:
            self.set_in_library(anime_id, True)
            return
        with self._tx() as c:
            cur = c.execute("INSERT OR IGNORE INTO list_items (list_id, anime_id, added_at) VALUES (?, ?, ?)",
                            (list_id, anime_id, time.time()))
            if cur.rowcount and not self.private:
                name = c.execute("SELECT name FROM lists WHERE list_id = ?", (list_id,)).fetchone()
                c.execute("INSERT INTO events (at, kind, anime_id, detail) VALUES (?, 'listed', ?, ?)",
                          (time.time(), anime_id, name[0] if name else ""))

    def remove_from_list(self, list_id: int, anime_id: str) -> None:
        if list_id == SAVED:
            self.set_in_library(anime_id, False)
            return
        with self._tx() as c:
            c.execute("DELETE FROM list_items WHERE list_id = ? AND anime_id = ?", (list_id, anime_id))

    def lists_for(self, anime_id: str) -> set[int]:
        c = self._conn()
        out = {r[0] for r in c.execute("SELECT list_id FROM list_items WHERE anime_id = ?", (anime_id,))}
        saved = c.execute("SELECT in_library FROM shows WHERE anime_id = ?", (anime_id,)).fetchone()
        if saved and saved[0]:
            out.add(SAVED)
        return out

    # -- My Library: your rating, tags and note (2.0) --------------------------------

    def notes(self, anime_id: str) -> "ShowNotes":
        r = self._conn().execute("SELECT * FROM show_notes WHERE anime_id = ?", (anime_id,)).fetchone()
        if r is None:
            return ShowNotes(None, (), "")
        return ShowNotes(r["rating"], tuple(t for t in r["tags"].split("|") if t), r["note"])

    def _save_notes(self, anime_id: str, **changes) -> None:
        old = self.notes(anime_id)
        rating = changes.get("rating", old.rating)
        tags = changes.get("tags", old.tags)
        note = changes.get("note", old.note)
        with self._tx() as c:
            if rating is None and not tags and not note:
                c.execute("DELETE FROM show_notes WHERE anime_id = ?", (anime_id,))
                return
            c.execute(
                """INSERT INTO show_notes (anime_id, rating, tags, note, updated_at) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(anime_id) DO UPDATE SET rating = excluded.rating, tags = excluded.tags,
                       note = excluded.note, updated_at = excluded.updated_at""",
                (anime_id, rating, "|".join(tags), note, time.time()))

    def set_rating(self, anime_id: str, rating: int | None) -> None:
        """rating: 1..10 half stars (10 = ★★★★★), or None to clear."""
        if rating is not None:
            rating = max(1, min(10, int(rating)))
        if rating == self.notes(anime_id).rating:
            return
        self._save_notes(anime_id, rating=rating)
        if rating is not None and not self.private:
            with self._tx() as c:
                c.execute("DELETE FROM events WHERE kind = 'rated' AND anime_id = ? AND at > ?",
                          (anime_id, time.time() - 600))      # changing your mind isn't news
                c.execute("INSERT INTO events (at, kind, anime_id, detail) VALUES (?, 'rated', ?, ?)",
                          (time.time(), anime_id, str(rating)))

    def set_tags(self, anime_id: str, tags) -> None:
        clean: list[str] = []
        for t in tags:
            t = " ".join(str(t).replace("|", " ").split())[:40]
            if t and t.lower() not in (x.lower() for x in clean):
                clean.append(t)
        self._save_notes(anime_id, tags=tuple(clean))

    def set_note(self, anime_id: str, note: str) -> None:
        self._save_notes(anime_id, note=note.strip())

    def all_tags(self) -> list[tuple[str, int]]:
        """Every tag you've used, most used first."""
        counts: dict[str, int] = {}
        names: dict[str, str] = {}
        for (raw,) in self._conn().execute("SELECT tags FROM show_notes WHERE tags != ''"):
            for t in raw.split("|"):
                if t:
                    counts[t.lower()] = counts.get(t.lower(), 0) + 1
                    names.setdefault(t.lower(), t)
        return sorted(((names[k], n) for k, n in counts.items()), key=lambda kv: (-kv[1], kv[0].lower()))

    def tagged(self, tag: str) -> list[Show]:
        rows = self._conn().execute(
            """SELECT s.*, n.tags FROM show_notes n JOIN shows s ON s.anime_id = n.anime_id
               WHERE n.tags != '' ORDER BY n.updated_at DESC""").fetchall()
        want = tag.lower()
        return [_show(r) for r in rows if want in (t.lower() for t in r["tags"].split("|"))]

    def rated(self) -> list[tuple[Show, int]]:
        rows = self._conn().execute(
            """SELECT s.*, n.rating FROM show_notes n JOIN shows s ON s.anime_id = n.anime_id
               WHERE n.rating IS NOT NULL ORDER BY n.rating DESC, n.updated_at DESC""").fetchall()
        return [(_show(r), r["rating"]) for r in rows]

    # -- My Library: your timeline (2.0) ---------------------------------------------

    def timeline(self, days: int = 90) -> list["Moment"]:
        """What you did, newest first: episodes watched (one entry per show per day), shows
        saved or added to a list, and ratings. All from this Mac; nothing is sent anywhere."""
        c = self._conn()
        since_day = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        out: list[Moment] = []
        watched: dict[tuple[str, str], list] = {}
        for day, aid, ep, secs in c.execute(
                "SELECT day, anime_id, episode, seconds FROM watch_log WHERE day >= ?", (since_day,)):
            if secs >= 60:
                watched.setdefault((day, aid), []).append(ep)
        last_at = dict(c.execute(
            """SELECT anime_id, MAX(updated_at) FROM progress GROUP BY anime_id""").fetchall())
        for (day, aid), eps in watched.items():
            eps.sort(key=episode_key)
            when = dt.datetime.fromisoformat(day + "T12:00:00").timestamp()
            last = last_at.get(aid)
            if last and dt.date.fromtimestamp(last).isoformat() == day:
                when = last
            out.append(Moment(when, day, "watched", aid, ", ".join(eps)))
        since = dt.datetime.fromisoformat(since_day + "T00:00:00").timestamp()
        for at, kind, aid, detail in c.execute(
                "SELECT at, kind, anime_id, detail FROM events WHERE at >= ?", (since,)):
            out.append(Moment(at, dt.date.fromtimestamp(at).isoformat(), kind, aid, detail))
        titles = {r["anime_id"]: r for r in c.execute("SELECT anime_id, title, poster FROM shows")}
        out = [m for m in out if m.anime_id in titles]
        for i, m in enumerate(out):
            row = titles[m.anime_id]
            out[i] = Moment(m.at, m.day, m.kind, m.anime_id, m.detail, row["title"], row["poster"])
        out.sort(key=lambda m: m.at, reverse=True)
        return out

    # -- progress ------------------------------------------------------------------

    def record_progress(self, anime_id: str, episode: str, position: float,
                        duration: float | None = None, source: str = "gui") -> Progress:
        """Save playback position. Crossing 90% of the duration marks it watched; it stays watched."""
        done = bool(duration and duration > 0 and position / duration >= COMPLETE_RATIO)
        now = time.time()
        with self._tx() as c:
            c.execute(
                """INSERT INTO progress (anime_id, episode, position, duration, completed, source, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(anime_id, episode) DO UPDATE SET
                       position = excluded.position,
                       duration = COALESCE(excluded.duration, progress.duration),
                       completed = MAX(progress.completed, excluded.completed),
                       source = excluded.source,
                       updated_at = excluded.updated_at""",
                (anime_id, episode, max(0.0, position), duration, int(done), source, now),
            )
        return self.get_progress(anime_id, episode)  # type: ignore[return-value]

    def mark_watched(self, anime_id: str, episode: str, watched: bool = True) -> None:
        """Watched keeps any saved position; unwatched forgets the episode entirely."""
        with self._tx() as c:
            if not watched:
                c.execute("DELETE FROM progress WHERE anime_id = ? AND episode = ?", (anime_id, episode))
                return
            c.execute(
                """INSERT INTO progress (anime_id, episode, completed, updated_at) VALUES (?, ?, 1, ?)
                   ON CONFLICT(anime_id, episode) DO UPDATE SET completed = 1, updated_at = excluded.updated_at""",
                (anime_id, episode, time.time()),
            )

    def get_progress(self, anime_id: str, episode: str) -> Progress | None:
        row = self._conn().execute(
            "SELECT * FROM progress WHERE anime_id = ? AND episode = ?", (anime_id, episode)
        ).fetchone()
        return _progress(row) if row else None

    def show_progress(self, anime_id: str) -> dict[str, Progress]:
        rows = self._conn().execute("SELECT * FROM progress WHERE anime_id = ?", (anime_id,)).fetchall()
        return {r["episode"]: _progress(r) for r in rows}

    def continue_watching(self, limit: int = 20) -> list[ContinueItem]:
        rows = self._conn().execute(
            """SELECT p.anime_id, p.episode, p.position, p.duration, p.completed, p.source, p.updated_at,
                      s.title, s.poster, s.anilist_id, s.match_score, s.match_manual,
                      s.in_library, s.library_added_at
               FROM (
                   SELECT *, ROW_NUMBER() OVER (PARTITION BY anime_id ORDER BY updated_at DESC) AS rn
                   FROM progress
               ) p JOIN shows s ON s.anime_id = p.anime_id
               WHERE p.rn = 1
               ORDER BY p.updated_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [ContinueItem(_show(r), _progress(r)) for r in rows]

    def forget_show_progress(self, anime_id: str, history: str | Path | None = None) -> None:
        """Remove a show from Continue Watching and drop its episode progress."""
        hidden = [(a, e) for e, a, _t in self._ani_cli_entries(history) if a == anime_id]
        with self._tx() as c:
            c.execute("DELETE FROM progress WHERE anime_id = ?", (anime_id,))
            c.execute("DELETE FROM watch_log WHERE anime_id = ?", (anime_id,))
            c.executemany("INSERT OR IGNORE INTO history_hidden VALUES (?, ?)", hidden)

    def clear_history(self, history: str | Path | None = None) -> int:
        """Forget all watch progress (Continue Watching, resume points, watched marks).

        My List is kept. ani-cli's own history file is left alone, but what it lists
        right now is remembered as cleared so the next import doesn't bring it back.
        Returns how many shows were cleared.
        """
        hidden = [(a, e) for e, a, _t in self._ani_cli_entries(history)]
        with self._tx() as c:
            shows = c.execute("SELECT COUNT(DISTINCT anime_id) FROM progress").fetchone()[0]
            c.execute("DELETE FROM progress")
            c.execute("DELETE FROM watch_log")  # stats come from history, so they go with it
            c.executemany("INSERT OR IGNORE INTO history_hidden VALUES (?, ?)", hidden)
        return shows

    # -- watch log (for stats) ------------------------------------------------------

    def log_watch(self, anime_id: str, episode: str, seconds: float, day: dt.date | None = None) -> None:
        if seconds <= 0:
            return
        day = (day or dt.date.today()).isoformat()
        with self._tx() as c:
            c.execute("""INSERT INTO watch_log VALUES (?, ?, ?, ?)
                         ON CONFLICT(day, anime_id, episode) DO UPDATE SET seconds = seconds + excluded.seconds""",
                      (day, anime_id, episode, seconds))

    def watch_log(self) -> list[tuple[str, str, str, float]]:
        """(day, anime_id, episode, seconds) rows."""
        return [tuple(r) for r in self._conn().execute("SELECT day, anime_id, episode, seconds FROM watch_log")]

    def all_progress(self) -> list[Progress]:
        return [_progress(r) for r in self._conn().execute("SELECT * FROM progress")]

    # -- new episodes -----------------------------------------------------------------

    def watched_latest(self, anime_id: str) -> str | None:
        row = self._conn().execute("SELECT latest FROM episode_watch WHERE anime_id = ?", (anime_id,)).fetchone()
        return row["latest"] if row else None

    def set_latest(self, anime_id: str, latest: str, *, seen: bool = False) -> bool:
        """Record the newest episode out. The first time, nothing counts as new.

        Returns True if this is a newer episode than before.
        """
        now = time.time()
        with self._tx() as c:
            row = c.execute("SELECT latest, seen FROM episode_watch WHERE anime_id = ?", (anime_id,)).fetchone()
            if row is None:
                # Only for saved shows; one that's still being saved is picked up next time
                c.execute("""INSERT INTO episode_watch SELECT ?, ?, ?, ?, ?
                             WHERE EXISTS (SELECT 1 FROM shows WHERE anime_id = ?)""",
                          (anime_id, latest, latest, latest, now, anime_id))
                return False
            newer = episode_key(latest) > episode_key(row["latest"])
            new_latest = latest if newer else row["latest"]
            c.execute("UPDATE episode_watch SET latest = ?, seen = ?, checked_at = ? WHERE anime_id = ?",
                      (new_latest, new_latest if seen else row["seen"], now, anime_id))
            return newer

    def mark_episodes_seen(self, anime_id: str) -> bool:
        """The user opened the show: its new episodes aren't new anymore. True if anything changed."""
        with self._tx() as c:
            cur = c.execute("UPDATE episode_watch SET seen = latest, notified = latest "
                            "WHERE anime_id = ? AND seen != latest", (anime_id,))
            return cur.rowcount > 0

    def new_episodes(self) -> list[NewEpisodes]:
        rows = self._conn().execute(
            """SELECT w.latest AS w_latest, w.seen AS w_seen, w.checked_at AS w_checked, s.*
               FROM episode_watch w JOIN shows s ON s.anime_id = w.anime_id""").fetchall()
        items = [NewEpisodes(_show(r), r["w_latest"], r["w_seen"]) for r in rows
                 if episode_key(r["w_latest"]) > episode_key(r["w_seen"])]
        return sorted(items, key=lambda i: i.show.title.lower())

    def take_unnotified(self) -> list[NewEpisodes]:
        """New episodes nobody was notified about yet; marks them notified."""
        with self._tx() as c:
            rows = c.execute(
                """SELECT w.latest AS w_latest, w.seen AS w_seen, w.notified AS w_notified, s.*
                   FROM episode_watch w JOIN shows s ON s.anime_id = w.anime_id""").fetchall()
            fresh = [r for r in rows if episode_key(r["w_latest"]) > episode_key(r["w_notified"])
                     and episode_key(r["w_latest"]) > episode_key(r["w_seen"])]
            for r in fresh:
                c.execute("UPDATE episode_watch SET notified = latest WHERE anime_id = ?", (r["anime_id"],))
        return [NewEpisodes(_show(r), r["w_latest"], r["w_seen"]) for r in fresh]

    # -- ani-cli history -----------------------------------------------------------

    def import_ani_cli_history(self, path: str | Path | None = None) -> int:
        """Bring in shows watched with ani-cli in the terminal. Safe to run every launch.

        Each history line is `episode<TAB>anime_id<TAB>title`. ani-cli records an episode
        when it starts playing and offers the next one on --continue, so imported
        episodes count as watched. Pre-v5 ids (no dash) can't be resolved and are skipped.
        Existing rows are never overwritten.
        """
        path = Path(path) if path else paths.ani_cli_history_file()
        if not path.is_file():
            return 0
        stamp = path.stat().st_mtime
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        imported = 0
        with self._tx() as c:
            hidden = {tuple(r) for r in c.execute("SELECT anime_id, episode FROM history_hidden")}
            for i, line in enumerate(lines):
                entry = _history_entry(line)
                if not entry:
                    continue
                episode, anime_id, title = entry
                if (anime_id, episode) in hidden:  # cleared in AniGUI
                    continue
                # The file has no dates. ani-cli appends new shows at the end, so later
                # lines get later timestamps; that keeps Continue Watching in a sane order.
                when = stamp - (len(lines) - i)
                c.execute(
                    "INSERT OR IGNORE INTO shows (anime_id, title, updated_at) VALUES (?, ?, ?)",
                    (anime_id, title, when),
                )
                cur = c.execute(
                    """INSERT OR IGNORE INTO progress (anime_id, episode, completed, source, updated_at)
                       VALUES (?, ?, 1, 'ani-cli', ?)""",
                    (anime_id, episode, when),
                )
                imported += cur.rowcount
        return imported

    def ani_cli_history_shows(self, path: str | Path | None = None) -> int:
        """How many shows ani-cli's Terminal history lists (that AniGUI can use)."""
        return len({anime_id for _e, anime_id, _t in self._ani_cli_entries(path)})

    def _ani_cli_entries(self, path: str | Path | None) -> list[tuple[str, str, str]]:
        path = Path(path) if path else paths.ani_cli_history_file()
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        return [e for e in map(_history_entry, lines) if e]

    # -- TTL cache -----------------------------------------------------------------

    def cache_get(self, key: str) -> str | None:
        row = self._conn().execute(
            "SELECT value FROM cache WHERE key = ? AND expires_at > ?", (key, time.time())
        ).fetchone()
        return row["value"] if row else None

    def cache_put(self, key: str, value: str, ttl: float) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
                (key, value, time.time() + ttl),
            )

    def cache_delete(self, key: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM cache WHERE key = ?", (key,))

    # -- 18+ flags (by AniList id, so they work before a show is linked to hianime) -----

    def set_maturity(self, anilist_id: int, mature: bool, notes: tuple[str, ...]) -> None:
        with self._tx() as c:
            c.execute("""INSERT INTO mature_flags (anilist_id, mature, notes) VALUES (?, ?, ?)
                         ON CONFLICT(anilist_id) DO UPDATE SET mature = excluded.mature, notes = excluded.notes""",
                      (int(anilist_id), int(bool(mature)), "|".join(notes)))

    def maturity(self, anilist_id: int | None) -> tuple[bool, tuple[str, ...], bool] | None:
        """(mature, notes, allowed) or None if this show hasn't been looked at yet."""
        if not anilist_id:
            return None
        row = self._conn().execute("SELECT mature, notes, allowed FROM mature_flags WHERE anilist_id = ?",
                                   (int(anilist_id),)).fetchone()
        if row is None:
            return None
        return bool(row[0]), tuple(n for n in row[1].split("|") if n), bool(row[2])

    def allow_mature(self, anilist_id: int, allowed: bool = True) -> None:
        with self._tx() as c:
            c.execute("""INSERT INTO mature_flags (anilist_id, mature, notes, allowed) VALUES (?, 1, '', ?)
                         ON CONFLICT(anilist_id) DO UPDATE SET allowed = excluded.allowed""",
                      (int(anilist_id), int(bool(allowed))))

    def cache_get_json(self, key: str) -> Any | None:
        raw = self.cache_get(key)
        return json.loads(raw) if raw is not None else None

    def cache_put_json(self, key: str, value: Any, ttl: float) -> None:
        self.cache_put(key, json.dumps(value, separators=(",", ":")), ttl)

    def cache_prune(self) -> int:
        with self._tx() as c:
            return c.execute("DELETE FROM cache WHERE expires_at <= ?", (time.time(),)).rowcount


class _Tx:
    """BEGIN IMMEDIATE ... COMMIT/ROLLBACK on a connection in autocommit mode."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, *_: object) -> None:
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")


def _history_entry(line: str) -> tuple[str, str, str] | None:
    """(episode, anime_id, title) from an ani-cli history line, or None if unusable."""
    parts = line.split("\t")
    if len(parts) != 3 or "-" not in parts[1]:
        return None
    episode, anime_id, title = (p.strip() for p in parts)
    return (episode, anime_id, title) if episode and anime_id and title else None


def _show(row: sqlite3.Row) -> Show:
    return Show(
        anime_id=row["anime_id"], title=row["title"], poster=row["poster"],
        anilist_id=row["anilist_id"], match_score=row["match_score"],
        match_manual=bool(row["match_manual"]), in_library=bool(row["in_library"]),
        library_added_at=row["library_added_at"],
    )


def _progress(row: sqlite3.Row) -> Progress:
    return Progress(
        anime_id=row["anime_id"], episode=row["episode"], position=row["position"],
        duration=row["duration"], completed=bool(row["completed"]), source=row["source"],
        updated_at=row["updated_at"],
    )
