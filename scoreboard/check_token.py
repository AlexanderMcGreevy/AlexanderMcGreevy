"""First-gate check: can each token read its account's contributions?

Usage: PERSONAL_GH_TOKEN=... WORK_GH_TOKEN=... python -m scoreboard.check_token

Prints only: which token is set, OK/FAIL with the error class name, the number
of calendar days, and all-time counts. No repo names, no token values.
"""

from __future__ import annotations

import os
import sys
from datetime import date

from .github import fetch_contributions, make_transport

TOKENS = ("PERSONAL_GH_TOKEN", "WORK_GH_TOKEN")


def check(env_name: str, token: str | None) -> bool:
    print(f"{env_name}: {'set' if token else 'NOT SET'}")
    if not token:
        return False
    try:
        account = fetch_contributions(make_transport(token), date.today())
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
    return True


def main() -> int:
    results = [check(name, os.environ.get(name)) for name in TOKENS]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
