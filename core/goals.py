"""Goals and streaks (2.0): an episode goal for the week, and how many days in a row you've
watched. Worked out on this Mac from what AniGUI already keeps."""

from __future__ import annotations

import datetime as dt

from .store import Store


def week_start(today: dt.date | None = None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=today.weekday())        # Monday


def episodes_this_week(store: Store, today: dt.date | None = None) -> int:
    start = dt.datetime.combine(week_start(today), dt.time()).timestamp()
    return sum(1 for p in store.all_progress() if p.completed and p.updated_at >= start)


def streak(store: Store, today: dt.date | None = None) -> int:
    """Days in a row with some watching (a minute or more). Not having watched yet today
    doesn't break it."""
    today = today or dt.date.today()
    per_day: dict[dt.date, float] = {}
    for day, _a, _e, seconds in store.watch_log():
        d = dt.date.fromisoformat(day)
        per_day[d] = per_day.get(d, 0.0) + seconds
    days = {d for d, s in per_day.items() if s >= 60}
    cursor = today if today in days else today - dt.timedelta(days=1)
    run = 0
    while cursor in days:
        run += 1
        cursor -= dt.timedelta(days=1)
    return run


def goal_line(done: int, goal: int, streak_days: int) -> str:
    """For Home: '3 of 5 episodes this week · 4-day streak'."""
    parts = []
    if goal > 0:
        parts.append("Goal met this week 🎉" if done >= goal else f"{done} of {goal} episodes this week")
    if streak_days >= 2:
        parts.append(f"{streak_days}-day streak")
    return " · ".join(parts)
