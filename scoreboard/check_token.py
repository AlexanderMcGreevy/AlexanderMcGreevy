"""First-gate check: can each token read its account's contributions?

Usage: PERSONAL_GH_TOKEN=... WORK_GH_TOKEN=... python -m scoreboard.check_token

Prints only: which token is set, OK/FAIL with the error class name, the number
of calendar days, all-time counts, the star total and the number of languages.
No repo names, no token values.
"""

from __future__ import annotations

import os
import sys
from datetime import date

from .github import fetch_contributions, fetch_languages, fetch_stars, make_transport

TOKENS = ("PERSONAL_GH_TOKEN", "WORK_GH_TOKEN")


def check(env_name: str, token: str | None) -> bool:
    print(f"{env_name}: {'set' if token else 'NOT SET'}")
    if not token:
        return False
    try:
        gql = make_transport(token)
        account = fetch_contributions(gql, date.today())
    except Exception as exc:  # report the class only; messages stay out of output
        print(f"  contributions: FAIL ({type(exc).__name__})")
        return False
    print("  contributions: OK")
    print(f"  calendar days: {len(account.calendar)}")
    print(f"  commits: {account.commits}")
    print(f"  pull requests: {account.pull_requests}")
    print(f"  reviews: {account.reviews}")
    if not account.history_complete:
        print("  history: INCOMPLETE (older years failed)")
    # Languages and stars are informational: the work token may be unable to
    # read private-repo languages, which is exactly what this reveals.
    for label, fetch, show in (
        ("stars", fetch_stars, lambda value: value),
        ("languages", fetch_languages, len),
    ):
        try:
            print(f"  {label}: OK ({show(fetch(gql))})")
        except Exception as exc:
            print(f"  {label}: FAIL ({type(exc).__name__})")
    return True


def main() -> int:
    results = [check(name, os.environ.get(name)) for name in TOKENS]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
