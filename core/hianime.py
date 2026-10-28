"""Search and episode lists from hianime.at, ported from ani-cli 5.1.6.

Mirrors ani-cli's `hianime_search` and `hianime_episodes` so result order matches
what `ani-cli -S <n>` selects. Requests go through the same curl binary and TLS
flags ani-cli uses, so Cloudflare sees identical traffic from both.
"""

from __future__ import annotations

import html
import re
import subprocess
from dataclasses import dataclass

from .env import find_curl, is_macos

BASE_URL = "https://hianime.at"
SEARCH_URL = BASE_URL + "/search?keyword={}"
EPISODES_URL = BASE_URL + "/api/theme/episode/list/{}"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_CIPHERS = (
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305"
)
_TLS13_CIPHERS = "TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256"

# Characters allowed in a query. ani-cli puts the query into the URL unescaped,
# so anything else could make its search differ from ours and break -S indexing.
_QUERY_STRIP = re.compile(r"[^\w\s\-'.!]", re.UNICODE)

_SEARCH_ITEM = re.compile(
    r'<h3 class="film-name">\s*<a href="[^"]*/([^"/]*)"\s*title="([^"]*)"'
)
_POSTER = re.compile(r'<img[^>]*(?:data-src|src)="([^"]+)"[^>]*class="[^"]*film-poster-img')
_POSTER_ALT = re.compile(r'class="[^"]*film-poster-img[^"]*"[^>]*(?:data-src|src)="([^"]+)"')
_EP_TITLE = re.compile(r'title="([^"]*)"[^>]*$')


class HianimeError(RuntimeError):
    """Network or parsing failure talking to hianime."""


class CloudflareBlocked(HianimeError):
    """Cloudflare served a challenge page instead of results."""


class SiteUnreachable(HianimeError):
    """No usable answer from hianime at all: DNS failure, refused or reset connection,
    timeout, TLS failure, or an ISP block page. Usually fixed by a VPN."""


UNREACHABLE_MESSAGE = (
    "Can't reach hianime from your network. Some internet providers block it. "
    "Turn on a VPN such as Cloudflare WARP, then try again."
)

# curl exit codes that mean "never got a real answer from the site"
# 6 resolve host, 7 connect, 28 timeout, 35 TLS handshake, 52 empty reply,
# 56 receive failure (often a reset), 60 certificate problem (block-page interception)
NETWORK_EXIT_CODES = {6, 7, 28, 35, 52, 56, 60}


@dataclass(frozen=True)
class FetchResult:
    curl_exit: int
    status: int | None
    body: str


@dataclass(frozen=True)
class SearchResult:
    index: int          # 1-based, matches `ani-cli -S <index>`
    anime_id: str       # e.g. "frieren-beyond-journeys-end-18542"
    title: str
    poster: str | None  # best effort; AniList fills gaps in step 2


@dataclass(frozen=True)
class Episode:
    number: str         # string on purpose: specials can be "12.5"
    episode_id: str
    title: str | None


def normalize_query(query: str) -> str:
    """Clean a query so this client and ani-cli search for exactly the same thing."""
    cleaned = _QUERY_STRIP.sub(" ", query)
    return " ".join(cleaned.split())


class HianimeClient:
    def __init__(self, curl: str | None = None, timeout: float = 10.0) -> None:
        self.curl = curl or find_curl()
        self.timeout = timeout

    # -- HTTP -----------------------------------------------------------------

    def fetch(self, url: str, referer: str | None = None) -> FetchResult:
        """Raw request: never raises for network trouble; callers classify the result."""
        cmd = [self.curl, "-sL", "-A", USER_AGENT, "--max-time", str(int(self.timeout))]
        if is_macos():
            cmd += ["--ciphers", _CIPHERS, "--tls13-ciphers", _TLS13_CIPHERS]
        cmd += ["-w", " %{http_code}", url]
        if referer:
            cmd += ["-e", referer]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout + 5)
        except subprocess.TimeoutExpired:
            return FetchResult(28, None, "")
        body, _, code = proc.stdout.rpartition(" ")
        status = int(code) if code.isdigit() and code != "000" else None
        return FetchResult(proc.returncode, status, body)

    def _get(self, url: str, referer: str | None = None) -> str:
        r = self.fetch(url, referer)
        if r.curl_exit in NETWORK_EXIT_CODES or (r.curl_exit != 0 and r.status is None):
            raise SiteUnreachable(UNREACHABLE_MESSAGE)
        if r.curl_exit != 0:
            raise HianimeError(f"Could not fetch {url} (HTTP {r.status}; curl exit {r.curl_exit})")
        if "just a moment" in r.body[:4000].lower():
            hint = " Install curl-impersonate: brew install curl-impersonate" if self.curl.endswith("curl") else ""
            raise CloudflareBlocked("Blocked by Cloudflare." + hint)
        if r.status in (403, 451) or (r.status and r.status >= 500 and "hianime" not in r.body.lower()):
            raise SiteUnreachable(UNREACHABLE_MESSAGE)
        if not (r.status and 200 <= r.status < 300):
            raise HianimeError(f"HTTP {r.status} from {url}")
        return r.body

    # -- API ------------------------------------------------------------------

    def search(self, query: str) -> list[SearchResult]:
        q = normalize_query(query)
        if not q:
            return []
        page = self._get(SEARCH_URL.format(q.replace(" ", "+")))
        return parse_search(page)

    def episodes(self, anime_id: str) -> list[Episode]:
        numeric_id = anime_id.rsplit("-", 1)[-1]
        page = self._get(EPISODES_URL.format(numeric_id))
        return parse_episodes(page, anime_id)


# -- Parsers (pure functions, unit-tested against fixtures) --------------------

def parse_search(page: str) -> list[SearchResult]:
    # The "top 10" sidebar repeats the result markup; ani-cli cuts it off too.
    cut = page.find('id="main-sidebar"')
    if cut != -1:
        page = page[:cut]
    chunks = page.replace("\n", " ").split('<div class="film-detail">')

    results: list[SearchResult] = []
    for prev, chunk in zip(chunks, chunks[1:]):
        m = _SEARCH_ITEM.search(chunk)
        if not m:
            continue
        poster = _POSTER.search(prev) or _POSTER_ALT.search(prev)
        results.append(
            SearchResult(
                index=len(results) + 1,
                anime_id=m.group(1),
                title=html.unescape(m.group(2)),
                poster=poster.group(1) if poster else None,
            )
        )
    return results


def parse_episodes(page: str, anime_id: str) -> list[Episode]:
    chunks = page.replace("\\", "").split("ep-item")
    pattern = re.compile(
        r'data-number="([^"]*)".*data-id="([0-9]+)".*/watch/' + re.escape(anime_id) + r"[?]ep="
    )
    episodes: list[Episode] = []
    for prev, chunk in zip(chunks, chunks[1:]):
        m = pattern.search(chunk.split("\n", 1)[0])
        if not m:
            continue
        t = _EP_TITLE.search(prev)
        episodes.append(
            Episode(
                number=m.group(1),
                episode_id=m.group(2),
                title=html.unescape(t.group(1)) if t else None,
            )
        )
    return episodes
