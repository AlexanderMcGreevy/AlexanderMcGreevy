from datetime import date

import pytest

from scoreboard.errors import PersistentError, TransientError
from scoreboard.github import classify, fetch_contributions, with_retries

TODAY = date(2026, 10, 25)
SECRET_REPO = "secret-org/secret-repo"


def payload(created="2024-06-10T12:00:00Z", days=(), commits=0, prs=0, reviews=0):
    return {
        "viewer": {
            "login": "alex",
            "createdAt": created,
            "contributionsCollection": {
                "totalCommitContributions": commits,
                "totalPullRequestContributions": prs,
                "totalPullRequestReviewContributions": reviews,
                "contributionCalendar": {
                    "weeks": [
                        {
                            "contributionDays": [
                                {"date": d, "contributionCount": n} for d, n in days
                            ]
                        }
                    ]
                },
                "commitContributionsByRepository": [
                    {"repository": {"nameWithOwner": SECRET_REPO}}
                ],
            },
        }
    }


class FakeGql:
    """Returns canned payloads by window start year; records windows queried."""

    def __init__(self, by_year, failures=None):
        self.by_year = by_year
        self.failures = failures or {}
        self.windows = []

    def __call__(self, query, variables):
        self.windows.append((variables["from"][:10], variables["to"][:10]))
        year = int(variables["from"][:4])
        if year in self.failures:
            raise self.failures[year]
        return self.by_year[year]


def test_year_windows_clip_to_account_creation():
    gql = FakeGql({2024: payload(), 2025: payload(), 2026: payload()})
    fetch_contributions(gql, TODAY)
    assert sorted(gql.windows) == [
        ("2024-06-10", "2024-12-31"),
        ("2025-01-01", "2025-12-31"),
        ("2026-01-01", "2026-10-25"),
    ]


def test_current_and_previous_year_are_fetched_before_older_years():
    gql = FakeGql({2024: payload(), 2025: payload(), 2026: payload()})
    fetch_contributions(gql, TODAY)
    assert [w[0][:4] for w in gql.windows] == ["2026", "2025", "2024"]


def test_account_created_this_year_queries_one_window():
    # Creation date is unknown until the first (current-year) response arrives,
    # so that window starts Jan 1; GitHub reports nothing before creation.
    gql = FakeGql({2026: payload(created="2026-03-02T00:00:00Z")})
    fetch_contributions(gql, TODAY)
    assert gql.windows == [("2026-01-01", "2026-10-25")]


def test_sums_all_years_and_merges_calendar():
    gql = FakeGql(
        {
            2024: payload(days=[("2024-07-01", 2), ("2024-07-02", 3)], commits=5, prs=1, reviews=2),
            2025: payload(days=[("2025-01-01", 4)], commits=10, prs=2, reviews=3),
            2026: payload(days=[("2026-01-01", 1), ("2026-10-25", 6)], commits=20, prs=4, reviews=5),
        }
    )
    account = fetch_contributions(gql, TODAY)
    assert account.login == "alex"
    assert account.commits == 35
    assert account.pull_requests == 7
    assert account.reviews == 10
    assert account.history_complete is True
    assert account.stars is None and account.languages is None
    assert account.calendar == {
        date(2024, 7, 1): 2,
        date(2024, 7, 2): 3,
        date(2025, 1, 1): 4,
        date(2026, 1, 1): 1,
        date(2026, 10, 25): 6,
    }


def test_discards_repo_names():
    gql = FakeGql({2024: payload(), 2025: payload(), 2026: payload(days=[("2026-01-01", 1)])})
    account = fetch_contributions(gql, TODAY)
    assert SECRET_REPO not in repr(account)
    assert "secret" not in repr(account)


def test_older_year_persistent_failure_sets_history_incomplete():
    gql = FakeGql(
        {
            2025: payload(days=[("2025-01-01", 4)], commits=10),
            2026: payload(days=[("2026-01-01", 1)], commits=20),
        },
        failures={2024: PersistentError("nope")},
    )
    account = fetch_contributions(gql, TODAY)
    assert account.history_complete is False
    assert account.commits == 30
    assert set(account.calendar) == {date(2025, 1, 1), date(2026, 1, 1)}


@pytest.mark.parametrize("year", [2025, 2026])
def test_recent_year_persistent_failure_raises(year):
    gql = FakeGql(
        {2024: payload(), 2025: payload(), 2026: payload()},
        failures={year: PersistentError("nope")},
    )
    with pytest.raises(PersistentError):
        fetch_contributions(gql, TODAY)


def test_older_year_transient_failure_propagates():
    gql = FakeGql(
        {2025: payload(), 2026: payload()},
        failures={2024: TransientError("flaky")},
    )
    with pytest.raises(TransientError):
        fetch_contributions(gql, TODAY)


def test_retries_transient_then_succeeds():
    calls, sleeps = [], []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise TransientError("flaky")
        return "ok"

    assert with_retries(fn, sleep=sleeps.append) == "ok"
    assert len(calls) == 3
    assert sleeps == [1, 4]


def test_retries_give_up_after_three():
    calls, sleeps = [], []

    def fn():
        calls.append(1)
        raise TransientError("flaky")

    with pytest.raises(TransientError):
        with_retries(fn, sleep=sleeps.append)
    assert len(calls) == 3
    assert sleeps == [1, 4]


def test_persistent_errors_are_not_retried():
    calls, sleeps = [], []

    def fn():
        calls.append(1)
        raise PersistentError("bad token")

    with pytest.raises(PersistentError):
        with_retries(fn, sleep=sleeps.append)
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.parametrize("status", [401, 403])
def test_classifies_persistent_http(status):
    assert classify(status, []) is PersistentError


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_classifies_transient_http(status):
    assert classify(status, []) is TransientError


def test_classifies_network_error_as_transient():
    assert classify(None, []) is TransientError


@pytest.mark.parametrize("etype", ["FORBIDDEN", "INSUFFICIENT_SCOPES"])
def test_classifies_persistent_graphql(etype):
    assert classify(200, [{"type": etype}]) is PersistentError


def test_classifies_rate_limited_graphql_as_transient():
    assert classify(200, [{"type": "RATE_LIMITED"}]) is TransientError


def test_classifies_success_as_none():
    assert classify(200, []) is None
