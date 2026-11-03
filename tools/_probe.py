"""Temporary CI probe (removed in the next commit): are the advent episodes on hianime?"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, ".")
from core.anilist import AniListClient
from core.catalog import Catalog
from core.holiday import CHRISTMAS_EPISODES, CHRISTMAS_IDS, XmasEpisode
from core.store import Store
def note(m): print(f"::notice title=probe::{m}"[:3800])
al = AniListClient()
cat = Catalog(Store(Path(tempfile.mkdtemp()) / "t.db"), anilist=al)
EXTRA = (XmasEpisode(12815, '37', "Polar Bear's Cafe", ''), XmasEpisode(10495, '7', 'YuruYuri', ''),
         XmasEpisode(687, '37', 'Tokyo Mew Mew', ''), XmasEpisode(351, '44', 'Ojamajo Doremi Sharp', ''),
         XmasEpisode(918, '200', 'Gintama', ''), XmasEpisode(516, '90', 'Sgt. Frog', ''))
CHRISTMAS_EPISODES = EXTRA
ids = sorted({e.anilist_id for e in CHRISTMAS_EPISODES} | set(CHRISTMAS_IDS))
found = al.airing(ids)
note(f"anilist found {len(found)}/{len(ids)}; missing {[i for i in ids if i not in found]}")
for e in CHRISTMAS_EPISODES:
    try:
        m = found.get(e.anilist_id)
        hit = cat.find_streamable(m) if m else None
        if not hit:
            note(f"MISS {e.show} ep {e.episode}: not on hianime"); continue
        _id, _t, eps = cat.episodes_for(hit.anime_id, hit.title)
        nums = [x.number for x in eps]
        ep = next((x for x in eps if x.number == e.episode), None)
        note(f"{'OK  ' if ep else 'NOEP'} {e.show} ep {e.episode} -> {hit.anime_id} ({len(nums)} eps) title={ep.title if ep else None!r}")
    except Exception as exc:
        note(f"FAIL {e.show}: {exc!r}")
