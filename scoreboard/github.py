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
from collections.abc import Callable
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

_PERSISTENT_GRAPHQL = {"FORBIDDEN", "INSUFFICIENT_SCOPES"}
_TRANSIENT_GRAPHQL = {"RATE_LIMITED"}


def classify(status: int | None, errors: list[dict]) -> type[Exception] | None:
    """Map an HTTP status and GraphQL errors to an error class, or None if fine.

    `status` is None when no HTTP response arrived (network failure).
    """
    if status is None:
        return TransientError
    if status == 429 or status >= 500:
        return TransientError
    if status >= 400:
        return PersistentError
    types = {e.get("type") for e in errors or []}
    if types & _TRANSIENT_GRAPHQL:
        return TransientError
    if types & _PERSISTENT_GRAPHQL:
        return PersistentError
    if types:
        # Unrecognised GraphQL errors (e.g. a bad query) will not fix themselves.
        return PersistentError
    return None


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
    return gql(CONTRIBUTIONS_QUERY, variables)["viewer"]


def fetch_contributions(gql: GraphQL, today: date) -> AccountData:
    """Fetch all-time contribution counts and the daily calendar for the viewer.

    Current and previous calendar years must succeed. Older years are
    best-effort: a PersistentError there only marks history as incomplete.
    """
    calendar: dict[date, int] = {}
    totals = {"commits": 0, "pull_requests": 0, "reviews": 0}

    def absorb(viewer: dict) -> None:
        collection = viewer["contributionsCollection"]
        totals["commits"] += collection["totalCommitContributions"]
        totals["pull_requests"] += collection["totalPullRequestContributions"]
        totals["reviews"] += collection["totalPullRequestReviewContributions"]
        for week in collection["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                calendar[date.fromisoformat(day["date"])] = day["contributionCount"]

    # The current year goes first: its response also tells us when the account
    # was created, which bounds every other window.
    current = _window(gql, date(today.year, 1, 1), today)
    login = current["login"]
    created = date.fromisoformat(current["createdAt"][:10])
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
