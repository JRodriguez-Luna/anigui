"""What changed in each version, in plain words. Shown in the What's New window and
on the GitHub release page.

Newest first. Add an entry here with every release; tests check the current
version has one.

Write for the people using AniGUI: only what they'll notice. Fixes that are internal
(the publisher's own tools, the build, logs, how the app is put together) go under
one line: Change("Minor fixes", "Small fixes and improvements.").
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
    Release("2.0.1", "November 12, 2026", (
        Change("Lighter while you watch", "AniGUI uses far less of your Mac while an episode plays, most of all "
                                          "in full screen, on a TV or big display, and with the holiday theme "
                                          "on. Snow and lights hold still while an episode plays or while "
                                          "you're in another app, and pick up again after."),
        Change("Video straight from the graphics chip", "The built-in player now lets your Mac's graphics chip "
                                                        "hand each frame over directly, instead of copying it "
                                                        "out to memory and back, so playing an episode takes "
                                                        "much less work."),
        Change("Less memory", "Pictures AniGUI keeps ready for scrolling now stay within a fixed budget, so it "
                              "no longer grows to gigabytes after a long evening of browsing."),
    )),
    Release("2.0.0", "November 9, 2026", (
        Change("Yours", "AniGUI 2.0 is personal and private, and everything stays on your Mac. A short tour shows "
                        "what's new the first time you open it. New features start off; switch on what you like in "
                        "Settings."),
        Change("Cinema", "A new look: each show's colors fill the page, the player goes full bleed, and the video "
                         "can pop out (P) to float over other apps and full-screen windows."),
        Change("My Library", "Make your own lists, rate shows with half stars, add tags and a note, and see a "
                             "timeline of what you watched. My List is now called Saved (everything in it is "
                             "still there)."),
        Change("Private", "Private mode (⌘⇧N) keeps what you watch out of your history. Lock AniGUI, a list or "
                          "18+ shows with Touch ID. Settings → Privacy shows every place AniGUI connects to, "
                          "and why."),
        Change("Back up and bring your list", "Back up everything to one file and restore it on any Mac, with "
                                              "automatic daily backups if you like. Import your list from "
                                              "AniList or MyAnimeList. Your data was backed up before this "
                                              "update, just in case."),
        Change("Downloads", "Right-click an episode → Download to watch with no internet. Find them in "
                            "My Library → Downloads."),
        Change("In the player", "Save a moment (B) and come back to that second later, a sleep timer, a queue "
                                "for what's next, Sharper picture (Anime4K) for older or lower-quality video, and "
                                "your Mac's media keys, AirPods and Control Center control the built-in player."),
        Change("Your shows, your way", "Per-show Sub/Dub, quality, skipping and subtitle size; subtitle size, "
                                       "color and a box behind them; Spoiler shield blurs episodes you haven't "
                                       "reached; Rewatch mode; and “Not interested” hides a suggestion."),
        Change("Wrapped and goals", "Your year in anime on the Stats page, plus a weekly goal and streaks."),
        Change("Make it yours", "Pick your color and a matching app icon, put your name on Home, and choose "
                                "Home's rows and their order."),
        Change("Smoother", "Scrolling, playing and the holiday snow all use far less of your Mac."),
    )),
    Release("1.11.1", "November 3, 2026", (
        Change("Built-in player shows the episode", "The video area showed a flipped copy of the window instead of "
                                                    "the episode. Fixed."),
        Change("A cleaner watch page", "While an episode plays, its list sits beside the video (find an episode, "
                                       "sort, hide watched, fillers, right-click to mark watched) and the grid below "
                                       "steps aside, so episodes aren't listed twice. Under the video: the episode's "
                                       "title, air date and summary, Sub/Dub and quality, and Open in IINA. Seasons, "
                                       "Related and You might also like follow."),
    )),
    Release("1.11.0", "November 3, 2026", (
        Change("Play right here", "Episodes can now play inside AniGUI: the video on the show's page with the "
                                  "episode list beside it, a mini-player in the corner when you look around, and "
                                  "full screen with F. Skip intro, Up next, audio and subtitle tracks and speed are "
                                  "all in the player. Settings › Playback › Player switches between AniGUI, IINA "
                                  "and mpv."),
        Change("Because you watched", "Home now suggests shows based on what you've watched the most."),
        Change("Holidays: coming December 1", "Before December the Holidays page shows a countdown (and can "
                                              "remind you), and badges only count from December 1."),
        Change("Holiday player", "In the holiday season the built-in player gets lights, a garland, a bow and "
                                 "snow while paused. Switch any of it off in the player's ⚙ menu."),
    )),
    Release("1.10.0", "November 3, 2026", (
        Change("Holidays", "A new 🎄 Holidays page while the holiday theme is on. An advent calendar with a "
                           "Christmas episode behind every door from December 1 to 24 (missed one? it stays open), "
                           "the 12 Days of Anime challenge from December 14 to Christmas, six badges to earn, and "
                           "the Christmas episodes in shows you already watch."),
        Change("Decked out", "Twinkling lights and a Christmas countdown in the sidebar (click it and see), "
                             "candy-cane progress bars, snow on the posters and settling on the Home banner, "
                             "ornaments, gift-tag NEW badges, a sweater on Stats, and 🎄 tags on Christmas episodes."),
        Change("Little surprises", "🎁 Surprise me on Home plays something from a show you're watching or saved. "
                                   "Santa flies by now and then, adding a show to My List comes with a bow, and the "
                                   "Calendar marks Christmas and New Year's. Christmas Day and New Year's each have "
                                   "something special too."),
        Change("Christmas shelf", "Every show on Home's Christmas shelf now has a Christmas episode."),
    )),
    Release("1.9.1", "November 3, 2026", (
        Change("Holiday Dock icon", "The Santa hat hung off the bottom corner of the icon on some screens. It "
                                    "now sits on top, drawn sharp at every icon size and display resolution."),
        Change("Episode titles with accents", "Titles with letters like ū or é came out garbled (My Hero Academia "
                                              "season 6 episode 4 read \"Keishu014d\"), and those episodes lost "
                                              "their picture. Both are fixed."),
    )),
    Release("1.9.0", "November 3, 2026", (
        Change("Seasons on one page", "A show's page now lists every season of the series in order, with how far "
                                      "you've got in each, plus its movies and specials. Finish a season and Up next "
                                      "offers the next one; auto-play rolls right into it."),
        Change("Smoother everywhere", "Pages fade in, pictures fade in as they load, the Home banner crossfades, "
                                      "posters lift when you hover them, and loading placeholders shimmer. With "
                                      "Reduce motion on in macOS, it keeps to gentle fades."),
        Change("Holiday theme", "Snow on Home, red-and-green colors, a shelf of anime with Christmas episodes and a festive Dock icon. "
                                "It turns on by itself the day after Thanksgiving and off after New Year's Day. "
                                "Can't wait? Settings › Appearance › Early."),
        Change("Minor fixes", "Small fixes and improvements."),
    )),
    Release("1.8.8", "November 3, 2026", (
        Change("Minor fixes", "Small fixes and improvements."),
    )),
    Release("1.8.7", "November 3, 2026", (
        Change("Saved shows load again", "hianime renumbered its shows, so shows saved before then said "
                                         "\"Couldn't load this show: HTTP 404\". AniGUI now finds each one's new "
                                         "address the first time you open it (or when it checks for new episodes) "
                                         "and moves your progress and My List over."),
    )),
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
        Change("Minor fixes", "Small fixes and improvements."),
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
