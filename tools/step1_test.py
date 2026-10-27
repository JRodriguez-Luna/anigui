#!/usr/bin/env python3
"""Step 1 check: search -> episodes -> stream link, all from the terminal.

    python tools/step1_test.py "frieren"                  # doctor + search + episodes + resolve ep 1
    python tools/step1_test.py "frieren" --ep 3 --play     # ...and open it in IINA/mpv
    python tools/step1_test.py "frieren" --qt              # resolve through the QProcess bridge
    python tools/step1_test.py --doctor                    # dependency check only
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.ani_cli import AniCliError, ResolveRequest, StreamInfo, doctor, resolve_stream  # noqa: E402
from core.env import find_player  # noqa: E402
from core.hianime import HianimeClient, HianimeError  # noqa: E402

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def section(title: str) -> None:
    print(f"\n{BOLD}== {title}{RESET}")


def run_doctor(need_player: bool) -> bool:
    section("Dependencies")
    all_required_ok = True
    for name, ok, detail in doctor():
        optional = "optional" in name or (name == "player" and not need_player)
        mark = f"{GREEN}ok{RESET}" if ok else (f"{DIM}--{RESET}" if optional else f"{RED}!!{RESET}")
        print(f"  [{mark}] {name:<26} {detail}")
        if not ok and not optional and name != "ani-cli version":
            all_required_ok = False
    return all_required_ok


def resolve_with_qt(req: ResolveRequest) -> StreamInfo:
    from PySide6.QtCore import QCoreApplication

    from core.cli_bridge import CliBridge

    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    bridge = CliBridge()
    outcome: dict[str, object] = {}

    def done(_rid: str, info: object) -> None:
        outcome["info"] = info
        app.quit()

    def fail(_rid: str, msg: str) -> None:
        outcome["error"] = msg
        app.quit()

    bridge.streamResolved.connect(done)
    bridge.failed.connect(fail)
    bridge.progress.connect(lambda _rid, line: print(f"  {DIM}ani-cli: {line}{RESET}"))
    bridge.resolve(req)
    app.exec()
    if "error" in outcome:
        raise AniCliError(str(outcome["error"]))
    return outcome["info"]  # type: ignore[return-value]


def play_externally(info: StreamInfo) -> None:
    """Minimal launcher for this test. The real one arrives in step 4 (core/player.py)."""
    found = find_player()
    if not found:
        raise SystemExit("No player found. Install IINA (brew install --cask iina) or mpv.")
    kind, path = found
    title = info.title or "AniGUI"

    if kind == "iina":
        def esc(v: str) -> str:  # mpv splits file lists on ':'
            return v.replace(":", "\\:")
        cmd = [path, "--no-stdin", "--keep-running"]
        if info.referrer:
            cmd.append(f"--mpv-referrer={info.referrer}")
        if info.audio_url:
            cmd.append(f"--mpv-audio-files={esc(info.audio_url)}")
        if info.subtitle_url:
            cmd.append(f"--mpv-sub-files={esc(info.subtitle_url)}")
        cmd += [f"--mpv-{a[2:]}" if a.startswith("--") else a for a in info.extra_args]
        cmd += [f"--mpv-force-media-title={title}", info.url]
    else:
        cmd = [path]
        if info.referrer:
            cmd.append(f"--referrer={info.referrer}")
        if info.audio_url:
            cmd.append(f"--audio-file={info.audio_url}")
        if info.subtitle_url:
            cmd.append(f"--sub-file={info.subtitle_url}")
        cmd += [*info.extra_args, f"--force-media-title={title}", info.url]

    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    print(f"  Launched {kind}.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("query", nargs="?", help="anime to search for")
    p.add_argument("--pick", type=int, default=1, help="search result number (default 1)")
    p.add_argument("--ep", default=None, help="episode number (default: first listed)")
    p.add_argument("--dub", action="store_true")
    p.add_argument("--quality", default="best", help="best | worst | 1080 | 720 | 480")
    p.add_argument("--skip", action="store_true", help="ani-skip intro flags (needs ani-skip)")
    p.add_argument("--qt", action="store_true", help="resolve via the QProcess bridge")
    p.add_argument("--play", action="store_true", help="open the stream in IINA/mpv")
    p.add_argument("--doctor", action="store_true", help="only check dependencies")
    args = p.parse_args()

    if not run_doctor(need_player=args.play or args.doctor):
        print(f"\n{RED}Fix the missing dependencies above first.{RESET}")
        return 1
    if args.doctor:
        return 0
    if not args.query:
        p.error("query is required unless --doctor is used")

    client = HianimeClient()

    section(f'Search: "{args.query}"')
    t = time.perf_counter()
    try:
        results = client.search(args.query)
    except HianimeError as exc:
        print(f"  {RED}{exc}{RESET}")
        return 1
    print(f"  {len(results)} results in {time.perf_counter() - t:.1f}s")
    for r in results[:10]:
        marker = "→" if r.index == args.pick else " "
        print(f"  {marker} {r.index:>2}. {r.title}  {DIM}{r.anime_id}{' · poster' if r.poster else ''}{RESET}")
    if not results:
        return 1
    if not 1 <= args.pick <= len(results):
        print(f"  {RED}--pick must be between 1 and {len(results)}{RESET}")
        return 1
    chosen = results[args.pick - 1]

    section(f"Episodes: {chosen.title}")
    t = time.perf_counter()
    try:
        episodes = client.episodes(chosen.anime_id)
    except HianimeError as exc:
        print(f"  {RED}{exc}{RESET}")
        return 1
    print(f"  {len(episodes)} episodes in {time.perf_counter() - t:.1f}s")
    preview = ", ".join(e.number for e in episodes[:15])
    print(f"  {preview}{' …' if len(episodes) > 15 else ''}")
    if not episodes:
        return 1
    episode = args.ep or episodes[0].number
    if episode not in {e.number for e in episodes}:
        print(f"  {RED}Episode {episode} is not in the list{RESET}")
        return 1

    section(f"Resolve: episode {episode} ({'dub' if args.dub else 'sub'}, {args.quality}) via {'QProcess' if args.qt else 'subprocess'}")
    req = ResolveRequest(query=args.query, index=args.pick, episode=episode,
                         dub=args.dub, quality=args.quality, skip_intro=args.skip)
    t = time.perf_counter()
    try:
        info = resolve_with_qt(req) if args.qt else resolve_stream(req)
    except AniCliError as exc:
        print(f"  {RED}{exc}{RESET}")
        return 1
    print(f"  {GREEN}Resolved in {time.perf_counter() - t:.1f}s{RESET}")
    print(f"  title     {info.title}")
    print(f"  url       {info.url}")
    print(f"  referrer  {info.referrer}")
    print(f"  audio     {info.audio_url or '-'}")
    print(f"  subtitles {info.subtitle_url or '-'}")
    if info.extra_args:
        print(f"  extra     {' '.join(info.extra_args)}")

    if args.play:
        section("Play")
        play_externally(info)
    return 0


if __name__ == "__main__":
    sys.exit(main())
