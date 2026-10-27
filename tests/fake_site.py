"""Offline stand-in for hianime.at.

Builds a bin directory with a fake `curl` (plus the curl-impersonate names
ani-cli prefers) that serves fixture responses by URL, and a stub `fzf` so
ani-cli's dependency check passes. The real ani-cli script then runs its full
scraping flow (search, episodes, servers, embed deobfuscation, m3u8) offline.
"""

from __future__ import annotations

import base64
import json
import os
import stat
import sys
from pathlib import Path

ANIME_ID = "frieren-beyond-journeys-end-18542"
TITLE_HTML = "Frieren: Beyond Journey&#039;s End"
TITLE = "Frieren: Beyond Journey's End"
EMBED_HOST = "https://embed.example"
XOR_KEY = b"otaku-embed-v1"

FAKE_CURL = r'''#!/usr/bin/env python3
import json, os, sys
site = os.environ["FAKE_SITE_DIR"]
manifest = json.load(open(os.path.join(site, "manifest.json")))
args = sys.argv[1:]
takes_value = {"-A", "-e", "-w", "--max-time", "--ciphers", "--tls13-ciphers", "-o", "--data", "-G"}
url, write_out, i = None, "", 0
while i < len(args):
    a = args[i]
    if a in takes_value:
        if a == "-w":
            write_out = args[i + 1]
        i += 2
        continue
    if a.startswith("http") and url is None:
        url = a
    i += 1
with open(os.path.join(site, "requests.log"), "a") as log:
    log.write(" ".join(args) + "\n")
entry = manifest.get(url) or manifest.get(url.lower())  # real search is case-insensitive
if entry is None:
    sys.stdout.write("not found" + write_out.replace("%{http_code}", "404"))
    sys.exit(0)
body = open(os.path.join(site, entry["file"]), encoding="utf-8").read()
sys.stdout.write(body + write_out.replace("%{http_code}", str(entry.get("code", 200))))
'''


def _search_page() -> str:
    items = []
    titles = [(ANIME_ID, TITLE_HTML), ("frieren-mini-anime-19001", "Frieren Mini &amp; Friends")]
    for slug, title in titles:
        items.append(f"""
<div class="flw-item">
  <div class="film-poster">
    <img data-src="https://img.example/{slug}.jpg" class="film-poster-img lazyload" alt="x">
  </div>
  <div class="film-detail">
    <h3 class="film-name">
      <a href="/{slug}" title="{title}" class="dynamic-name">{title}</a>
    </h3>
  </div>
</div>""")
    sidebar = """
<div id="main-sidebar">
  <div class="film-detail"><h3 class="film-name"><a href="/one-piece-100" title="One Piece">One Piece</a></h3></div>
</div>"""
    return "<html><head><title>Search</title></head><body><div class=\"film_list-wrap\">" + "".join(items) + "</div>" + sidebar + "</body></html>"


def _episodes_json(slug: str, numbers: list[str]) -> str:
    links = "".join(
        f'<a title="Episode {n} title" class="ssl-item ep-item" data-number="{n}" data-id="{100 + i}" '
        f'href="/watch/{slug}?ep={100 + i}"><div>{n}</div></a>'
        for i, n in enumerate(numbers, start=1)
    )
    return json.dumps({"status": True, "html": f'<div class="ss-list">{links}</div>'})


def _servers_json(ep_id: int) -> str:
    def item(kind: str, name: str, url: str) -> str:
        h = base64.b64encode(url.encode()).decode()
        return (f'<div class="item server-item" data-type="{kind}" data-id="{ep_id}" '
                f'data-server-name="{name}" data-hash="{h}"><a>{name}</a></div>')
    html = "".join([
        item("sub", "OtherServer", "https://other.example/x"),
        item("sub", "ZokoAnime", f"{EMBED_HOST}/mal/52991/ep/{ep_id}/sub"),
        item("dub", "ZokoAnime", f"{EMBED_HOST}/mal/52991/ep/{ep_id}/dub"),
    ])
    return json.dumps({"status": True, "html": html})


def _embed_page(master: str, sub: str) -> str:
    payload = json.dumps({
        "src": master,
        "subtitles": [
            {"src": "https://cdn.example/subs/es.vtt", "label": "Spanish", "default": False},
            {"src": sub, "label": "English", "default": True},
        ],
    }, separators=(",", ":")).encode()
    xored = bytes(b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(payload))
    blob = base64.b64encode(xored).decode()
    return f'<html><script>window.__P="{blob}";</script></html>'


def _master_playlist() -> str:
    return "\n".join([
        "#EXTM3U",
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="English",DEFAULT=YES,URI="audio/eng.m3u8"',
        '#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080,CODECS="avc1.640028"',
        "1080/index.m3u8",
        '#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720,CODECS="avc1.64001f"',
        "720/index.m3u8",
        '#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=854x480,CODECS="avc1.64001e"',
        "480/index.m3u8",
        "",
    ])


def build(root: Path, cloudflare: bool = False) -> dict[str, str]:
    """Create the fake site under root. Returns env vars to apply."""
    site = root / "site"
    bin_dir = root / "bin"
    site.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, dict] = {}

    def serve(url: str, body: str, code: int = 200) -> None:
        name = f"r{len(manifest)}.txt"
        (site / name).write_text(body, encoding="utf-8")
        manifest[url] = {"file": name, "code": code}

    search_body = "<html><title>Just a moment...</title></html>" if cloudflare else _search_page()
    for q in ("frieren", "frieren+beyond"):
        serve(f"https://hianime.at/search?keyword={q}", search_body, 403 if cloudflare else 200)
    serve("https://hianime.at/api/theme/episode/list/18542", _episodes_json(ANIME_ID, ["1", "2", "3"]))
    serve("https://hianime.at/api/theme/episode/list/19001", _episodes_json("frieren-mini-anime-19001", ["1"]))

    for ep_id in (101, 102, 103):
        serve(f"https://hianime.at/api/theme/episode/servers?episodeId={ep_id}", _servers_json(ep_id))
        for kind in ("sub", "dub"):
            master = f"https://cdn.example/hls/{ep_id}/{kind}/master.m3u8"
            serve(f"{EMBED_HOST}/mal/52991/ep/{ep_id}/{kind}", _embed_page(master, f"https://cdn.example/subs/{ep_id}-en.vtt"))
            serve(master, _master_playlist())

    (site / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    curl = bin_dir / "curl"
    curl.write_text(FAKE_CURL.replace("#!/usr/bin/env python3", f"#!{sys.executable}"), encoding="utf-8")
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    for alias in ("curl_firefox135", "curl_chrome136", "curl_chrome116", "curl_ff117"):
        link = bin_dir / alias
        if not link.exists():
            link.symlink_to(curl)
    fzf = bin_dir / "fzf"
    fzf.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fzf.chmod(0o755)

    return {
        "FAKE_SITE_DIR": str(site),
        "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
    }
