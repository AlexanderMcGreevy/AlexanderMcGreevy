"""The daily run: fetch both accounts, apply the failure policy, render, and
write the board only when something other than the visitors readout changed.

Exit codes returned by `run`:

    0  healthy
    2  transient failure (or any personal failure); nothing was written
    3  board written (or already current) but degraded: a persistent problem
       that needs fixing, such as a lost work token

When several conditions apply the result is 2 if any is transient, else 3 if
any is degraded, else 0.

Logs carry section names, ok/failed, exception class names and counts only.
Exception messages, logins, tokens, repo and org names are never printed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date
from pathlib import Path

from . import github
from .errors import PersistentError
from .github import GraphQL
from .models import AccountData, BoardData
from .render import VISITORS_ID, render_narrow, render_wide
from .stats import compute_stats
from .visitors import atomic_write_text, load_state, save_state

OK, TRANSIENT, DEGRADED = 0, 2, 3

PERSONAL_ENV = "PERSONAL_GH_TOKEN"
WORK_ENV = "WORK_GH_TOKEN"

ASSETS_DIR = "assets"
WIDE_FILE = "scoreboard.svg"
NARROW_FILE = "scoreboard-narrow.svg"
STATE_FILE = "state.json"

_VISITORS_OPEN = re.compile(r'<g\b[^>]*\sid="%s"[^>]*>' % re.escape(VISITORS_ID))
_G_TAG = re.compile(r"<(/?)g\b[^>]*?(/?)>")


def strip_volatile(svg: str) -> str:
    """Remove the `<g id="visitors">...</g>` element (and everything in it).

    What remains is what change detection compares: the visitors number and
    its "as of" date alone never count as a change.
    """
    out: list[str] = []
    pos = 0
    while (start := _VISITORS_OPEN.search(svg, pos)) is not None:
        out.append(svg[pos:start.start()])
        if start.group(0).endswith("/>"):
            pos = start.end()
            continue
        depth = 1
        for tag in _G_TAG.finditer(svg, start.end()):
            if tag.group(1):
                depth -= 1
            elif not tag.group(2):
                depth += 1
            if depth == 0:
                pos = tag.end()
                break
        else:  # unbalanced markup: leave the rest untouched
            out.append(svg[start.start():])
            return "".join(out)
    out.append(svg[pos:])
    return "".join(out)


# --- logging -----------------------------------------------------------------

def _log(line: str) -> None:
    print(line, flush=True)


def _failed(section: str, exc: BaseException) -> None:
    # The class name only: messages stay out of logs, whatever they contain.
    _log(f"{section}: failed ({type(exc).__name__})")


def _warn(message: str) -> None:
    _log(f"::warning::{message}")


def _counts(account: AccountData) -> str:
    active = sum(1 for n in account.calendar.values() if n > 0)
    return (f"{len(account.calendar)} days, {active} active, {account.commits} commits, "
            f"{account.pull_requests} pull requests, {account.reviews} reviews")


# --- fetching ----------------------------------------------------------------

def _fetch_personal(env: Mapping[str, str], today: date,
                    gql_factory: Callable[[str], GraphQL]) -> AccountData | None:
    """Personal data, complete, or None: any personal failure stops the run."""
    token = env.get(PERSONAL_ENV)
    if not token:
        _log(f"personal contributions: failed ({PERSONAL_ENV} not set)")
        return None
    section = "personal contributions"
    try:
        gql = gql_factory(token)
        account = github.fetch_contributions(gql, today)
        _log(f"{section}: ok ({_counts(account)})")
        if not account.history_complete:
            # Older personal years failing would understate the all-time row.
            _log("personal history: failed (older years unavailable)")
            return None
        section = "personal stars"
        stars = github.fetch_stars(gql)
        _log(f"{section}: ok ({stars})")
        section = "personal languages"
        languages = github.fetch_languages(gql)
        _log(f"{section}: ok ({len(languages)} languages)")
    except Exception as exc:
        _failed(section, exc)
        return None
    return replace(account, stars=stars, languages=languages)


def _is_empty(account: AccountData) -> bool:
    totals = account.commits + account.pull_requests + account.reviews
    return totals == 0 and not any(n > 0 for n in account.calendar.values())


def _fetch_work(env: Mapping[str, str], today: date,
                gql_factory: Callable[[str], GraphQL]) -> tuple[AccountData | None, int]:
    """(work data or None, status). Stars are personal only, so never fetched."""
    token = env.get(WORK_ENV)
    if not token:
        _log(f"work contributions: failed ({WORK_ENV} not set)")
        _warn(f"{WORK_ENV} is not set; the board shows personal data only.")
        return None, DEGRADED

    try:
        gql = gql_factory(token)
        account = github.fetch_contributions(gql, today)
    except PersistentError as exc:
        _failed("work contributions", exc)
        _warn("Work contributions failed persistently (token expired, revoked or blocked?); "
              "the board shows personal data only.")
        return None, DEGRADED
    except Exception as exc:  # TransientError, or anything unexpected
        _failed("work contributions", exc)
        return None, TRANSIENT
    _log(f"work contributions: ok ({_counts(account)})")

    if _is_empty(account):
        _warn("Work account returned no contributions at all; treated as unavailable, "
              "the board shows personal data only.")
        return None, DEGRADED

    status = OK
    if not account.history_complete:
        _log("work history: failed (older years unavailable)")
        _warn("Work history is incomplete; all-time figures show personal data only.")
        status = DEGRADED

    try:
        languages: dict[str, int] | None = github.fetch_languages(gql)
    except PersistentError as exc:
        # Expected when a read-only token cannot read private repos.
        _failed("work languages", exc)
        languages = None
    except Exception as exc:
        _failed("work languages", exc)
        return None, TRANSIENT
    else:
        _log(f"work languages: ok ({len(languages)} languages)")
    return replace(account, languages=languages), status


def _visitors(fetch_visitors: Callable[[], int | None], state_path: Path,
              today: date) -> tuple[int | None, date | None]:
    """Fetched count, else the last known one from state, else (None, None)."""
    try:
        count = fetch_visitors()
    except Exception:
        count = None
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
        _log(f"visitors: ok ({count})")
        return count, today
    known, as_of = load_state(state_path)
    if known is not None:
        _log(f"visitors: failed, using last known ({known})")
        return known, as_of
    _log("visitors: failed, omitted")
    return None, None


# --- writing -----------------------------------------------------------------

def _changed(path: Path, svg: str) -> bool:
    try:
        existing = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return True
    return strip_volatile(existing) != strip_volatile(svg)


def run(env: Mapping[str, str], out_dir: Path, today: date,
        gql_factory: Callable[[str], GraphQL],
        fetch_visitors: Callable[[], int | None]) -> int:
    """Fetch, apply the failure policy, render, write if changed; return the exit code."""
    personal = _fetch_personal(env, today, gql_factory)
    if personal is None:
        _log("::error::Personal data could not be fetched; nothing was written.")
        return TRANSIENT

    work, status = _fetch_work(env, today, gql_factory)
    if status == TRANSIENT:
        _log("::error::Work data failed transiently; the last good board is kept.")
        return TRANSIENT

    assets = Path(out_dir) / ASSETS_DIR
    state_path = assets / STATE_FILE
    count, as_of = _visitors(fetch_visitors, state_path, today)

    scope = "combined" if work is not None and work.languages else "personal"
    _log(f"languages: {scope}")
    stats = compute_stats(BoardData(
        today=today,
        personal=personal,
        work=work,
        languages_scope=scope,
        visitors=count,
        visitors_as_of=as_of,
    ))
    outputs = {assets / WIDE_FILE: render_wide(stats),
               assets / NARROW_FILE: render_narrow(stats)}

    if any(_changed(path, svg) for path, svg in outputs.items()):
        for path, svg in outputs.items():
            atomic_write_text(path, svg)
        if count is not None and as_of is not None:
            save_state(state_path, count, as_of)
        _log("board: written")
    else:
        _log("board: unchanged")
    return status
