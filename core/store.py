"""SQLite state: shows, library, watch progress, and a TTL cache.

Safe to use from worker threads: each thread gets its own connection, and the
database runs in WAL mode so readers never block the writer.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths

SCHEMA_VERSION = 2
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
            c.execute("DELETE FROM shows WHERE anime_id = ?", (old_id,))  # cascades old progress

    def find_by_anilist(self, anilist_id: int) -> Show | None:
        row = self._conn().execute(
            "SELECT * FROM shows WHERE anilist_id = ? ORDER BY match_manual DESC, match_score DESC LIMIT 1",
            (anilist_id,),
        ).fetchone()
        return _show(row) if row else None

    # -- library ("My List") ------------------------------------------------------

    def set_in_library(self, anime_id: str, value: bool) -> None:
        with self._tx() as c:
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
            c.executemany("INSERT OR IGNORE INTO history_hidden VALUES (?, ?)", hidden)
        return shows

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
