"""Temporary CI probe (removed in the next commit)."""
import re, sys
sys.path.insert(0, ".")
from core.hianime import HianimeClient, BASE_URL
c = HianimeClient()
def note(m): print(f"::notice title=probe::{m}")
for q in ("my hero academia season 5", "my hero academia season 6", "frieren"):
    rs = [r for r in c.search(q)][:3]
    note(f"search {q}: {[r.anime_id for r in rs]}")
    r = rs[0]
    eps = c.episodes(r.anime_id)
    for ep in eps[:3]:
        f = c.fetch(f"{BASE_URL}/api/theme/episode/servers?episodeId={ep.episode_id}")
        body = f.body.replace('\\\\"', '"').replace('\\"', '"')
        items = re.findall(r'server-item[^>]*?data-type="([^"]+)"[^>]*?data-server-name="([^"]+)"', body)
        if not items:
            items = re.findall(r'data-type="([^"]+)".{0,200}?data-server-name="([^"]+)"', body)
        note(f"  {r.anime_id} ep {ep.number}: HTTP {f.status} servers {items} | {body[:200]!r}")
