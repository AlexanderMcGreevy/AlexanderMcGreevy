"""Plain data models. Counts and dates only; nothing that names a repo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class AccountData:
    login: str
    calendar: dict[date, int]
    commits: int
    pull_requests: int
    reviews: int
    history_complete: bool = True
    stars: int | None = None
    languages: dict[str, int] | None = None
