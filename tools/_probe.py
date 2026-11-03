"""Temporary CI probe (removed in the next commit)."""
import collections, json, re, sys
sys.path.insert(0, ".")
from core import fillers, http

def note(msg):
    print(f"::notice title=probe::{msg}")

idx = fillers._fetch(fillers.SHOWS_URL).body.decode("utf-8", "replace")
shows = fillers.parse_shows(idx)
note(f"index bytes={len(idx)} shows={len(shows)} 'one piece'->{shows.get('one piece')}")
hits = [m for m in fillers._SHOW_LINK.findall(idx) if "one piece" in fillers.normalize(m[1])]
note(f"one piece links: {hits[:8]}")
resp = fillers._fetch(fillers.SHOW_URL.format(slug="one-piece"))
page = resp.body.decode("utf-8", "replace")
note(f"one-piece status={resp.status} bytes={len(page)} rows={len(fillers._EPISODE_ROW.findall(page))}")
c = collections.Counter(cls for cls, _ in fillers._EPISODE_ROW.findall(page))
note(f"row classes: {dict(c.most_common(8))}")
trs = re.findall(r'<tr[^>]*>', page)
note(f"tr tags={len(trs)} sample={trs[1:5]}")
k = fillers.parse_episodes(page)
note(f"parsed fillers={len(k)} first={sorted(k, key=float)[:12]}")
g = fillers.FillerGuide()
info = g.for_titles(["ONE PIECE", "One Piece"])
note(f"guide: fillers={len(info.kinds)} complete={info.complete}")
i = page.find('id="eps-54"')
note("around 54: " + page[max(0, i-300):i+200].replace("\n", " ")[:480])
q = '{Page(perPage:6){media(search:"Nukitashi",type:ANIME){id isAdult title{romaji english}}}}'
r = http.request("https://graphql.anilist.co", data=json.dumps({"query": q}).encode(),
                 headers={"Content-Type": "application/json", "Accept": "application/json"}, timeout=20)
note("anilist nukitashi: " + r.body.decode()[:400])
