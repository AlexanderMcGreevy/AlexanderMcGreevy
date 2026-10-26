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


# --- Task 3: language_shares and compute_stats ---

from scoreboard.models import AccountData, BoardData  # noqa: E402
from scoreboard.stats import compute_stats, language_shares  # noqa: E402


def test_language_shares_merge_and_top_five():
    personal = {"Python": 400, "Go": 100, "Rust": 50}
    work = {"Python": 200, "TypeScript": 150, "Java": 60, "C": 40}
    shares = language_shares(personal, work)
    # total = 1000 bytes; Rust (50) is the fifth; C (40) is cut.
    assert len(shares) == 5
    assert [n for n, _ in shares] == ["Python", "TypeScript", "Go", "Java", "Rust"]
    assert [p for _, p in shares] == [60, 15, 10, 6, 5]


def test_language_shares_percent_of_total_not_of_shown():
    langs = {f"L{i}": 10 for i in range(6)}
    shares = language_shares(langs, None)
    assert len(shares) == 5
    assert all(p == 17 for _, p in shares)  # 10/60, not 10/50
    assert sum(p for _, p in shares) < 100


def test_language_shares_empty():
    assert language_shares(None, None) == []
    assert language_shares({}, {}) == []
    assert language_shares({"Python": 0}, None) == []


def test_language_shares_one_side_none():
    assert language_shares({"Python": 30, "Go": 10}, None) == [("Python", 75), ("Go", 25)]
    assert language_shares(None, {"Go": 10}) == [("Go", 100)]


def test_language_shares_ties_are_deterministic_by_name():
    assert language_shares({"B": 5, "A": 5}, None) == [("A", 50), ("B", 50)]


def account(login, cal, commits=0, prs=0, reviews=0, complete=True, stars=None, langs=None):
    return AccountData(login, cal, commits, prs, reviews, complete, stars, langs)


def board(personal, work, scope="combined"):
    return BoardData(TODAY, personal, work, scope, 12, date(2026, 10, 24))


def test_compute_stats_combined():
    p = account("p", {date(2026, 10, 24): 482}, commits=1000, prs=50, reviews=20, stars=7,
                langs={"Python": 80})
    w = account("w", {date(2026, 10, 25): 611}, commits=2000, prs=30, reviews=10,
                langs={"Go": 20})
    stats = compute_stats(board(p, w))
    assert stats.year_total == 1093
    assert stats.year_personal == 482
    assert stats.year_work == 611
    assert stats.all_time.commits.total == 3000
    assert stats.all_time.commits.personal == 1000
    assert stats.all_time.commits.work == 2000
    assert stats.all_time.pull_requests.total == 80
    assert stats.all_time.reviews.work == 10
    assert stats.work_available is True
    assert stats.all_time_work_available is True
    assert stats.best_streak_window_only is False
    assert stats.stars == 7
    assert stats.languages == [("Python", 80), ("Go", 20)]
    assert stats.languages_scope == "combined"
    assert stats.current_streak == 2
    assert stats.best_streak == 2 and stats.best_streak_end == date(2026, 10, 25)
    assert (stats.visitors, stats.visitors_as_of) == (12, date(2026, 10, 24))
    assert len(stats.weeks) == 53


def test_compute_stats_year_window_excludes_older_days():
    old = date(2025, 10, 25)  # exactly one year ago: outside the window
    edge = date(2025, 10, 26)  # first day inside
    p = account("p", {old: 100, edge: 5, date(2026, 10, 25): 1}, commits=106)
    stats = compute_stats(board(p, None))
    assert stats.year_total == 6
    assert stats.all_time.commits.total == 106


def test_compute_stats_year_window_on_leap_day():
    leap = BoardData(date(2028, 2, 29), account("p", {date(2027, 2, 28): 9, date(2027, 3, 1): 4}),
                     None, "personal", None, None)
    assert compute_stats(leap).year_total == 4


def test_compute_stats_work_none_is_personal_only():
    p = account("p", {date(2026, 10, 25): 3}, commits=10, prs=2, reviews=1, stars=4,
                langs={"Python": 5}, )
    stats = compute_stats(board(p, None))
    assert stats.work_available is False
    assert stats.all_time_work_available is False
    assert stats.year_work is None
    assert stats.year_total == stats.year_personal == 3
    for split in (stats.all_time.commits, stats.all_time.pull_requests, stats.all_time.reviews):
        assert split.work is None
        assert split.total == split.personal
    assert stats.all_time.commits.total == 10
    assert stats.best_streak_window_only is False


def test_compute_stats_incomplete_history():
    p = account("p", {date(2026, 10, 25): 3}, commits=10)
    w = account("w", {date(2026, 10, 25): 4}, commits=99, complete=False)
    stats = compute_stats(board(p, w))
    assert stats.all_time_work_available is False
    assert stats.best_streak_window_only is True
    assert stats.work_available is True
    assert stats.year_work == 4 and stats.year_total == 7
    assert stats.all_time.commits.work is None
    assert stats.all_time.commits.total == 10


def test_compute_stats_best_streak_uses_full_merged_calendar():
    # A 5-day run two years ago, split across the personal and work calendars.
    start = date(2024, 3, 1)
    p = account("p", {start + timedelta(days=i): 1 for i in (0, 1, 4)})
    w = account("w", {start + timedelta(days=i): 1 for i in (2, 3)})
    stats = compute_stats(board(p, w))
    assert stats.best_streak == 5
    assert stats.best_streak_end == date(2024, 3, 5)
    assert stats.year_total == 0
    assert stats.current_streak == 0


def test_compute_stats_personal_scope_ignores_work_languages():
    p = account("p", {}, langs={"Python": 10})
    w = account("w", {}, langs={"Go": 1000})
    stats = compute_stats(board(p, w, scope="personal"))
    assert stats.languages == [("Python", 100)]
    assert stats.languages_scope == "personal"


def test_compute_stats_stars_come_from_personal_only():
    p = account("p", {}, stars=5)
    w = account("w", {}, stars=500)
    assert compute_stats(board(p, w)).stars == 5
    assert compute_stats(board(account("p", {}), w)).stars is None


def test_compute_stats_empty_calendars_and_languages():
    stats = compute_stats(board(account("p", {}), None))
    assert stats.year_total == 0
    assert stats.best_streak == 0 and stats.best_streak_end is None
    assert stats.languages == []
