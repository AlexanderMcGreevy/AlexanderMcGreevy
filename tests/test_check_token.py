from datetime import date

from scoreboard import check_token
from scoreboard.errors import PersistentError
from scoreboard.models import AccountData


def test_prints_counts_only(monkeypatch, capsys):
    account = AccountData("alex-secret-login", {date(2026, 1, 1): 3}, 7, 2, 1)
    monkeypatch.setattr(check_token, "make_transport", lambda token: None)
    monkeypatch.setattr(check_token, "fetch_contributions", lambda gql, today: account)
    assert check_token.check("WORK_GH_TOKEN", "ghp_supersecret") is True
    out = capsys.readouterr().out
    assert "contributions: OK" in out
    assert "calendar days: 1" in out
    assert "commits: 7" in out
    assert "ghp_supersecret" not in out
    assert "alex-secret-login" not in out


def test_failure_prints_class_name_only(monkeypatch, capsys):
    def boom(gql, today):
        raise PersistentError("detail that must not leak: org/repo")

    monkeypatch.setattr(check_token, "make_transport", lambda token: None)
    monkeypatch.setattr(check_token, "fetch_contributions", boom)
    assert check_token.check("WORK_GH_TOKEN", "ghp_supersecret") is False
    out = capsys.readouterr().out
    assert "contributions: FAIL (PersistentError)" in out
    assert "org/repo" not in out
    assert "ghp_supersecret" not in out


def test_unset_token_reported(capsys):
    assert check_token.check("WORK_GH_TOKEN", None) is False
    assert "WORK_GH_TOKEN: NOT SET" in capsys.readouterr().out


def _patch_ok(monkeypatch, stars, languages):
    account = AccountData("alex-secret-login", {date(2026, 1, 1): 3}, 7, 2, 1)
    monkeypatch.setattr(check_token, "make_transport", lambda token: None)
    monkeypatch.setattr(check_token, "fetch_contributions", lambda gql, today: account)
    monkeypatch.setattr(check_token, "fetch_stars", stars)
    monkeypatch.setattr(check_token, "fetch_languages", languages)


def test_reports_stars_and_languages_counts_only(monkeypatch, capsys):
    _patch_ok(monkeypatch, lambda gql: 42, lambda gql: {"Python": 10, "Go": 5})
    assert check_token.check("WORK_GH_TOKEN", "ghp_supersecret") is True
    out = capsys.readouterr().out
    assert "stars: OK (42)" in out
    assert "languages: OK (2)" in out
    assert "Python" not in out
    assert "ghp_supersecret" not in out


def test_languages_failure_is_reported_but_does_not_fail_check(monkeypatch, capsys):
    def boom(gql):
        raise PersistentError("detail that must not leak: org/repo")

    _patch_ok(monkeypatch, lambda gql: 1, boom)
    assert check_token.check("WORK_GH_TOKEN", "ghp_supersecret") is True
    out = capsys.readouterr().out
    assert "languages: FAIL (PersistentError)" in out
    assert "stars: OK (1)" in out
    assert "org/repo" not in out
