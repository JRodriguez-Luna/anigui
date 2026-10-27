#!/usr/bin/env python3
"""Compare parsed episode lists with the raw hianime pages for shows in your ani-cli history.

    python tools/episode_probe.py            # every show in history
    python tools/episode_probe.py demon      # only titles containing "demon"

A "raw" count higher than "parsed" means the episode parser is missing entries.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import paths  # noqa: E402
from core.hianime import EPISODES_URL, HianimeClient, HianimeError, parse_episodes  # noqa: E402


def main() -> int:
    needle = " ".join(sys.argv[1:]).lower()
    hist = paths.ani_cli_history_file()
    if not hist.exists():
        print(f"No ani-cli history at {hist}")
        return 1
    client = HianimeClient()
    print(f"{'raw':>4} {'parsed':>6} {'last':>6}  {'history ep':>10}  title")
    for line in hist.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or "-" not in parts[1]:
            continue
        episode, anime_id, title = parts
        if needle and needle not in title.lower():
            continue
        try:
            raw = client._get(EPISODES_URL.format(anime_id.rsplit("-", 1)[-1]))
        except HianimeError as exc:
            print(f"   ?      ?      ?  {episode:>10}  {title}  ({exc})")
            continue
        raw_count = len(re.findall(r'data-number=\\?"', raw))
        eps = parse_episodes(raw, anime_id)
        last = eps[-1].number if eps else "-"
        flag = ""
        if not eps:
            slugs = sorted(set(re.findall(r"/watch/([^?\\\"]+)\\?\?ep=", raw)))
            flag = f"  <-- stale id; page lists {', '.join(slugs[:2]) or 'nothing'}"
        elif raw_count > len(eps):
            flag = "  <-- parser missed some"
        print(f"{raw_count:>4} {len(eps):>6} {last:>6}  {episode:>10}  {title}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
