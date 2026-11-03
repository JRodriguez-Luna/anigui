"""Temporary CI probe (removed in the next commit): find Christmas episodes by their titles."""
import json, re, sys, urllib.parse
sys.path.insert(0, ".")
from core import http
from core.anilist import AniListClient
def note(m): print(f"::notice title=probe::{m}"[:3800])
al = AniListClient()
SHOWS = ["Azumanga Daioh", "Sailor Moon R", "Is the Order a Rabbit??", "Is the Order a Rabbit? BLOOM",
         "Strike Witches 2", "School Rumble", "White Album 2", "Amagami SS", "Shirokuma Cafe", "Sakura Trick",
         "Love Live! Sunshine!!", "Laid-Back Camp Season 2", "Kimi ni Todoke 2nd Season", "Hello!! Kiniro Mosaic",
         "My Teen Romantic Comedy SNAFU TOO!", "ReLIFE", "Haganai", "Clannad After Story", "Kaguya-sama Love is War",
         "Fruits Basket 2019", "Kiss Him Not Me", "Monthly Girls' Nozaki-kun", "Kemono Michi", "Toaru Kagaku no Railgun",
         "A Certain Magical Index", "Durarara!!", "Natsume Yuujinchou", "Sweetness and Lightning", "Usagi Drop",
         "Hinamatsuri", "Kotoura-san", "Charlotte", "Ano Hana", "Tanaka-kun is Always Listless", "Pokemon",
         "Toradora SOS", "Asobi Asobase", "Kaguya-sama Love is War Ultra Romantic", "Mob Psycho 100",
         "Golden Time", "Ouran High School Host Club", "Kanojo mo Kanojo", "Akiba Maid War", "Super Cub",
         "Yuri!!! on Ice", "Bunny Drop", "Hyouka", "Komi Can't Communicate Season 2", "Sound! Euphonium 2"]
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
