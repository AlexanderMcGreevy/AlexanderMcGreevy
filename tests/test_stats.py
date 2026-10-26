from datetime import date, timedelta

from scoreboard.stats import (
    best_streak,
    current_streak,
    dot_levels,
    last_12_months_grid,
    merge_calendars,
)

TODAY = date(2026, 10, 25)  # a Sunday


def days(start: date, n: int, count: int = 1) -> dict[date, int]:
    return {start + timedelta(days=i): count for i in range(n)}


def test_merge_calendars_sums_per_date():
    a = {date(2026, 10, 1): 2, date(2026, 10, 2): 1}
    b = {date(2026, 10, 2): 3, date(2026, 10, 3): 4}
    assert merge_calendars(a, b) == {
        date(2026, 10, 1): 2,
        date(2026, 10, 2): 4,
        date(2026, 10, 3): 4,
    }


def test_current_streak_counts_through_today():
    cal = days(date(2026, 10, 22), 4)
    assert current_streak(cal, TODAY) == 4


def test_current_streak_survives_empty_today():
    cal = days(date(2026, 10, 22), 3)
    cal[date(2026, 10, 25)] = 0
    assert current_streak(cal, TODAY) == 3


def test_current_streak_zero_when_yesterday_also_empty():
    cal = days(date(2026, 10, 20), 3)
    assert current_streak(cal, TODAY) == 0


def test_best_streak_returns_longest_run_and_end_date():
    cal = days(date(2026, 1, 1), 3)
    cal.update(days(date(2026, 3, 10), 5))
    assert best_streak(cal) == (5, date(2026, 3, 14))


def test_best_streak_empty_calendar():
    assert best_streak({}) == (0, None)
    assert best_streak({date(2026, 1, 1): 0}) == (0, None)


def test_streak_uses_merged_calendar():
    personal = {date(2026, 10, 19): 2}  # Monday
    work = {date(2026, 10, 20): 3}  # Tuesday
    merged = merge_calendars(personal, work)
    assert best_streak(merged) == (2, date(2026, 10, 20))
    assert current_streak(merged, date(2026, 10, 20)) == 2


def test_dot_levels_quartiles():
    assert dot_levels([0, 1, 2, 3, 4, 5, 6, 7, 8]) == [0, 1, 1, 2, 2, 3, 3, 4, 4]


def test_dot_levels_all_zero_and_single_value():
    assert dot_levels([0, 0, 0]) == [0, 0, 0]
    assert dot_levels([0, 5]) == [0, 4]


def test_dot_levels_ties_go_to_lower_bucket():
    # four nonzero values, the middle two tied: ties share the lowest rank's level
    assert dot_levels([1, 2, 2, 9]) == [1, 2, 2, 4]


def test_grid_shape():
    cal = {TODAY: 1}
    weeks, _ = last_12_months_grid(cal, TODAY)
    assert len(weeks) == 53
    assert all(len(w) == 7 for w in weeks)
    # TODAY is a Sunday: last column has today in row 0 and None after it
    assert weeks[-1][0] == 1
    assert weeks[-1][1:] == [None] * 6


def test_grid_future_days_none_and_first_column_sunday():
    today = date(2026, 10, 22)  # Thursday
    cal = {today: 7, today - timedelta(days=1): 2}
    weeks, _ = last_12_months_grid(cal, today)
    assert len(weeks) == 53
    last = weeks[-1]
    assert last[:5] == [0, 0, 0, 2, 7]  # Sun..Thu
    assert last[5:] == [None, None]
    assert all(v is not None for w in weeks[:-1] for v in w)
    # first column starts on a Sunday: 52 whole weeks before this week's Sunday
    first_sunday = date(2026, 10, 18) - timedelta(weeks=52)
    assert first_sunday.weekday() == 6
    probe = {first_sunday: 5}
    weeks2, _ = last_12_months_grid(probe, today)
    assert weeks2[0][0] == 5


def test_month_labels_first_column_of_each_month():
    weeks, labels = last_12_months_grid({}, TODAY)
    first_sunday = TODAY - timedelta(weeks=52)  # 2025-10-26
    assert [name for _, name in labels] == [
        "NOV", "DEC", "JAN", "FEB", "MAR", "APR",
        "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
    ]
    for idx, name in labels:
        col_days = [first_sunday + timedelta(weeks=idx, days=d) for d in range(7)]
        firsts = [d for d in col_days if d.day == 1]
        assert len(firsts) == 1 and firsts[0].strftime("%b").upper() == name
    assert labels[0] == (0, "NOV")
    assert labels[1] == (5, "DEC")
