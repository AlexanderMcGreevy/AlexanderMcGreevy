"""GitHub GraphQL transport and the contributions fetch.

Only counts and dates leave this module. Repo names, org names, commit
messages and file names are never requested, parsed, stored, or logged, and
the token is never logged or placed in an error message.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from datetime import date
from typing import TypeVar

from .errors import PersistentError, TransientError
from .models import AccountData

T = TypeVar("T")

GraphQL = Callable[[str, dict], dict]

API_URL = "https://api.github.com/graphql"
TIMEOUT_SECONDS = 30
BACKOFF_SECONDS = (1, 4)

CONTRIBUTIONS_QUERY = """
query($from: DateTime!, $to: DateTime!) {
  viewer {
    login
    createdAt
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""

STARS_QUERY = """
query($first: Int!, $after: String) {
  viewer {
    repositories(
      first: $first, after: $after, ownerAffiliations: OWNER, privacy: PUBLIC
    ) {
      nodes {
        stargazerCount
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""

# Language names and byte counts only: no repository field other than
# `languages` is requested.
LANGUAGES_QUERY = """
query($first: Int!, $after: String) {
  viewer {
    repositories(
      first: $first, after: $after, ownerAffiliations: OWNER, isFork: false
    ) {
      nodes {
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node {
              name
            }
          }
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""

PAGE_SIZE = 100

_PERSISTENT_GRAPHQL = {"FORBIDDEN", "INSUFFICIENT_SCOPES"}
_TRANSIENT_GRAPHQL = {"RATE_LIMITED"}
_TRANSIENT_HTTP = {408, 429}


def classify(status: int | None, errors: list[dict]) -> type[Exception] | None:
    """Map an HTTP status and GraphQL errors to an error class, or None if fine.

    `status` is None when no HTTP response arrived (network failure).
    """
    if status is None:
        return TransientError
    if status in _TRANSIENT_HTTP or status >= 500:
        return TransientError
    if status >= 400:
        return PersistentError
    if not errors:
        return None
    types = {e.get("type") for e in errors}
    if types & _TRANSIENT_GRAPHQL:
        return TransientError
    if types & _PERSISTENT_GRAPHQL:
        return PersistentError
    # Typeless or unrecognised errors look like blips, not a lost token.
    return TransientError


def with_retries(
    fn: Callable[[], T],
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call fn, retrying only TransientError, with 1s then 4s backoff."""
    for attempt in range(attempts):
        try:
            return fn()
        except TransientError:
            if attempt == attempts - 1:
                raise
            sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
    raise AssertionError("unreachable")  # pragma: no cover


def make_transport(token: str) -> GraphQL:
    """Build a GraphQL callable that POSTs to GitHub with transient retries."""

    def once(query: str, variables: dict) -> dict:
        body = json.dumps({"query": query, "variables": variables}).encode()
        request = urllib.request.Request(
            API_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "stats-scoreboard",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as exc:
            kind = classify(exc.code, [])
            raise (kind or PersistentError)(f"HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise TransientError("network error") from None

        try:
            parsed = json.loads(raw)
        except ValueError:
            raise TransientError("unreadable response") from None

        errors = parsed.get("errors") or []
        kind = classify(status, errors)
        if kind is not None:
            types = sorted({str(e.get("type", "UNKNOWN")) for e in errors})
            raise kind("GraphQL error: " + ",".join(types) if types else f"HTTP {status}")
        data = parsed.get("data")
        if not isinstance(data, dict):
            raise PersistentError("response had no data")
        return data

    def gql(query: str, variables: dict) -> dict:
        return with_retries(lambda: once(query, variables))

    return gql


def _window(gql: GraphQL, start: date, end: date) -> dict:
    variables = {
        "from": f"{start.isoformat()}T00:00:00Z",
        "to": f"{end.isoformat()}T23:59:59Z",
    }
    viewer = gql(CONTRIBUTIONS_QUERY, variables).get("viewer")
    if not isinstance(viewer, dict):
        raise PersistentError("malformed response: no viewer")
    return viewer


def _parse_window(viewer: dict) -> tuple[dict[str, int], dict[date, int]]:
    """Validate one window's payload and return (totals, calendar).

    Raises PersistentError on a malformed payload without having touched any
    caller state.
    """
    try:
        collection = viewer["contributionsCollection"]
        totals = {
            "commits": int(collection["totalCommitContributions"]),
            "pull_requests": int(collection["totalPullRequestContributions"]),
            "reviews": int(collection["totalPullRequestReviewContributions"]),
        }
        calendar: dict[date, int] = {}
        for week in collection["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                calendar[date.fromisoformat(day["date"])] = int(day["contributionCount"])
    except (KeyError, TypeError, ValueError, AttributeError):
        raise PersistentError("malformed response: contributions") from None
    return totals, calendar


def fetch_contributions(gql: GraphQL, today: date) -> AccountData:
    """Fetch all-time contribution counts and the daily calendar for the viewer.

    Current and previous calendar years must succeed. Older years are
    best-effort: a PersistentError there only marks history as incomplete.
    """
    calendar: dict[date, int] = {}
    totals = {"commits": 0, "pull_requests": 0, "reviews": 0}

    def absorb(viewer: dict) -> None:
        window_totals, window_calendar = _parse_window(viewer)
        for key, value in window_totals.items():
            totals[key] += value
        for day, count in window_calendar.items():
            # A date can appear in two windows; never let a smaller value win.
            calendar[day] = max(calendar.get(day, 0), count)

    # The current year goes first: its response also tells us when the account
    # was created, which bounds every other window.
    current = _window(gql, date(today.year, 1, 1), today)
    try:
        login = str(current["login"])
        created = date.fromisoformat(current["createdAt"][:10])
    except (KeyError, TypeError, ValueError):
        raise PersistentError("malformed response: account") from None
    absorb(current)

    history_complete = True
    for year in range(today.year - 1, created.year - 1, -1):
        start = max(date(year, 1, 1), created)
        try:
            absorb(_window(gql, start, date(year, 12, 31)))
        except PersistentError:
            if year == today.year - 1:
                raise
            history_complete = False

    return AccountData(
        login=login,
        calendar=calendar,
        commits=totals["commits"],
        pull_requests=totals["pull_requests"],
        reviews=totals["reviews"],
        history_complete=history_complete,
    )


def _repo_nodes(gql: GraphQL, query: str) -> Iterator[dict]:
    """Yield each repository node across all pages of the viewer's repos."""
    cursor: str | None = None
    while True:
        previous = cursor
        viewer = gql(query, {"first": PAGE_SIZE, "after": cursor}).get("viewer")
        try:
            repos = viewer["repositories"]
            nodes = repos["nodes"]
            page = repos["pageInfo"]
            has_next = bool(page["hasNextPage"])
            cursor = page.get("endCursor")
            if not isinstance(nodes, list):
                raise TypeError
        except (KeyError, TypeError, AttributeError):
            raise PersistentError("malformed response: repositories") from None
        for node in nodes:
            if not isinstance(node, dict):
                raise PersistentError("malformed response: repositories")
            yield node
        if not has_next:
            return
        if not cursor:
            raise PersistentError("malformed response: missing page cursor")
        if cursor == previous:
            raise PersistentError("malformed response: page cursor did not advance")


def fetch_stars(gql: GraphQL) -> int:
    """Total stargazers across the viewer's owned, public repositories."""
    total = 0
    for node in _repo_nodes(gql, STARS_QUERY):
        try:
            total += int(node["stargazerCount"])
        except (KeyError, TypeError, ValueError):
            raise PersistentError("malformed response: stars") from None
    return total


def fetch_languages(gql: GraphQL) -> dict[str, int]:
    """Bytes per language across the viewer's owned, non-fork repositories.

    Repository names are never requested, so none can be kept.
    """
    languages: dict[str, int] = {}
    for node in _repo_nodes(gql, LANGUAGES_QUERY):
        try:
            edges = (node["languages"] or {}).get("edges") or []
            parsed = [(str(e["node"]["name"]), int(e["size"])) for e in edges]
        except (KeyError, TypeError, ValueError):
            raise PersistentError("malformed response: languages") from None
        for name, size in parsed:
            languages[name] = languages.get(name, 0) + size
    return languages
