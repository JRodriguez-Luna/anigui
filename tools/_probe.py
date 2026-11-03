"""Temporary CI probe (removed in the next commit)."""
import sys
sys.path.insert(0, ".")
from core.anilist import AniListClient
al = AniListClient()
for q in ["Tokyo Godfathers", "Toradora!", "K-ON!", "Kaguya-sama: Love is War Season 2", "Yuru Camp", "Sword Art Online",
          "Komi Can't Communicate", "Ouran High School Host Club", "Cardcaptor Sakura", "Kimi ni Todoke",
          "Hayate the Combat Butler", "Gintama", "Spy x Family Season 2", "Horimiya", "Lucky Star", "Nisekoi"]:
    try:
        ms = al.search(q, per_page=3)
        print(f"::notice title=probe::{q} -> " + "; ".join(f"{m.anilist_id} {m.display_title} ({m.format} {m.year})" for m in ms))
    except Exception as e:
        print(f"::notice title=probe::{q} failed {e!r}")
