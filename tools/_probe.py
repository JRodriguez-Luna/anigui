"""Temporary CI probe (removed in the next commit): find Christmas episodes by their titles."""
import json, re, sys, urllib.parse
sys.path.insert(0, ".")
from core import http
from core.anilist import AniListClient
def note(m): print(f"::notice title=probe::{m}"[:3800])
al = AniListClient()
SHOWS = ["Sword Art Online", "Kaguya-sama Love is War Season 2", "Spy x Family", "Nisekoi", "Silver Spoon",
         "Barakamon", "Bakuman", "Tamako Market", "Love Live! School Idol Project 2nd Season", "Hanasaku Iroha",
         "Aria the Natural", "Squid Girl", "Space Brothers", "Gakkou Gurashi", "Chihayafuru", "Little Busters",
         "Sket Dance", "Daily Lives of High School Boys", "Nisemonogatari", "Keroro Gunsou", "Chi's Sweet Home",
         "Yu Yu Hakusho", "Shakugan no Shana II", "To Love-Ru", "Sakurasou no Pet na Kanojo", "Oreimo",
         "Ef: A Tale of Memories", "Little Witch Academia", "Tsuki ga Kirei", "Tari Tari", "Kamisama Kiss",
         "Inu x Boku SS", "Hataraku Maou-sama", "Natsume Yuujinchou Shi", "Pokemon", "Ojamajo Doremi",
         "Wandering Son", "Saki", "Kemono Friends", "Princess Tutu", "Chobits", "Fullmetal Panic? Fumoffu",
         "Kanokon", "Mahoraba", "Toradora", "The Melancholy of Haruhi Suzumiya 2009", "Lucky Star OVA",
         "Rozen Maiden", "Sailor Moon", "Tokyo Mew Mew", "Ojamajo Doremi Sharp", "Detective Conan"]
WORDS = re.compile(r"christmas|xmas|santa|reindeer|holy night|silent night|christmas eve|クリスマス|聖夜|サンタ|イブ", re.I)
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
        for off in range(0, 300, 20):
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
