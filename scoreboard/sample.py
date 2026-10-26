"""Deterministic FAKE board data for previews and tests only.

Nothing here is real. The logins are `sample` / `sample-work`, and every number
is generated from a fixed seed. The live pipeline never imports this module.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

from .models import AccountData, BoardData

SAMPLE_TODAY = date(2026, 10, 25)
_DAYS = 730  # two years of history, so the best streak can predate the window


def _calendar(rng: random.Random, today: date, rate: float, weekend: float,
              peak: int) -> dict[date, int]:
    cal: dict[date, int] = {}
    for back in range(_DAYS):
        day = today - timedelta(days=back)
        week = back // 7
        busy = 0.35 + 0.45 * math.sin(week / 6) + 0.2 * rng.random()
        if day.weekday() >= 5:
            busy *= weekend
        if rng.random() < busy * rate:
            cal[day] = rng.randint(1, peak)
    return cal


def _with_run(cal: dict[date, int], end: date, days: int) -> dict[date, int]:
    """Make the `days` days ending on `end` active (a streak for previews)."""
    out = dict(cal)
    for back in range(days):
        day = end - timedelta(days=back)
        out[day] = max(out.get(day, 0), 1 + back % 3)
    return out


def sample_board_data() -> BoardData:
    """A combined board with both accounts present and a visitors count."""
    rng = random.Random(41)
    personal = AccountData(
        login="sample",
        calendar=_with_run(_with_run(
            _calendar(rng, SAMPLE_TODAY, rate=0.55, weekend=0.6, peak=4),
            SAMPLE_TODAY, 14), date(2025, 3, 21), 31),
        commits=1310,
        pull_requests=31,
        reviews=4,
        history_complete=True,
        stars=5,
        languages={"Swift": 74_000, "Jupyter Notebook": 11_000, "Python": 7_000,
                   "Java": 5_000, "TypeScript": 2_000, "Shell": 1_000},
    )
    work = AccountData(
        login="sample-work",
        calendar=_calendar(rng, SAMPLE_TODAY, rate=0.85, weekend=0.2, peak=6),
        commits=1537,
        pull_requests=112,
        reviews=92,
        history_complete=True,
        stars=None,
        languages=None,
    )
    return BoardData(
        today=SAMPLE_TODAY,
        personal=personal,
        work=work,
        languages_scope="combined",
        visitors=658,
        visitors_as_of=SAMPLE_TODAY,
    )
