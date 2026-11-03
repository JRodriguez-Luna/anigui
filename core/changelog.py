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
    Release("1.8.6", "November 2, 2026", (
        Change("ⓘ panel fits", "In a wide window, the \"What these tags mean\" panel on a show page cut off its "
                               "last lines. It now gets the room its text needs at any window size."),
    )),
    Release("1.8.5", "November 2, 2026", (
        Change("Adult shows are flagged 18+", "Shows AniList marks as adult (Nukitashi, for example) never matched, "
                                               "so they had no poster, no details and no 18+ badge. They now match, "
                                               "get their artwork, and are blurred and asked about like any 18+ show."),
        Change("One Piece fillers", "One Piece was matched to the One Pace fan edit's list and showed 1 filler. "
                                    "It now shows all 94, and Hide and Skip fillers work on it."),
        Change("Go menu", "Home, Search, My List, Stats, Calendar (⌘1 to ⌘5) and Back (⌘[) are in the menu bar."),
        Change("Small fixes", "Search results and My List fill the page's width. The sidebar works with VoiceOver. "
                              "Searches with one hit say \"1 result\". "
                              "Skip fillers moved to Settings › Skipping."),
    )),
    Release("1.8.4", "November 2, 2026", (
        Change("Better drop-downs", "Search filters, Settings and Quality now drop down right under the box, "
                                    "at most 10 rows tall with a scroll bar, instead of filling the screen or "
                                    "squeezing into two rows. The row under the pointer is highlighted."),
    )),
    Release("1.8.3", "November 2, 2026", (
        Change("Hover cards fit their text", "The card under a Content tag cut off its last line on some Macs. "
                                             "It now sizes itself to the text."),
        Change("18+ badges show up reliably", "When Home and My List both checked your saved shows at the same "
                                              "time, one of them could miss the result and stay unblurred until "
                                              "you came back. Fixed."),
    )),
    Release("1.8.2", "November 2, 2026", (
        Change("Rating meters", "Hover a Content tag and a card shows its AniList rating on a meter, with a white "
                                "line where 18+ starts (70 for nudity), so you can see why a show is or isn't 18+."),
        Change("Nudity is listed again from 60", "Shows like Tales of Wedding Rings list Nudity again; the meter "
                                                 "shows it's below the 18+ line, so they aren't hidden."),
        Change("What these tags mean", "The ⓘ next to Content opens a short guide right on the page: where the "
                                       "ratings come from, the 0-100 scale, and what earns 18+."),
    )),
    Release("1.8.1", "November 2, 2026", (
        Change("18+ badges right away", "Shows already in My List or Continue Watching are checked when AniGUI "
                                        "opens, so they're badged and blurred without opening them first. If a "
                                        "show only turns out to be 18+ once its page loads, it asks then."),
        Change("The Content line matches the badge", "\"Nudity\" is listed only when it's enough to make a show "
                                                     "18+ (rated 70+), so a show never says Nudity without the badge."),
        Change("What the tags mean", "Hover a Content tag to see its rating (0-100) and what that means; the ⓘ next "
                                     "to it explains where the ratings come from and what earns 18+."),
    )),
    Release("1.8.0", "November 2, 2026", (
        Change("18+ shows", "Shows with heavy nudity or sexual content get a red 18+ badge. Hide 18+ shows "
                            "(Settings → Content, on by default) keeps them out of Home, Search, the Calendar and "
                            "Related; Search says how many it hid. Shows you added yourself stay, with blurred "
                            "posters, and ask before opening (you can say not to ask again for a show)."),
        Change("Content notes", "Show pages list what's in a show, like Nudity, Sexual themes, Gore or Disturbing "
                                "themes, from AniList's community tags. Spoiler tags are never shown."),
        Change("Back is always there", "Scroll down a show page and a slim bar stays at the top with Back, the "
                                       "title, where you are, and Play."),
        Change("Coming soon", "Airing shows end their episode list with the next episode and when it airs."),
        Change("Dubs without mismatched subtitles", "Subtitles are made for the Japanese audio, so with a dub "
                                                    "they're off by default (still in the player's Subtitles menu). "
                                                    "Settings → Playback → Subtitles with dubs turns them back on."),
    )),
    Release("1.7.2", "November 2, 2026", (
        Change("Auto-play next works in IINA", "IINA stays on the last frame when an episode ends, and AniGUI missed "
                                               "that, so the next episode never started. It now notices either way, "
                                               "and IINA keeps its window open so the next episode plays right there."),
        Change("Quieter log", "Fixed a harmless error that filled the log after leaving a show page."),
    )),
    Release("1.7.1", "November 1, 2026", (
        Change("Pictures for new shows", "Shows that started this season now get episode pictures too, from a "
                                         "third source (TheTVDB, through ani.zip) that has them days earlier."),
        Change("Nicer placeholders", "Episodes that still have no picture show the show's own artwork, darkened, "
                                     "behind the episode number, instead of a plain block of color."),
    )),
    Release("1.7.0", "November 1, 2026", (
        Change("Filler badges", "Episodes that aren't from the manga get a FILLER tag, and the show page says how "
                                "many there are, e.g. \"87 of 220 episodes are filler\"."),
        Change("Hide fillers", "One switch above the episodes leaves fillers out of the list."),
        Change("Skip fillers", "Up Next and auto-play jump straight to the next story episode. Turn it on above "
                               "the episodes or in Settings → Playback; you can still click any filler to watch it."),
        Change("Where it comes from", "Anime Filler List (animefillerlist.com), the fan-made filler guide. Long "
                                      "shows like Naruto, Bleach and One Piece are covered; episodes that are only "
                                      "partly filler count as story. Shows without filler don't show the switches."),
    )),
    Release("1.6.0", "November 1, 2026", (
        Change("Episode pictures", "Episodes now show a still from the episode, with the title underneath. "
                                   "Hover one to see a play button and its full title. When there's no picture, "
                                   "you get a big episode number instead."),
        Change("Pages for long shows", "Shows with more than 100 episodes are split into pages (1–100, 101–200, …) "
                                       "and open on the page with your next episode."),
        Change("Jump to episode", "Type an episode number above the grid and press Return to go straight to it."),
    )),
    Release("1.5.0", "November 1, 2026", (
        Change("Signed updates", "From this version on, Update Now only installs updates signed by AniGUI's "
                                 "publisher. Even someone who broke into the GitHub account couldn't push you a "
                                 "fake update."),
        Change("Safer playback", "Only plain web links from the streaming site ever reach IINA or mpv, so a "
                                 "hacked site can't slip in player options."),
        Change("Verified downloads", "Setup checks that IINA is really from IINA's developer and approved by "
                                     "Apple before installing it."),
        Change("ani-cli comes with AniGUI", "ani-cli updates now arrive inside AniGUI updates: each one is a "
                                            "version that was tested with AniGUI and signed, instead of whatever "
                                            "is newest online."),
        Change("Under the hood", "Text from websites is always shown as plain text, temporary files live in "
                                 "private folders, and the build pipeline is locked down and checked for "
                                 "vulnerable libraries every week."),
    )),
    Release("1.4.1", "October 31, 2026", (
        Change("Trending in the calendar", "All airing is now Trending: the 30 hottest airing shows right now, "
                                           "ranked by AniList activity this week, each on its airing day with its "
                                           "rank. It loads in one quick request, so it no longer fails."),
        Change("Sidebar icons", "Stats and Calendar have icons now, and every sidebar icon has a cleaner look."),
        Change("Fix: search filters", "Filtering without picking a genre (for example, only a year) works again."),
    )),
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
