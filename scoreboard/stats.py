"""Pure computation over contribution calendars. No I/O."""

from __future__ import annotations

from datetime import date, timedelta

from .models import AllTime, BoardData, BoardStats, Split

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


def language_shares(
    personal: dict[str, int] | None,
    work: dict[str, int] | None,
    top: int = 5,
) -> list[tuple[str, int]]:
    """Merge two byte maps and return the top languages as integer percents.

    Percents are of the *total* merged bytes (rounded half up), so the shown
    entries need not sum to 100. Ties break alphabetically.
    """
    merged: dict[str, int] = {}
    for side in (personal, work):
        for name, size in (side or {}).items():
            if size > 0:
                merged[name] = merged.get(name, 0) + size
    total = sum(merged.values())
    if total == 0:
        return []
    ranked = sorted(merged.items(), key=lambda item: (-item[1], item[0]))[:top]
    return [(name, (size * 100 * 2 + total) // (2 * total)) for name, size in ranked]


def _one_year_ago(today: date) -> date:
    try:
        return today.replace(year=today.year - 1)
    except ValueError:  # Feb 29
        return today.replace(year=today.year - 1, day=28)


def _window_sum(cal: dict[date, int], today: date) -> int:
    """Sum of counts for days in (one year ago, today]."""
    start = _one_year_ago(today)
    return sum(count for day, count in cal.items() if start < day <= today)


def compute_stats(data: BoardData) -> BoardStats:
    """Combine personal and (optional) work data into the board's numbers."""
    today = data.today
    personal, work = data.personal, data.work
    work_available = work is not None
    all_time_work = work is not None and work.history_complete

    year_personal = _window_sum(personal.calendar, today)
    year_work = _window_sum(work.calendar, today) if work is not None else None

    def split(attr: str) -> Split:
        mine = getattr(personal, attr)
        theirs = getattr(work, attr) if all_time_work else None
        return Split(mine + (theirs or 0), mine, theirs)

    merged = merge_calendars(personal.calendar, work.calendar if work else {})
    best, best_end = best_streak(merged)
    weeks, labels = last_12_months_grid(merged, today)

    if data.languages_scope == "combined":
        languages = language_shares(personal.languages, work.languages if work else None)
    else:
        languages = language_shares(personal.languages, None)

    return BoardStats(
        year_total=year_personal + (year_work or 0),
        year_personal=year_personal,
        year_work=year_work,
        current_streak=current_streak(merged, today),
        best_streak=best,
        best_streak_end=best_end,
        best_streak_window_only=(not personal.history_complete)
        or (work is not None and not work.history_complete),
        all_time=AllTime(
            commits=split("commits"),
            pull_requests=split("pull_requests"),
            reviews=split("reviews"),
        ),
        stars=personal.stars,
        languages=languages,
        weeks=weeks,
        month_labels=labels,
        work_available=work_available,
        all_time_work_available=all_time_work,
        languages_scope=data.languages_scope,
        visitors=data.visitors,
        visitors_as_of=data.visitors_as_of,
    )
