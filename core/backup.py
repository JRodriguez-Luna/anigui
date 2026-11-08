"""Your data (2.0): back up and restore everything that's yours, on your own Mac.

A backup is one .anigui-backup file (a zip): your database (history, lists, ratings, notes,
timeline) and your settings, plus a small manifest. Restoring makes a safety backup of what's
there first. Automatic backups keep the newest few in AniGUI's folder.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from . import __version__, paths
from .store import SCHEMA_VERSION, Store

EXT = ".anigui-backup"
KEEP = 7


class BackupError(Exception):
    pass


def backups_dir() -> Path:
    path = paths.data_dir() / "Backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_name(when: dt.datetime | None = None) -> str:
    when = when or dt.datetime.now()
    return f"AniGUI {when.strftime('%Y-%m-%d %H.%M')}{EXT}"


def back_up(store: Store, prefs: dict[str, Any], dest: Path, reason: str = "manual") -> Path:
    """Write a backup to `dest` (a file). Returns its path."""
    dest = Path(dest)
    if dest.suffix != EXT:
        dest = dest.with_name(dest.name + EXT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "anigui.db"
        target = sqlite3.connect(snap)
        try:
            store._conn().backup(target)           # a consistent copy, even while AniGUI writes
        finally:
            target.close()
        manifest = {"app": "AniGUI", "version": __version__, "schema": SCHEMA_VERSION, "reason": reason,
                    "created": dt.datetime.now().isoformat(timespec="seconds")}
        partial = dest.with_name(dest.name + ".part")
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
            z.write(snap, "anigui.db")
            z.writestr("settings.json", json.dumps(_plain(prefs), indent=2, sort_keys=True))
        partial.replace(dest)
    return dest


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as z:
            manifest = json.loads(z.read("manifest.json"))
            if "anigui.db" not in z.namelist():
                raise BackupError("This backup has no database in it.")
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError) as exc:
        raise BackupError("That isn't an AniGUI backup.") from exc
    if manifest.get("app") != "AniGUI":
        raise BackupError("That isn't an AniGUI backup.")
    if int(manifest.get("schema", 0)) > SCHEMA_VERSION:
        raise BackupError(f"This backup is from a newer AniGUI ({manifest.get('version', '?')}). Update AniGUI first.")
    return manifest


def restore(store: Store, src: Path, prefs_now: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    """Replace your data with the backup's. Returns (the backup's settings, the safety backup
    made of what was there before)."""
    read_manifest(src)
    safety = back_up(store, prefs_now, backups_dir() / default_name().replace(EXT, f" before restore{EXT}"),
                     reason="before restore")
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(src) as z:
        z.extract("anigui.db", tmp)
        settings = json.loads(z.read("settings.json")) if "settings.json" in z.namelist() else {}
        source = sqlite3.connect(Path(tmp) / "anigui.db")
        try:
            check = source.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise BackupError("The backup's database is damaged, so nothing was changed.")
            source.backup(store._conn())
        finally:
            source.close()
    store._migrate()                               # an older backup gets the newer tables
    return settings, safety


def auto_backup(store: Store, prefs: dict[str, Any], folder: Path | None = None, keep: int = KEEP,
                every: dt.timedelta = dt.timedelta(days=1), now: dt.datetime | None = None) -> Path | None:
    """A backup if the newest automatic one is older than `every`; keeps the newest `keep`."""
    folder = Path(folder) if folder else backups_dir()
    folder.mkdir(parents=True, exist_ok=True)
    now = now or dt.datetime.now()
    autos = sorted(folder.glob(f"AniGUI auto *{EXT}"))
    if autos and now - dt.datetime.fromtimestamp(autos[-1].stat().st_mtime) < every:
        return None
    path = back_up(store, prefs, folder / f"AniGUI auto {now.strftime('%Y-%m-%d %H.%M')}{EXT}", reason="automatic")
    autos = sorted(folder.glob(f"AniGUI auto *{EXT}"))
    for old in autos[:-keep]:
        old.unlink(missing_ok=True)
    return path


def list_backups(folder: Path | None = None) -> list[tuple[Path, dict[str, Any]]]:
    folder = Path(folder) if folder else backups_dir()
    out = []
    for path in sorted(folder.glob(f"*{EXT}"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            out.append((path, read_manifest(path)))
        except BackupError:
            continue
    return out


def _plain(prefs: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in prefs.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, tuple)):
            out[k] = [x for x in v if isinstance(x, (str, int, float, bool))]
    return out
