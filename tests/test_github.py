from datetime import date

import pytest

from scoreboard.errors import PersistentError, TransientError
from scoreboard.github import (
    classify,
    fetch_contributions,
    fetch_languages,
    fetch_stars,
    with_retries,
)

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


# --- Task 3: carry-over fixes (classify, malformed payloads, calendar merge) ---


def test_classifies_typeless_graphql_error_as_transient():
    assert classify(200, [{"message": "something blipped"}]) is TransientError


def test_classifies_unknown_graphql_type_as_transient():
    assert classify(200, [{"type": "SOMETHING_NEW"}]) is TransientError


def test_known_persistent_type_wins_over_typeless_error():
    assert classify(200, [{"message": "blip"}, {"type": "FORBIDDEN"}]) is PersistentError


@pytest.mark.parametrize("status", [408, 429])
def test_classifies_408_and_429_as_transient(status):
    assert classify(status, []) is TransientError


@pytest.mark.parametrize("status", [400, 404, 422])
def test_other_4xx_stay_persistent(status):
    assert classify(status, []) is PersistentError


def _viewer(**overrides):
    base = payload(days=[("2026-01-01", 1)])["viewer"]
    base.update(overrides)
    return {"viewer": base}


def _without_calendar_keys():
    p = _viewer()
    del p["viewer"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return p


def _without_collection():
    p = _viewer()
    del p["viewer"]["contributionsCollection"]
    return p


def _without_count_key():
    p = _viewer()
    del p["viewer"]["contributionsCollection"]["totalCommitContributions"]
    return p


@pytest.mark.parametrize(
    "bad",
    [
        {"viewer": None},
        {},
        {"viewer": {"login": "alex"}},
        _without_collection(),
        _without_calendar_keys(),
        _without_count_key(),
        _viewer(createdAt="not-a-date"),
    ],
)
def test_malformed_current_year_payload_raises_persistent(bad):
    gql = FakeGql({2026: bad})
    with pytest.raises(PersistentError):
        fetch_contributions(gql, TODAY)


def test_malformed_previous_year_payload_raises_persistent():
    gql = FakeGql({2024: payload(), 2025: {"viewer": None}, 2026: payload()})
    with pytest.raises(PersistentError):
        fetch_contributions(gql, TODAY)


def test_malformed_older_year_marks_history_incomplete_without_partial_totals():
    broken = _without_calendar_keys()
    broken["viewer"]["contributionsCollection"]["totalCommitContributions"] = 999
    gql = FakeGql({2024: broken, 2025: payload(commits=10), 2026: payload(commits=20)})
    account = fetch_contributions(gql, TODAY)
    assert account.history_complete is False
    assert account.commits == 30


def test_overlapping_windows_keep_max_count_per_date():
    # 2025-12-31 appears in two windows; the larger count wins in either order.
    gql = FakeGql(
        {
            2024: payload(),
            2025: payload(days=[("2025-12-31", 9)]),
            2026: payload(days=[("2025-12-31", 2), ("2026-01-01", 1)]),
        }
    )
    assert fetch_contributions(gql, TODAY).calendar[date(2025, 12, 31)] == 9
    gql = FakeGql(
        {
            2024: payload(),
            2025: payload(days=[("2025-12-31", 2)]),
            2026: payload(days=[("2025-12-31", 9)]),
        }
    )
    assert fetch_contributions(gql, TODAY).calendar[date(2025, 12, 31)] == 9


# --- Task 3: stars and languages ---


def repos_page(nodes, has_next=False, cursor=None):
    return {
        "viewer": {
            "repositories": {
                "nodes": nodes,
                "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
            }
        }
    }


class PagedGql:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def __call__(self, query, variables):
        self.calls.append((query, variables))
        return self.pages.pop(0)


def test_fetch_stars_paginates():
    gql = PagedGql(
        [
            repos_page([{"stargazerCount": 3}, {"stargazerCount": 4}], True, "c1"),
            repos_page([{"stargazerCount": 10}]),
        ]
    )
    assert fetch_stars(gql) == 17
    assert [v.get("after") for _, v in gql.calls] == [None, "c1"]
    assert all(v["first"] == 100 for _, v in gql.calls)
    assert "OWNER" in gql.calls[0][0] and "PUBLIC" in gql.calls[0][0]


def test_fetch_stars_no_repos_is_zero():
    assert fetch_stars(PagedGql([repos_page([])])) == 0


def test_fetch_languages_sums_bytes_and_drops_repo_names():
    def repo(name, langs):
        return {
            "name": name,
            "nameWithOwner": f"org/{name}",
            "languages": {"edges": [{"size": s, "node": {"name": n}} for n, s in langs]},
        }

    gql = PagedGql(
        [
            repos_page(
                [repo("secret-repo", [("Python", 100), ("Go", 50)])], True, "c1"
            ),
            repos_page([repo("other-secret", [("Python", 25)]), repo("empty", [])]),
        ]
    )
    result = fetch_languages(gql)
    assert result == {"Python": 125, "Go": 50}
    assert "secret" not in repr(result)
    query = gql.calls[0][0]
    assert "isFork: false" in query and "OWNER" in query
    assert "nameWithOwner" not in query
    assert "url" not in query.lower()


@pytest.mark.parametrize("fetch", [fetch_stars, fetch_languages])
@pytest.mark.parametrize(
    "bad",
    [
        {"viewer": None},
        {"viewer": {"repositories": None}},
        {"viewer": {"repositories": {"nodes": None, "pageInfo": {}}}},
        repos_page([{"unexpected": 1}], False),
        repos_page([{"stargazerCount": 1}], True, None),  # next page but no cursor
    ],
)
def test_malformed_repo_payload_raises_persistent(fetch, bad):
    with pytest.raises(PersistentError):
        fetch(PagedGql([bad]))


def test_null_languages_repo_is_skipped():
    normal = {"languages": {"edges": [{"size": 7, "node": {"name": "Python"}}]}}
    gql = PagedGql([repos_page([{"languages": None}, {"languages": {"edges": None}}, normal])])
    assert fetch_languages(gql) == {"Python": 7}


@pytest.mark.parametrize(
    "fetch, node", [(fetch_stars, {"stargazerCount": 1}), (fetch_languages, {"languages": {"edges": []}})]
)
def test_repeated_cursor_raises_instead_of_looping(fetch, node):
    class SameCursor:
        calls = 0

        def __call__(self, query, variables):
            self.calls += 1
            if self.calls > 5:
                raise AssertionError("pager looped")
            return repos_page([node], True, "same")

    gql = SameCursor()
    with pytest.raises(PersistentError):
        fetch(gql)
    assert gql.calls <= 3
