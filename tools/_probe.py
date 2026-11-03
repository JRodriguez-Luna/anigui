"""Temporary CI probe (removed in the next commit): find Christmas episodes by their titles."""
import json, re, sys, urllib.parse
sys.path.insert(0, ".")
from core import http
from core.anilist import AniListClient
def note(m): print(f"::notice title=probe::{m}"[:3800])
al = AniListClient()
SHOWS = ["Toradora!", "K-ON!", "K-ON!! Season 2", "Laid-Back Camp", "Kaguya-sama Love is War Season 2",
         "Komi Can't Communicate", "Sword Art Online", "Ouran High School Host Club", "Kimi ni Todoke",
         "Cardcaptor Sakura", "Hayate the Combat Butler", "Gintama", "Lucky Star", "Clannad", "Nisekoi",
         "Horimiya", "Spy x Family Season 2", "Kiniro Mosaic", "Non Non Biyori Repeat", "Love Live! School Idol Project",
         "Hidamari Sketch", "Yuru Yuri", "Gabriel DropOut", "Nichijou", "Love, Chunibyo & Other Delusions",
         "Saekano", "Golden Time", "Your Lie in April", "Wotakoi", "My Teen Romantic Comedy SNAFU",
         "My Love Story!!", "Tsurezure Children", "Tonikawa Over the Moon for You", "Rent-a-Girlfriend",
         "The Quintessential Quintuplets", "Bocchi the Rock!", "Spy x Family", "Kanon 2006", "Toradora",
         "Teasing Master Takagi-san", "Rascal Does Not Dream of Bunny Girl Senpai", "Aria the Animation",
         "Natsume's Book of Friends", "Fruits Basket", "Lovely Complex", "Maid Sama!", "Plastic Memories",
         "Aho Girl", "Bakemonogatari", "Kobayashi's Dragon Maid", "Shirobako", "The Disastrous Life of Saiki K."]
WORDS = re.compile(r"christmas|xmas|santa|holy night|silent night|eve\b|クリスマス|聖夜", re.I)
seen = set()
for title in SHOWS:
    try:
        m = al.search(title, per_page=1)
        if not m or m[0].anilist_id in seen or not m[0].mal_id:
            continue
        m = m[0]; seen.add(m.anilist_id)
        r = http.request("https://kitsu.app/api/edge/mappings?filter[externalSite]=myanimelist/anime&filter[externalId]=%d&include=item" % m.mal_id, headers={"Accept": "application/vnd.api+json"}, timeout=20)
        inc = [x for x in json.loads(r.body).get("included", []) if x.get("type") == "anime"]
        if not inc:
            note(f"{m.display_title}: no kitsu"); continue
        kid = inc[0]["id"]
        hits = []
        for off in range(0, 200, 20):
            r = http.request(f"https://kitsu.app/api/edge/anime/{kid}/episodes?page[limit]=20&page[offset]={off}&sort=number", headers={"Accept": "application/vnd.api+json"}, timeout=20)
            data = json.loads(r.body).get("data", [])
            for e in data:
                a = e["attributes"]
                names = " / ".join(v for v in [a.get("canonicalTitle")] + list((a.get("titles") or {}).values()) if v)
                if WORDS.search(names or ""):
                    hits.append(f"ep {a.get('number')}: {a.get('canonicalTitle')}")
            if len(data) < 20:
                break
        note(f"{m.anilist_id} {m.display_title} ({m.format} {m.episodes} eps): {hits if hits else 'none'}")
    except Exception as e:
        note(f"{title}: failed {e!r}")
