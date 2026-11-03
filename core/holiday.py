"""When the holiday theme is on.

Auto: from the day after (US) Thanksgiving through New Year's Day, when most people
decorate. Early: from November 1. Off: never. The November banner offers Early once a
year, before Auto would start.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

MODES = ("auto", "early", "off")


def thanksgiving(year: int) -> dt.date:
    """The fourth Thursday of November."""
    first = dt.date(year, 11, 1)
    first_thursday = first + dt.timedelta(days=(3 - first.weekday()) % 7)
    return first_thursday + dt.timedelta(weeks=3)


def season_start(mode: str, year: int) -> dt.date | None:
    if mode == "early":
        return dt.date(year, 11, 1)
    if mode == "auto":
        return thanksgiving(year) + dt.timedelta(days=1)
    return None


def is_on(mode: str, today: dt.date | None = None) -> bool:
    today = today or dt.date.today()
    if mode not in ("auto", "early"):
        return False
    if today.month == 1 and today.day == 1:          # New Year's Day still counts
        return True
    start = season_start(mode, today.year)
    return start is not None and start <= today <= dt.date(today.year, 12, 31)


def offer_early(mode: str, seen_year: str, today: dt.date | None = None) -> bool:
    """Show the 'holiday theme is ready' banner: November, on Auto, before it has started,
    and not yet answered this year."""
    today = today or dt.date.today()
    return (mode == "auto" and today.month == 11 and not is_on(mode, today)
            and str(seen_year) != str(today.year))


# The Christmas shelf. AniList has no Christmas tag, so these are hand-picked: well-known
# anime with a Christmas movie or a Christmas episode (in CHRISTMAS_EPISODES below).
CHRISTMAS_IDS = (
    759,      # Tokyo Godfathers
    4224,     # Toradora!
    5680,     # K-ON!
    98444,    # Laid-Back Camp
    11757,    # Sword Art Online
    6045,     # Kimi ni Todoke: From Me to You
    232,      # Cardcaptor Sakura
    918,      # Gintama
    99578,    # Wotakoi: Love is Hard for Otaku
    13759,    # The Pet Girl of Sakurasou
    20812,    # SHIROBAKO
    1887,     # Lucky☆Star
)


# -- Christmas episodes (the advent calendar, the 🎄 tags, the Holidays page) ----------------------

@dataclass(frozen=True)
class XmasEpisode:
    anilist_id: int
    episode: str          # "19", or "1" for a movie
    show: str
    title: str            # the episode's own title


# One per advent door, Dec 1 to 24. Each was checked against the episode's own title on
# Kitsu, and the release's live check makes sure hianime still has it.
CHRISTMAS_EPISODES: tuple[XmasEpisode, ...] = (
    XmasEpisode(98444, "11", "Laid-Back Camp", "Christmas Camp!"),
    XmasEpisode(5680, "7", "K-ON!", "Christmas!"),
    XmasEpisode(1887, "11", "Lucky☆Star", "Various Ways to Spend Christmas Eve"),
    XmasEpisode(66, "17", "Azumanga Daioh", "End of 2nd Semester & Christmas"),
    XmasEpisode(12815, "37", "Polar Bear's Café", "Christmas Planning! / Christmas Trouble!"),
    XmasEpisode(10495, "7", "YuruYuri", "Christmas"),
    XmasEpisode(11757, "3", "Sword Art Online", "The Red-Nosed Reindeer"),
    XmasEpisode(20047, "8", "Sakura Trick", "A Cherry Blossom-colored Christmas"),
    XmasEpisode(232, "35", "Cardcaptor Sakura", "Sakura's Wonderful Christmas"),
    XmasEpisode(918, "37", "Gintama", "People Who Say That Santa Doesn't Really Exist Actually Want To Believe In Him"),
    XmasEpisode(6045, "22", "Kimi ni Todoke: From Me to You", "Christmas"),
    XmasEpisode(11843, "6", "Daily Lives of High School Boys", "High School Boys and the Holy Night"),
    XmasEpisode(99578, "6", "Wotakoi: Love is Hard for Otaku", "Bleak Christmas"),
    XmasEpisode(21878, "9", "Gabriel DropOut", "Christmas and New Year's Eve Surprise"),
    XmasEpisode(516, "39", "Sgt. Frog", "The Space Frog Who Stole Christmas"),
    XmasEpisode(1852, "12", "Hidamari Sketch", "December 24, Christmas Eve"),
    XmasEpisode(21686, "4", "Kiss Him, Not Me", "Christmas in the Holy Land"),
    XmasEpisode(20946, "17", "My Love Story!!", "My Christmas"),
    XmasEpisode(2787, "22", "Shakugan no Shana: Season II", "Christmas Eve"),
    XmasEpisode(13759, "14", "The Pet Girl of Sakurasou", "Windows and Lights on Christmas Eve"),
    XmasEpisode(20812, "12", "SHIROBAKO", "Exodus Christmas"),
    XmasEpisode(4224, "17", "Toradora!", "Mercury Retrogrades at Christmas"),
    XmasEpisode(4224, "19", "Toradora!", "Christmas Eve Festival"),
    XmasEpisode(759, "1", "Tokyo Godfathers", "The movie: three people find a baby on Christmas Eve"),
)


def advent_pick(day: int) -> XmasEpisode | None:
    """Door `day` (1-24) of the advent calendar."""
    if not CHRISTMAS_EPISODES or not 1 <= day <= 24:
        return None
    return CHRISTMAS_EPISODES[(day - 1) % len(CHRISTMAS_EPISODES)]


def advent_open_until(today: dt.date | None = None) -> int:
    """How many doors can be opened today: none before December, one more each day, all
    24 from Christmas Eve on (and through New Year's Day)."""
    today = today or dt.date.today()
    if today.month == 12:
        return min(24, today.day)
    if today.month == 1 and today.day == 1:
        return 24
    return 0


def christmas_episodes_for(anilist_id: int | None) -> set[str]:
    return {e.episode for e in CHRISTMAS_EPISODES if anilist_id and e.anilist_id == anilist_id}


# -- 12 Days of Anime ---------------------------------------------------------------------------------

CHALLENGE_GOAL = 12


def challenge_window(year: int) -> tuple[dt.date, dt.date]:
    return dt.date(year, 12, 14), dt.date(year, 12, 25)


@dataclass(frozen=True)
class Badge:
    key: str
    emoji: str
    name: str
    hint: str
    earned: bool


def season_year(today: dt.date) -> int:
    """The holiday season a date belongs to (New Year's Day counts toward last year's)."""
    return today.year - 1 if today.month == 1 else today.year


def challenge(progress, watch_days, christmas_keys: set[tuple[str, str]], first_seen: dict[str, float],
              today: dt.date | None = None) -> tuple[int, list[Badge]]:
    """(episodes toward the 12 Days goal, badges) from your history.

    progress: Progress rows; watch_days: ISO days with any watching; christmas_keys: the
    (anime_id, episode) pairs that are Christmas episodes; first_seen: anime_id -> when you
    first watched it. Only this season counts (Nov 1 to Jan 1)."""
    today = today or dt.date.today()
    year = season_year(today)
    season_start = dt.datetime(year, 11, 1).timestamp()
    season_end = dt.datetime(year + 1, 1, 2).timestamp()
    start, end = challenge_window(year)
    lo, hi = dt.datetime.combine(start, dt.time()).timestamp(), dt.datetime.combine(end, dt.time.max).timestamp()
    done = [p for p in progress if p.completed and season_start <= p.updated_at < season_end]
    in_window = [p for p in done if lo <= p.updated_at <= hi]
    count = min(CHALLENGE_GOAL, len(in_window))

    days = sorted({d for d in watch_days if f"{year}-11-01" <= d <= f"{year + 1}-01-01"})
    streak = best = 0
    prev = None
    for d in days:
        cur = dt.date.fromisoformat(d)
        streak = streak + 1 if prev and (cur - prev).days == 1 else 1
        best = max(best, streak)
        prev = cur
    night = any(dt.datetime.fromtimestamp(p.updated_at).hour < 4 for p in done)
    xmas = any((p.anime_id, p.episode) in christmas_keys for p in done)
    new_show = any(season_start <= t < season_end for t in first_seen.values())
    badges = [
        Badge("gift", "🎁", "First gift", "Finish an episode this season", bool(done)),
        Badge("owl", "🦉", "Night owl", "Finish an episode after midnight", night),
        Badge("streak", "🔥", "3-day streak", "Watch three days in a row", best >= 3),
        Badge("xmas", "🎄", "Christmas episode", "Watch a Christmas episode", xmas),
        Badge("new", "⛷️", "Something new", "Start a show you've never watched", new_show),
        Badge("twelve", "⭐", "12 Days", f"Finish {CHALLENGE_GOAL} episodes from Dec 14 to 25", count >= CHALLENGE_GOAL),
    ]
    return count, badges


# -- once-a-year moments ---------------------------------------------------------------------------------

def is_christmas(today: dt.date | None = None) -> bool:
    today = today or dt.date.today()
    return today.month == 12 and today.day == 25


def is_new_year(today: dt.date | None = None) -> bool:
    today = today or dt.date.today()
    return today.month == 1 and today.day == 1


def holiday_days(day: dt.date) -> str | None:
    """Labels for the Calendar."""
    return {(12, 24): "Christmas Eve", (12, 25): "Christmas", (12, 31): "New Year's Eve",
            (1, 1): "New Year's Day"}.get((day.month, day.day))
