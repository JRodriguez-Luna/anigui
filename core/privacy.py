"""What leaves your Mac (2.0).

Every place AniGUI connects to, what it sends there and why, plus a live record of the hosts it
actually contacted since it opened (counts only: no addresses, searches or show names are kept).
Your lists, ratings, notes, history and settings never leave this Mac.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Destination:
    name: str
    hosts: tuple[str, ...]      # host suffixes this covers
    sends: str                  # what goes out
    why: str
    when: str


DESTINATIONS: tuple[Destination, ...] = (
    Destination("AniList", ("anilist.co",),
                "Search words you type, and the AniList ids of shows you open. No account, no sign-in.",
                "Show details, covers, seasons, trending and recommendations.",
                "When you browse, search or open a show."),
    Destination("hianime", ("hianime.at",),
                "The show and episode you pick (through ani-cli, like the terminal).",
                "Finding the episode list and the video for an episode.",
                "When you open a show or press play."),
    Destination("Video hosts", (),
                "A normal video request for the episode you play (from the built-in player, IINA or mpv).",
                "Streaming the episode.",
                "Only while an episode plays."),
    Destination("Kitsu and ani.zip", ("kitsu.app", "kitsu.io", "ani.zip"),
                "The AniList id of the show you're looking at.",
                "Episode pictures, titles, dates and lengths.",
                "When you open a show's episodes."),
    Destination("AniSkip", ("aniskip.com",),
                "The show's MyAnimeList id and the episode number.",
                "Intro and ending times, for Skip intro.",
                "When an episode starts."),
    Destination("Anime Filler List", ("animefillerlist.com",),
                "The show's name.",
                "Which episodes are filler.",
                "When you open a show that has fillers."),
    Destination("Image servers", ("anili.st", "s4.anilist.co", "img.anili.st", "flawlessfiles.com",
                                  "media.kitsu.app", "media.kitsu.io"),
                "Requests for cover and episode pictures.",
                "Showing artwork.",
                "As pictures come into view (then they're kept on this Mac)."),
    Destination("GitHub", ("github.com", "api.github.com", "githubusercontent.com", "objects.githubusercontent.com"),
                "Which AniGUI version you have.",
                "Checking for updates and downloading them (each one signed and checked), and setting up ani-cli or IINA.",
                "When AniGUI opens (once a day at most) or you press Check for Updates."),
)

NEVER_SENT = (
    "Your lists, ratings, tags and notes",
    "What you watched and when (your history and timeline)",
    "Your settings and how you've made AniGUI yours",
    "Anything that identifies you: there are no accounts, no analytics and no tracking",
)


class ConnectionLog:
    """Hosts contacted since AniGUI opened, with counts. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hosts: dict[str, list] = {}       # host -> [count, last time]

    def record(self, url: str) -> None:
        host = (urlsplit(url).hostname or "").lower()
        if not host:
            return
        with self._lock:
            entry = self._hosts.setdefault(host, [0, 0.0])
            entry[0] += 1
            entry[1] = time.time()

    def snapshot(self) -> list[tuple[str, int, float, str]]:
        """(host, count, last time, which destination it belongs to), most recent first."""
        with self._lock:
            items = [(h, c, t) for h, (c, t) in self._hosts.items()]
        return sorted(((h, c, t, destination_for(h)) for h, c, t in items), key=lambda x: -x[2])

    def clear(self) -> None:
        with self._lock:
            self._hosts.clear()


def destination_for(host: str) -> str:
    host = host.lower()
    for d in DESTINATIONS:
        if any(host == s or host.endswith("." + s) for s in d.hosts):
            return d.name
    return "Video hosts"


LOG = ConnectionLog()
