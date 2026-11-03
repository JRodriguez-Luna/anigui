"""Temporary CI probe (removed in the next commit): replicate ani-cli's stream lookup and
print the master playlists for sub and dub."""
import base64, json, re, sys
sys.path.insert(0, ".")
from core.hianime import HianimeClient, BASE_URL
def note(m): print(f"::notice title=probe::{m}"[:3500])
KEY = b"otaku-embed-v1"
c = HianimeClient()
def master(anime_id, number, mode):
    eps = {e.number: e.episode_id for e in c.episodes(anime_id)}
    body = c.fetch(f"{BASE_URL}/api/theme/episode/servers?episodeId={eps[number]}").body.replace('\\"', '"')
    m = re.search(r'data-type="' + mode + r'"[^>]*data-server-name="ZokoAnime"[^>]*data-hash="([^"]*)"', body)
    embed = base64.b64decode(m.group(1)).decode()
    refr = re.sub(r"^(https?://[^/]*).*", r"\1/", embed)
    page = c.fetch(embed).body
    blob = re.search(r'window\.__P="([^"]*)"', page).group(1)
    raw = base64.b64decode(blob)
    js = bytes(b ^ KEY[i % len(KEY)] for i, b in enumerate(raw)).decode()
    src = re.search(r'"src":"([^"]*\.m3u8[^"]*)"', js).group(1)
    pl = c.fetch(src, referer=refr).body
    return src, pl, js
for anime_id, number in (("my-hero-academia-season-5-1870", "1"), ("my-hero-academia-season-5-1870", "2"),
                         ("my-hero-academia-season-6-961", "1")):
    for mode in ("sub", "dub"):
        try:
            src, pl, js = master(anime_id, number, mode)
            lines = [l for l in pl.splitlines() if l.startswith("#EXT-X-MEDIA") or l.startswith("#EXT-X-STREAM")]
            tracks = re.findall(r'"(?:label|lang|language)":"([^"]*)"', js)
            note(f"{anime_id} ep {number} {mode}: {src[-60:]} | {lines} | labels {tracks[:8]}")
        except Exception as e:
            note(f"{anime_id} ep {number} {mode}: failed {e!r}")
