"""Temporary CI probe (removed in the next commit)."""
import os, subprocess, sys
sys.path.insert(0, ".")
from core.hianime import HianimeClient
from core.anilist import AniListClient
from core.stills import EpisodeStills
def note(m): print(f"::notice title=probe::{m}"[:3000])
env = {**os.environ, "ANI_CLI_PLAYER": "debug", "ANI_CLI_HIST_DIR": "/tmp/h"}
for query, ep, mode in (("my hero academia season 5", "1", "dub"), ("my hero academia season 5", "2", "dub"),
                        ("my hero academia season 6", "1", "dub"), ("my hero academia season 6", "4", "dub")):
    args = ["ani-cli", "-S", "1", "-e", ep] + (["--dub"] if mode == "dub" else []) + [query]
    p = subprocess.run(args, capture_output=True, text=True, timeout=120, env=env)
    out = (p.stdout + " | ERR: " + p.stderr).replace("\n", " ")
    note(f"{query} ep {ep} {mode}: rc={p.returncode} {out[:900]}")
c = HianimeClient()
al = AniListClient()
eps = c.episodes("my-hero-academia-season-6-961")
note("S6 hianime titles: " + " | ".join(f"{e.number}: {e.title}" for e in eps[:8]))
m = [x for x in al.search("My Hero Academia Season 6", per_page=3)]
note("S6 anilist: " + str([(x.anilist_id, x.mal_id, x.display_title) for x in m]))
aid, mal = m[0].anilist_id, m[0].mal_id
se = al.streaming_episodes(aid)
note("S6 streamingEpisodes: " + " | ".join(t for t, _ in se[:8]))
st = EpisodeStills(al)
found = st.for_episodes(aid, mal, [(e.number, e.title) for e in eps[:8]])
note("S6 stills: " + " | ".join(f"{k}: {v}" for k, v in sorted(found.items(), key=lambda kv: float(kv[0]))))
