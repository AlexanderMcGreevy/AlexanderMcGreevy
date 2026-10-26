"""Plain data models. Counts and dates only; nothing that names a repo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal


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


@dataclass(frozen=True)
class BoardData:
    today: date
    personal: AccountData
    work: AccountData | None  # None: work data is unavailable
    languages_scope: Literal["combined", "personal"]
    visitors: int | None
    visitors_as_of: date | None


@dataclass(frozen=True)
class Split:
    total: int
    personal: int
    work: int | None  # None renders the personal-only form


@dataclass(frozen=True)
class AllTime:
    commits: Split
    pull_requests: Split
    reviews: Split


@dataclass(frozen=True)
class BoardStats:
    year_total: int
    year_personal: int
    year_work: int | None
    current_streak: int
    best_streak: int
    best_streak_end: date | None
    best_streak_window_only: bool
    all_time: AllTime
    stars: int | None
    languages: list[tuple[str, int]]
    weeks: list[list[int | None]]
    month_labels: list[tuple[int, str]]
    work_available: bool
    all_time_work_available: bool
    languages_scope: str
    visitors: int | None
    visitors_as_of: date | None
