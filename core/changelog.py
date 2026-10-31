"""What changed in each version, in plain words. Shown in the What's New window.

Newest first. Add an entry here with every release; tests check the current
version has one.
"""

from __future__ import annotations

from dataclasses import dataclass

from .setup import parse_version


@dataclass(frozen=True)
class Change:
    title: str
    text: str


@dataclass(frozen=True)
class Release:
    version: str
    date: str          # "Month D, YYYY"
    changes: tuple[Change, ...]


RELEASES: tuple[Release, ...] = (
    Release("1.4.0", "October 31, 2026", (
        Change("Airing calendar", "A new Calendar page (⌘5) with this week's episodes, a column per day, in your "
                                  "time zone. WATCH NOW marks episodes that are already on hianime."),
        Change("My shows or everything", "See just the shows you follow, or switch to All airing to discover "
                                         "something new. Right-click any show to add it to My List."),
        Change("Any week", "Flip to last week or next week with the arrows."),
    )),
    Release("1.3.0", "October 31, 2026", (
        Change("More like this", "Below the episodes on every show page: sequels, prequels, movies and spin-offs, "
                                 "then shows other fans recommend."),
        Change("Search filters", "Filter by genre, year, season, format and airing status, and sort by popularity "
                                 "or rating. Works without typing too, so you can just browse."),
        Change("Your Stats", "A new page (⌘4) with time watched, episodes, your daily streak, the last 12 weeks, "
                             "top genres and most-watched shows."),
        Change("One-click updates", "From now on, updating is one click: Update Now downloads the new version, "
                                    "checks it, installs it and restarts AniGUI. (This update is the last one you "
                                    "install by hand.)"),
        Change("Back between shows", "Open a show from another show's page, and Back takes you to the one you "
                                     "came from."),
    )),
    Release("1.2.0", "October 30, 2026", (
        Change("Settings", "Everything in one place (⌘,): player, sub or dub, quality, auto-play, skipping, "
                           "new-episode alerts, history, connection and updates."),
        Change("Skip intros, endings and recaps", "Turn it on in Settings → Skipping. Works with IINA and mpv, "
                                                  "with nothing extra to install. Episodes nobody has timed yet "
                                                  "play normally."),
        Change("New episode alerts", "When a show in My List gets a new episode, it appears at the top of Home "
                                     "with a NEW badge, and you get a Mac notification."),
        Change("Clear watch history", "Use Clear next to Continue Watching, right-click a show to remove just "
                                      "that one, or History → Clear Watch History. My List stays."),
        Change("Terminal history is your choice", "Shows you watched with ani-cli in Terminal are only added to "
                                                  "Continue Watching if you say so: in Setup, or Settings → History. "
                                                  "(If you've used AniGUI before, nothing changes.)"),
        Change("What's New", "This window. It shows up once after each update, and anytime from the AniGUI menu."),
        Change("Fixes", "If the player you picked isn't installed, AniGUI uses the other one instead of failing. "
                        "Setup offers to install IINA when you've picked it, and still finds IINA when GitHub "
                        "is busy."),
    )),
    Release("1.1.0", "October 28, 2026", (
        Change("Setup assistant", "AniGUI installs ani-cli and IINA for you. No Homebrew or Terminal needed."),
        Change("Connection check", "Finds out whether hianime or its video servers are blocked on your network, "
                                   "and suggests Cloudflare WARP or your own VPN."),
        Change("Update pop-ups", "AniGUI tells you when a new version of AniGUI or ani-cli is out."),
        Change("Dub fallback", "Episodes that don't have a dub yet play subbed instead of failing."),
    )),
    Release("1.0.0", "October 27, 2026", (
        Change("First release", "Browse trending and seasonal anime, search, keep a list, and watch in IINA or "
                                "mpv with resume, progress tracking and auto-play."),
    )),
)


def since(version: str | None) -> list[Release]:
    """Releases newer than `version` (all of them for None)."""
    if not version:
        return list(RELEASES)
    return [r for r in RELEASES if parse_version(r.version) > parse_version(version)]
