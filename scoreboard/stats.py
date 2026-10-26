"""Pure computation over contribution calendars. No I/O."""

from __future__ import annotations

from datetime import date, timedelta

_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_WEEKS = 53


def merge_calendars(*cals: dict[date, int]) -> dict[date, int]:
    """Sum the per-day counts of any number of calendars."""
    merged: dict[date, int] = {}
    for cal in cals:
        for day, count in cal.items():
            merged[day] = merged.get(day, 0) + count
    return merged


def current_streak(cal: dict[date, int], today: date) -> int:
    """Consecutive active days ending today, or yesterday if today is empty."""
    day = today if cal.get(today, 0) > 0 else today - timedelta(days=1)
    streak = 0
    while cal.get(day, 0) > 0:
        streak += 1
        day -= timedelta(days=1)
    return streak


def best_streak(cal: dict[date, int]) -> tuple[int, date | None]:
    """Longest run of consecutive active days and the date it ended.

    Ties go to the most recent run. An empty calendar gives (0, None).
    """
    best, best_end = 0, None
    run, prev = 0, None
    for day in sorted(d for d, c in cal.items() if c > 0):
        run = run + 1 if prev is not None and day - prev == timedelta(days=1) else 1
        if run >= best:
            best, best_end = run, day
        prev = day
    return best, best_end


def dot_levels(counts: list[int]) -> list[int]:
    """Map counts to 0-4. Zero stays 0; nonzero counts split into quartiles.

    A nonzero value's level is ceil(4 * r / n), where r is the 1-based rank of
    its first occurrence among the n sorted nonzero counts, so ties share the
    lower bucket.
    """
    nonzero = sorted(c for c in counts if c > 0)
    n = len(nonzero)
    level_of: dict[int, int] = {}
    for rank, value in enumerate(nonzero, start=1):
        level_of.setdefault(value, -(-4 * rank // n))
    return [level_of.get(c, 0) if c > 0 else 0 for c in counts]


def last_12_months_grid(
    cal: dict[date, int], today: date
) -> tuple[list[list[int | None]], list[tuple[int, str]]]:
    """53 Sunday-first week columns ending with the week containing today.

    Days after `today` are None. Month labels are (week_index, "NOV") at the
    column that contains the 1st of each month.
    """
    this_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    start = this_sunday - timedelta(weeks=_WEEKS - 1)
    weeks: list[list[int | None]] = []
    labels: list[tuple[int, str]] = []
    for w in range(_WEEKS):
        column: list[int | None] = []
        for d in range(7):
            day = start + timedelta(weeks=w, days=d)
            column.append(None if day > today else cal.get(day, 0))
            if day.day == 1 and day <= today:
                labels.append((w, _MONTHS[day.month - 1]))
        weeks.append(column)
    return weeks, labels
