import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
WORKFLOW = ROOT / ".github" / "workflows" / "scoreboard.yml"
BADGE = "komarev.com/ghpvc/?username=alexandermcgreevy"


def test_stat_cards_replaced():
    assert "github-readme-stats.vercel.app" not in README
    assert "streak-stats.demolab.com" not in README


def test_board_embedded_with_narrow_source():
    assert "assets/scoreboard.svg" in README
    assert "assets/scoreboard-narrow.svg" in README
    assert "max-width" in README


def test_komarev_badge_kept_after_board():
    assert BADGE in README
    assert "<picture>" in README and "</picture>" in README
    assert README.index("</picture>") < README.index(BADGE)


def test_other_sections_untouched():
    for heading in ("About Me", "Tech Stack", "Featured Projects", "Let's Connect"):
        assert heading in README
    assert "## 📈 GitHub Stats" in README
    main_readme = subprocess.run(
        ["git", "show", "main:README.md"], cwd=ROOT, check=True,
        capture_output=True, text=True, encoding="utf-8",
    ).stdout
    assert README.count("img.shields.io") == main_readme.count("img.shields.io")


def test_workflow_has_required_pieces():
    text = WORKFLOW.read_text(encoding="utf-8")
    for needle in (
        "cron: '17 6 * * *'",
        "workflow_dispatch",
        "contents: write",
        "continue-on-error: true",
        "if: always()",
        "id: gen",
        "python -m scoreboard",
        "if: always() && steps.gen.outcome == 'failure'",
        "PERSONAL_GH_TOKEN",
        "WORK_GH_TOKEN",
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "chore: update scoreboard",
    ):
        assert needle in text, needle


def test_workflow_does_not_print_account_data():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "state.json" not in text
    assert "cat assets" not in text


def test_commit_step_guards_missing_assets_dir():
    text = WORKFLOW.read_text(encoding="utf-8")
    guard = '[ -d assets ] || { echo "No assets directory; nothing to commit."; exit 0; }'
    assert guard in text
    assert text.index(guard) < text.index("git add assets/")
