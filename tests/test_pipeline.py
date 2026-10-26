import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from scoreboard import github, pipeline, visitors
from scoreboard.errors import PersistentError, TransientError

TODAY = date(2026, 10, 25)
PERSONAL_TOKEN = "ghp_PERSONALtokenVALUE0001"
WORK_TOKEN = "ghp_WORKtokenVALUE0002"
ENV = {"PERSONAL_GH_TOKEN": PERSONAL_TOKEN, "WORK_GH_TOKEN": WORK_TOKEN}
SECRETS = ("secret-repo", "secret-org", PERSONAL_TOKEN, WORK_TOKEN)

PERSONAL_DAYS = {date(2026, 10, 25): 2, date(2026, 10, 24): 3, date(2026, 3, 1): 5,
                 date(2025, 6, 1): 1}
WORK_DAYS = {date(2026, 10, 23): 4, date(2026, 10, 22): 6, date(2025, 12, 1): 1}


class FakeAccount:
    """A fake GraphQL callable for one account.

    Every payload carries repo and org names the code must never keep, so the
    privacy test can prove they never reach any output.
    """

    def __init__(self, login, days, commits=0, prs=0, reviews=0, created="2025-01-01",
                 stars=0, languages=None, fail=None, fail_years=None,
                 stars_fail=None, languages_fail=None):
        self.login = login
        self.days = dict(days)
        self.totals = (commits, prs, reviews)
        self.created = created
        self.stars = stars
        self.languages = languages or {}
        self.fail = fail
        self.fail_years = fail_years or {}
        self.stars_fail = stars_fail
        self.languages_fail = languages_fail
        self.queries = []

    def __call__(self, query, variables):
        self.queries.append(query)
        if self.fail is not None:
            raise self.fail
        if query == github.CONTRIBUTIONS_QUERY:
            return self._contributions(int(variables["from"][:4]))
        if query == github.STARS_QUERY:
            if self.stars_fail is not None:
                raise self.stars_fail
            return self._repos([{"stargazerCount": self.stars,
                                 "nameWithOwner": "secret-org/secret-repo"}])
        if query == github.LANGUAGES_QUERY:
            if self.languages_fail is not None:
                raise self.languages_fail
            edges = [{"size": size, "node": {"name": name}}
                     for name, size in self.languages.items()]
            return self._repos([{"languages": {"edges": edges},
                                 "nameWithOwner": "secret-org/secret-repo",
                                 "owner": {"login": "secret-org"}}])
        raise AssertionError("unexpected query")

    def _repos(self, nodes):
        return {"viewer": {"repositories": {
            "nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}}

    def _contributions(self, year):
        if year in self.fail_years:
            raise self.fail_years[year]
        commits, prs, reviews = self.totals if year == TODAY.year else (0, 0, 0)
        days = [{"date": d.isoformat(), "contributionCount": n}
                for d, n in sorted(self.days.items()) if d.year == year]
        return {"viewer": {
            "login": self.login,
            "createdAt": f"{self.created}T00:00:00Z",
            "contributionsCollection": {
                "totalCommitContributions": commits,
                "totalPullRequestContributions": prs,
                "totalPullRequestReviewContributions": reviews,
                "contributionCalendar": {"weeks": [{"contributionDays": days}]},
                "commitContributionsByRepository": [
                    {"repository": {"nameWithOwner": "secret-org/secret-repo"}}],
            },
        }}


def personal(**kw):
    args = dict(login="alex", days=PERSONAL_DAYS, commits=40, prs=6, reviews=2, stars=5,
                languages={"Swift": 7000, "Python": 3000})
    args.update(kw)
    return FakeAccount(**args)


def work(**kw):
    args = dict(login="secret-org-bot", days=WORK_DAYS, commits=90, prs=12, reviews=30,
                languages={"TypeScript": 9000, "Go": 1000})
    args.update(kw)
    return FakeAccount(**args)


def factory(p=None, w=None):
    accounts = {PERSONAL_TOKEN: p or personal(), WORK_TOKEN: w or work()}
    return lambda token: accounts[token]


def run(tmp_path, *, p=None, w=None, env=ENV, count=658, today=TODAY):
    return pipeline.run(env, tmp_path, today, factory(p, w), lambda: count)


def wide(tmp_path):
    return (tmp_path / "assets" / "scoreboard.svg").read_text(encoding="utf-8")


def narrow(tmp_path):
    return (tmp_path / "assets" / "scoreboard-narrow.svg").read_text(encoding="utf-8")


def state(tmp_path):
    return json.loads((tmp_path / "assets" / "state.json").read_text(encoding="utf-8"))


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


# --- strip_volatile ------------------------------------------------------------

def test_strip_volatile_removes_only_the_visitors_group():
    svg = ('<svg><g id="year"><g class="kpi" transform="t">A</g>'
           '<g class="kpi" id="visitors" transform="x"><g>inner</g><text>000658</text></g>'
           '</g><g id="all-time">B</g></svg>')
    assert pipeline.strip_volatile(svg) == (
        '<svg><g id="year"><g class="kpi" transform="t">A</g></g><g id="all-time">B</g></svg>')


def test_strip_volatile_without_visitors_is_identity():
    svg = '<svg><g id="year"><g class="kpi">A</g></g></svg>'
    assert pipeline.strip_volatile(svg) == svg


def test_strip_volatile_ignores_other_ids_containing_visitors():
    svg = '<svg><g id="visitors-old">A</g><clipPath id="visitors-clip"/></svg>'
    assert pipeline.strip_volatile(svg) == svg


def test_strip_volatile_on_real_boards_differs_only_by_visitors(tmp_path):
    assert run(tmp_path / "a", count=658) == 0
    assert run(tmp_path / "b", count=91234) == 0
    for read in (wide, narrow):
        a, b = read(tmp_path / "a"), read(tmp_path / "b")
        assert a != b
        assert pipeline.strip_volatile(a) == pipeline.strip_volatile(b)
        assert 'id="visitors"' not in pipeline.strip_volatile(a)


# --- healthy runs and change detection -------------------------------------------

def test_healthy_run_writes_both_svgs_and_state(tmp_path, capsys):
    assert run(tmp_path) == 0
    assert 'viewBox="0 0 760' in wide(tmp_path)
    assert 'viewBox="0 0 390' in narrow(tmp_path)
    assert state(tmp_path) == {"visitors": 658, "as_of": "2026-10-25"}
    for svg in (wide(tmp_path), narrow(tmp_path)):
        assert "2 ACCOUNTS" in svg
        assert "PERSONAL ONLY" not in svg
        assert "PERSONAL REPOS" not in svg
        assert "TYPESCRIPT" in svg  # work languages are combined in
        assert "</tspan>658<" in svg
    assert "::warning::" not in capsys.readouterr().out


def test_unchanged_data_does_not_rewrite(tmp_path):
    assert run(tmp_path, count=658) == 0
    before = snapshot(tmp_path)
    assert run(tmp_path, count=700) == 0
    assert snapshot(tmp_path) == before
    assert state(tmp_path) == {"visitors": 658, "as_of": "2026-10-25"}


def test_visitors_date_alone_does_not_rewrite(tmp_path):
    assert run(tmp_path, count=658) == 0
    (tmp_path / "assets" / "state.json").unlink()
    visitors.save_state(tmp_path / "assets" / "state.json", 650, date(2026, 10, 1))
    before = snapshot(tmp_path)
    assert pipeline.run(ENV, tmp_path, TODAY, factory(), lambda: None) == 0
    assert snapshot(tmp_path) == before


def test_changed_data_rewrites_with_fresh_visitors(tmp_path):
    assert run(tmp_path, count=658) == 0
    old_wide, old_narrow = wide(tmp_path), narrow(tmp_path)
    days = dict(PERSONAL_DAYS)
    days[date(2026, 10, 20)] = 9
    assert run(tmp_path, p=personal(days=days), count=700) == 0
    assert wide(tmp_path) != old_wide and narrow(tmp_path) != old_narrow
    assert "</tspan>700<" in wide(tmp_path)
    assert "</tspan>700<" in narrow(tmp_path)
    assert state(tmp_path) == {"visitors": 700, "as_of": "2026-10-25"}


def test_missing_files_are_written_even_if_one_exists(tmp_path):
    assert run(tmp_path) == 0
    (tmp_path / "assets" / "scoreboard-narrow.svg").unlink()
    assert run(tmp_path, count=700) == 0
    assert "</tspan>700<" in narrow(tmp_path)
    assert "</tspan>700<" in wide(tmp_path)


# --- failure policy ---------------------------------------------------------------

def test_personal_transient_failure_writes_nothing(tmp_path, capsys):
    assert run(tmp_path) == 0
    before = snapshot(tmp_path)
    assert run(tmp_path, p=personal(fail=TransientError("x")), count=700) == 2
    assert snapshot(tmp_path) == before
    assert "::error::" in capsys.readouterr().out


def test_personal_failure_on_empty_out_dir_writes_nothing(tmp_path):
    assert run(tmp_path, p=personal(fail=TransientError("x"))) == 2
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("p", [
    lambda: personal(fail=PersistentError("x")),
    lambda: personal(stars_fail=PersistentError("x")),
    lambda: personal(languages_fail=TransientError("x")),
    lambda: personal(fail=ValueError("unexpected")),
    lambda: personal(created="2023-01-01", fail_years={2023: PersistentError("x")}),
])
def test_any_personal_failure_writes_nothing(tmp_path, p):
    assert run(tmp_path) == 0
    before = snapshot(tmp_path)
    assert run(tmp_path, p=p(), count=700) == 2
    assert snapshot(tmp_path) == before


def test_missing_personal_token_writes_nothing(tmp_path):
    assert run(tmp_path, env={"WORK_GH_TOKEN": WORK_TOKEN}) == 2
    assert list(tmp_path.iterdir()) == []


def test_work_transient_failure_keeps_last_good_board(tmp_path):
    assert run(tmp_path) == 0
    before = snapshot(tmp_path)
    assert run(tmp_path, w=work(fail=TransientError("x")), count=700) == 2
    assert snapshot(tmp_path) == before


def test_work_unexpected_error_is_treated_as_transient(tmp_path):
    assert run(tmp_path) == 0
    before = snapshot(tmp_path)
    assert run(tmp_path, w=work(fail=KeyError("secret-repo"))) == 2
    assert snapshot(tmp_path) == before


def test_work_languages_transient_failure_keeps_last_good_board(tmp_path):
    assert run(tmp_path) == 0
    before = snapshot(tmp_path)
    assert run(tmp_path, w=work(languages_fail=TransientError("x"))) == 2
    assert snapshot(tmp_path) == before


def test_work_persistent_failure_publishes_personal_only(tmp_path, capsys):
    assert run(tmp_path, w=work(fail=PersistentError("x"))) == 3
    for svg in (wide(tmp_path), narrow(tmp_path)):
        assert "PERSONAL ONLY" in svg
        assert "2 ACCOUNTS" not in svg
    assert "::warning::" in capsys.readouterr().out


def test_missing_work_token_publishes_personal_only(tmp_path, capsys):
    assert run(tmp_path, env={"PERSONAL_GH_TOKEN": PERSONAL_TOKEN}) == 3
    assert "PERSONAL ONLY" in wide(tmp_path)
    assert "PERSONAL ONLY" in narrow(tmp_path)
    assert "::warning::" in capsys.readouterr().out


def test_empty_work_token_publishes_personal_only(tmp_path):
    assert run(tmp_path, env={"PERSONAL_GH_TOKEN": PERSONAL_TOKEN, "WORK_GH_TOKEN": ""}) == 3
    assert "PERSONAL ONLY" in wide(tmp_path)


def test_empty_work_calendar_is_treated_as_missing(tmp_path, capsys):
    zero = work(days={date(2026, 10, 1): 0}, commits=0, prs=0, reviews=0)
    assert run(tmp_path, w=zero) == 3
    for svg in (wide(tmp_path), narrow(tmp_path)):
        assert "PERSONAL ONLY" in svg
        assert "2 ACCOUNTS" not in svg
        assert " WORK<" not in svg  # no "N PERSONAL · 0 WORK" combined split
        assert " W<" not in svg  # no all-time work breakdown
    assert "::warning::" in capsys.readouterr().out


def test_work_with_activity_but_zero_totals_is_kept(tmp_path):
    assert run(tmp_path, w=work(commits=0, prs=0, reviews=0)) == 0
    assert "2 ACCOUNTS" in wide(tmp_path)


def test_work_languages_unavailable_falls_back_to_personal_scope(tmp_path, capsys):
    assert run(tmp_path, w=work(languages_fail=PersistentError("x"))) == 0
    for svg in (wide(tmp_path), narrow(tmp_path)):
        assert "// LANGUAGES · PERSONAL REPOS" in svg
        assert "2 ACCOUNTS" in svg
        assert "TYPESCRIPT" not in svg  # language names render upper-case
        assert "SWIFT" in svg
    assert "::warning::" not in capsys.readouterr().out


def test_work_languages_empty_falls_back_to_personal_scope(tmp_path):
    assert run(tmp_path, w=work(languages={})) == 0
    assert "// LANGUAGES · PERSONAL REPOS" in wide(tmp_path)


def test_work_stars_are_never_requested(tmp_path):
    w = work()
    assert run(tmp_path, w=w) == 0
    assert github.STARS_QUERY not in w.queries


def test_work_history_incomplete_is_degraded(tmp_path, capsys):
    w = work(created="2023-01-01", fail_years={2023: PersistentError("x")})
    assert run(tmp_path, w=w) == 3
    svg = wide(tmp_path)
    assert "2 ACCOUNTS" in svg  # calendar still combined
    assert "// ALL TIME · PERSONAL ONLY" in svg
    assert "::warning::" in capsys.readouterr().out


def test_transient_wins_over_degraded(tmp_path):
    w = work(created="2023-01-01", fail_years={2023: PersistentError("x")},
             languages_fail=TransientError("x"))
    assert run(tmp_path, w=w) == 2
    assert list(tmp_path.iterdir()) == []


def test_degraded_run_with_unchanged_board_still_exits_3(tmp_path):
    env = {"PERSONAL_GH_TOKEN": PERSONAL_TOKEN}
    assert run(tmp_path, env=env) == 3
    before = snapshot(tmp_path)
    assert run(tmp_path, env=env, count=700) == 3
    assert snapshot(tmp_path) == before


def test_recovered_work_data_replaces_personal_only_board(tmp_path):
    assert run(tmp_path, env={"PERSONAL_GH_TOKEN": PERSONAL_TOKEN}) == 3
    assert run(tmp_path) == 0
    assert "2 ACCOUNTS" in wide(tmp_path)


# --- visitors ---------------------------------------------------------------------

def test_visitors_failure_keeps_last_known(tmp_path):
    visitors.save_state(tmp_path / "assets" / "state.json", 700, date(2026, 10, 1))
    assert pipeline.run(ENV, tmp_path, TODAY, factory(), lambda: None) == 0
    for svg in (wide(tmp_path), narrow(tmp_path)):
        assert "</tspan>700<" in svg
        assert "AS OF OCT 1<" in svg
    assert state(tmp_path) == {"visitors": 700, "as_of": "2026-10-01"}


def test_visitors_failure_without_state_omits_group(tmp_path):
    assert pipeline.run(ENV, tmp_path, TODAY, factory(), lambda: None) == 0
    assert 'id="visitors"' not in wide(tmp_path)
    assert 'id="visitors"' not in narrow(tmp_path)
    assert not (tmp_path / "assets" / "state.json").exists()


@pytest.mark.parametrize("bad", [-5, True, "658", 6.5])
def test_invalid_visitors_count_is_ignored(tmp_path, bad):
    visitors.save_state(tmp_path / "assets" / "state.json", 700, date(2026, 10, 1))
    assert pipeline.run(ENV, tmp_path, TODAY, factory(), lambda: bad) == 0
    assert "</tspan>700<" in wide(tmp_path)


def test_visitors_fetch_raising_falls_back(tmp_path):
    def boom():
        raise OSError("down")

    visitors.save_state(tmp_path / "assets" / "state.json", 700, date(2026, 10, 1))
    assert pipeline.run(ENV, tmp_path, TODAY, factory(), boom) == 0
    assert "</tspan>700<" in wide(tmp_path)


# --- privacy ----------------------------------------------------------------------

@pytest.mark.parametrize("w", [
    lambda: work(),
    lambda: work(fail=PersistentError("secret-org/secret-repo")),
    lambda: work(fail=TransientError("secret-org/secret-repo")),
    lambda: work(fail=RuntimeError("secret-org/secret-repo")),
    lambda: work(languages_fail=PersistentError("secret-org/secret-repo")),
    lambda: work(created="2023-01-01",
                 fail_years={2023: PersistentError("secret-org/secret-repo")}),
])
def test_no_private_details_in_outputs_or_logs(tmp_path, capsys, w):
    run(tmp_path, w=w())
    captured = capsys.readouterr()
    blobs = [captured.out, captured.err]
    blobs += [p.read_text(encoding="utf-8") for p in tmp_path.rglob("*") if p.is_file()]
    assert captured.out  # it does log something
    for blob in blobs:
        for secret in SECRETS:
            assert secret not in blob
        assert "secret-org-bot" not in blob  # the work login is not shown either


def test_logs_report_sections_and_counts(tmp_path, capsys):
    assert run(tmp_path) == 0
    out = capsys.readouterr().out
    assert "personal contributions: ok" in out
    assert "work contributions: ok" in out
    assert "visitors: ok (658)" in out
    assert "board: written" in out


# --- entry point ------------------------------------------------------------------

def test_main_runs_pipeline_with_real_dependencies(monkeypatch, tmp_path):
    from scoreboard import __main__ as cli

    seen = {}

    def fake_run(env, out_dir, today, gql_factory, fetch_visitors):
        seen.update(env=env, out_dir=out_dir, today=today, gql_factory=gql_factory,
                    fetch_visitors=fetch_visitors)
        return 3

    monkeypatch.setattr(cli.pipeline, "run", fake_run)
    assert cli.main([]) == 3
    assert seen["env"] is os.environ
    assert seen["out_dir"] == Path(".")
    assert seen["today"] == date.today()
    assert seen["gql_factory"] is github.make_transport
    assert seen["fetch_visitors"] is visitors.fetch_count

    assert cli.main(["--out", str(tmp_path)]) == 3
    assert seen["out_dir"] == tmp_path


def test_live_path_never_imports_sample():
    code = ("import sys, scoreboard.__main__, scoreboard.pipeline; "
            "print('scoreboard.sample' in sys.modules)")
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True,
                            text=True, check=True)
    assert result.stdout.strip() == "False"


# --- state file (carry-over rulings) ---------------------------------------------

def test_save_state_creates_parent_directory(tmp_path):
    path = tmp_path / "a" / "b" / "state.json"
    visitors.save_state(path, 12, TODAY)
    assert visitors.load_state(path) == (12, TODAY)
    assert [p.name for p in path.parent.iterdir()] == ["state.json"]


def test_save_state_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    visitors.save_state(path, 12, TODAY)

    def fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(visitors.os, "replace", fail)
    with pytest.raises(OSError):
        visitors.save_state(path, 99, TODAY)
    assert visitors.load_state(path) == (12, TODAY)
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_load_state_rejects_negative_count(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"visitors": -1, "as_of": "2026-10-25"}))
    assert visitors.load_state(path) == (None, None)
