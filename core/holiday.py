"""When the holiday theme is on.

Auto: from the day after (US) Thanksgiving through New Year's Day, when most people
decorate. Early: from November 1. Off: never. The November banner offers Early once a
year, before Auto would start.
"""

from __future__ import annotations

import datetime as dt

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
