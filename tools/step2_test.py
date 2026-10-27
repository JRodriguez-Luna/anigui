#!/usr/bin/env python3
"""Step 2 check against the live services.

    python tools/step2_test.py                  # uses ~/Library/Application Support/AniGUI
    python tools/step2_test.py --sandbox        # throwaway data dir instead
    python tools/step2_test.py --search "dandadan"

Runs: ani-cli history import -> Continue Watching -> AniList trending/season ->
hianime <-> AniList matching both ways -> parallel cover downloads on the thread pool.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def section(title: str) -> None:
    print(f"\n{BOLD}== {title}{RESET}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sandbox", action="store_true", help="use a temporary data directory")
    p.add_argument("--search", default="frieren", help="hianime search used for the match check")
    args = p.parse_args()

    if args.sandbox:
        os.environ["ANIGUI_HOME"] = tempfile.mkdtemp(prefix="anigui-")

    from PySide6.QtCore import QCoreApplication

    from core import paths
    from core.anilist import AniListError, current_season
    from core.catalog import AUTO_MATCH, Catalog, CatalogError
    from core.covers import CoverCache
    from core.hianime import HianimeError
    from core.store import Store
    from core.tasks import TaskRunner

    app = QCoreApplication(sys.argv)
    store = Store()
    catalog = Catalog(store)
    failures = 0
    print(f"{DIM}data: {paths.data_dir()}\ncache: {paths.cache_dir()}{RESET}")

    section("ani-cli history import")
    hist = paths.ani_cli_history_file()
    n = store.import_ani_cli_history()
    print(f"  {hist} → {n} new entries" if hist.exists() else f"  no history at {hist} (fine)")

    section("Continue Watching")
    items = store.continue_watching(limit=5)
    if not items:
        print("  (empty)")
    for item in items:
        state = "watched" if item.last.completed else f"{item.last.fraction:.0%}"
        print(f"  {item.show.title} — ep {item.last.episode} ({state}, {item.last.source})")
    if items:
        try:
            first = items[0]
            nxt = Catalog.next_episode(first, catalog.episodes(first.show.anime_id))
            print(f"  ▶ next for {first.show.title}: {('episode ' + nxt.number) if nxt else 'caught up'}")
        except (HianimeError, CatalogError) as exc:
            print(f"  {RED}{exc}{RESET}")
            failures += 1

    section("AniList trending")
    trending = []
    try:
        t = time.perf_counter()
        trending = catalog.anilist.trending(per_page=10)
        print(f"  {len(trending)} in {time.perf_counter() - t:.1f}s")
        for m in trending:
            print(f"  {m.score or '--':>3}  {m.display_title}  {DIM}{m.format}, {m.episodes or '?'} eps{RESET}")
        season, year = current_season()
        top = catalog.anilist.season(per_page=5)
        print(f"  {season.title()} {year} top: " + ", ".join(m.display_title for m in top))
    except AniListError as exc:
        print(f"  {RED}{exc}{RESET}")
        failures += 1

    section(f'hianime → AniList ("{args.search}")')
    try:
        results = catalog.hianime.search(args.search)[:3]
        for r in results:
            media = catalog.enrich(r.anime_id, r.title, r.poster)
            show = store.get_show(r.anime_id)
            if media:
                print(f"  {GREEN}✓{RESET} {r.title} → {media.display_title} {DIM}(#{media.anilist_id}, score {show.match_score}){RESET}")
            else:
                print(f"  {DIM}–{RESET} {r.title} → no confident match (needs ≥ {AUTO_MATCH})")
    except (HianimeError, AniListError) as exc:
        print(f"  {RED}{exc}{RESET}")
        failures += 1

    section("AniList → hianime (top 3 trending)")
    for media in trending[:3]:
        try:
            found = catalog.find_streamable(media)
            if found:
                loc = catalog.locate(found.anime_id, found.title)
                print(f"  {GREEN}✓{RESET} {media.display_title} → {found.anime_id} {DIM}(ani-cli -S {loc.index} \"{loc.query}\"){RESET}")
            else:
                print(f"  {DIM}–{RESET} {media.display_title} → not found on hianime")
        except (HianimeError, CatalogError) as exc:
            print(f"  {RED}{media.display_title}: {exc}{RESET}")
            failures += 1

    section("Covers (thread pool)")
    covers = CoverCache()
    runner = TaskRunner()
    urls = [u for m in trending[:8] for u in (m.cover,) if u]
    done: list[Path] = []
    errors: list[str] = []
    t = time.perf_counter()
    for url in urls:
        runner.submit(covers.get, url, on_done=done.append, on_error=errors.append)
    while runner.pending():
        app.processEvents()
        time.sleep(0.01)
    print(f"  {len(done)}/{len(urls)} covers in {time.perf_counter() - t:.1f}s → {covers.dir}")
    for e in errors:
        print(f"  {RED}{e}{RESET}")
    failures += bool(errors)
    print(f"  cache size {covers.size_bytes() / 1e6:.1f} MB")

    print(f"\n{GREEN if not failures else RED}{'All checks passed' if not failures else f'{failures} check(s) failed'}{RESET}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
