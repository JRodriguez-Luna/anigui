"""Temporary CI probe (removed in the next commit)."""
import sys
sys.path.insert(0, ".")
from core.hianime import HianimeClient, EPISODES_URL

def note(msg):
    print(f"::notice title=probe::{msg}")

c = HianimeClient()
for q in ("frieren", "one piece", "naruto"):
    try:
        rs = c.search(q)
        note(f"search {q}: {[(r.anime_id) for r in rs[:6]]}")
        for r in rs[:3]:
            f = c.fetch(EPISODES_URL.format(r.anime_id.rsplit('-', 1)[-1]))
            note(f"  {r.anime_id}: HTTP {f.status} bytes={len(f.body)} eps={len(c.episodes(r.anime_id)) if f.status == 200 else '-'}")
    except Exception as e:
        note(f"search {q} failed: {e!r}")
for i in ("1665", "18542", "100"):
    f = c.fetch(EPISODES_URL.format(i))
    note(f"list {i}: HTTP {f.status} {f.body[:160]!r}")
