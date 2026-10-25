# Combined Stats Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily GitHub Action renders one animated "RGB Scoreboard" SVG that merges Alexander's personal and work accounts, and the profile README embeds it in place of the three third-party stat cards.

**Architecture:** A stdlib-only Python package (`scoreboard/`) fetches each account's data with its own read-only token via the GitHub GraphQL API, reduces it to counts (no repo or org names ever enter a model), computes merged stats, and renders two static SVGs (wide and narrow). `main` applies the failure policy, writes the SVGs only when something other than the visitors box changed, and the workflow commits them.

**Tech Stack:** Python 3.12 (standard library only at runtime), pytest (dev only), GitHub Actions, GitHub GraphQL API.

**Spec:** `docs/superpowers/specs/2026-10-25-combined-stats-board-design.md` (mockups in `docs/superpowers/specs/assets/`; their numbers are sample data).

## Global Constraints

- Lives in repo `AlexanderMcGreevy/AlexanderMcGreevy`, default branch `main`; README embeds images by relative path.
- SVG renders inside a GitHub README `<img>`: embedded CSS/SMIL animation only; no `<script>`, no external fonts, no external images, no `<image>` or external `href`.
- Font stack: `'Courier New', Menlo, monospace`; the board is its own dark panel (`#06070b`) so it works in light and dark themes.
- Colors: green `#4dff91` = personal, blue `#5db6ff` = work. Dot ramp (levels 0-4): `#12161c #1e7a4a #37c46b #ffd24d #ff5d8f`. Language bar colors by rank: `#ff5d4d #f9a03c #4d8dff #c58a3a #5dd6ff`.
- Wide layout viewBox width 760; narrow layout viewBox width 390. Daily dots appear at both widths.
- Work activity appears only as counts and language proportions. No repo names, org names, commit messages or file names in any model, SVG, log line, committed file or commit message. Tokens are never printed.
- Footer text exactly `WORK ACTIVITY: PRIVATE REPOS, COUNTS ONLY`; header exactly `ALEX McGREEVY // COMBINED`.
- Runs once a day plus manual trigger; commits only when the output changed, and the visitors number and its "as of" date do not count as a change.
- Never ship mockup sample data; never present personal-only numbers as the combined total.
- Do not change any README section outside "GitHub Stats". The `komarev.com` views badge stays visible, unchanged, directly under the board.

## Review Focus

1. Today has no activity yet: the current streak counts through yesterday instead of resetting to 0. (Task 2)
2. Work token valid but private contributions hidden, so the work calendar is all zeros: the board is labeled personal-only, not shown as combined. (Task 7)
3. A window with no nonzero days (brand-new quiet year) must not crash the dot-level function or the percent math; empty languages renders an empty panel. (Tasks 2, 3)
4. Large numbers (e.g. 12,345 all-time commits): thousands separators and no text overflowing its box in either layout. (Tasks 5, 6)
5. Visitors badge returns an error page or non-numeric text: keep the last known value, never fail the run. (Task 4)

---

## File Structure

- `scoreboard/errors.py`: `TransientError`, `PersistentError`.
- `scoreboard/models.py`: dataclasses shared by every module.
- `scoreboard/github.py`: GraphQL transport and the three fetchers; returns models only.
- `scoreboard/stats.py`: pure computation (merge, streaks, levels, languages, all-time).
- `scoreboard/visitors.py`: komarev fetch/parse and state file read/write.
- `scoreboard/render.py`: `render_wide`, `render_narrow`, shared drawing helpers.
- `scoreboard/sample.py`: fake `BoardData` for previews and tests.
- `scoreboard/check_token.py`: counts-only token gate check (CLI).
- `scoreboard/__main__.py`: orchestration and failure policy.
- `tests/`: one test file per module plus `test_readme.py`.
- `.github/workflows/scoreboard.yml`, `.gitignore`, `requirements-dev.txt`, `assets/scoreboard.svg`, `assets/scoreboard-narrow.svg`, `assets/state.json`.

---

### Task 1: Models, GitHub transport, contributions fetch, token gate

**Files:**
- Create: `scoreboard/__init__.py`, `scoreboard/errors.py`, `scoreboard/models.py`, `scoreboard/github.py`, `scoreboard/check_token.py`, `tests/test_github.py`, `.gitignore`, `requirements-dev.txt`

**Interfaces:**
- Produces:
  - `errors.TransientError(Exception)`, `errors.PersistentError(Exception)`.
  - `models.AccountData(login: str, calendar: dict[date, int], commits: int, pull_requests: int, reviews: int, history_complete: bool = True, stars: int | None = None, languages: dict[str, int] | None = None)` (frozen dataclass).
  - `github.GraphQL = Callable[[str, dict], dict]`: takes query and variables, returns the response `data` dict, raises the two errors.
  - `github.make_transport(token: str) -> GraphQL`.
  - `github.with_retries(fn: Callable[[], T], attempts: int = 3, sleep: Callable[[float], None] = time.sleep) -> T`: retries only `TransientError`, backoff 1s then 4s.
  - `github.fetch_contributions(gql: GraphQL, today: date) -> AccountData` (stars/languages left `None`).

- [ ] **Step 1: Write failing tests** in `tests/test_github.py` using a fake `gql` that returns canned `viewer` payloads:
  - `test_year_windows_clip_to_account_creation`: account created `2024-06-10`, today `2026-10-25` → queried windows are `2024-06-10..2024-12-31`, `2025-01-01..2025-12-31`, `2026-01-01..2026-10-25`.
  - `test_sums_all_years_and_merges_calendar`: two years of canned days → `commits`, `pull_requests`, `reviews` are sums across years; `calendar` has one entry per date.
  - `test_discards_repo_names`: canned payload includes a `repository.nameWithOwner` field → `repr(account)` contains none of it.
  - `test_older_year_persistent_failure_sets_history_incomplete`: the 2024 window raises `PersistentError`, recent windows succeed → result has `history_complete is False` and still contains 2025-2026 data.
  - `test_recent_year_persistent_failure_raises`: the 2026 window raises `PersistentError` → `fetch_contributions` raises `PersistentError`.
  - `test_retries_transient_then_succeeds` and `test_retries_give_up_after_three` (fake sleep records `[1, 4]`).
  - `test_classifies_errors`: HTTP 401/403 and GraphQL error types `FORBIDDEN`, `INSUFFICIENT_SCOPES` → `PersistentError`; HTTP 429/5xx, network error, GraphQL `RATE_LIMITED` → `TransientError` (test via a pure `classify(status: int | None, errors: list[dict]) -> type[Exception] | None`).

- [ ] **Step 2: Run** `python -m pytest tests/test_github.py -v`. Expected: FAIL (modules missing).

- [ ] **Step 3: Implement.** One GraphQL query on `viewer` (so private activity is included for the token's own account): `login`, `createdAt`, and `contributionsCollection(from:, to:)` with `contributionCalendar { weeks { contributionDays { date contributionCount } } }`, `totalCommitContributions`, `totalPullRequestContributions`, `totalPullRequestReviewContributions`. Fetch the current and previous calendar year first (these must succeed); older years second, with persistent failures only flipping `history_complete`. `make_transport` uses `urllib.request` against `https://api.github.com/graphql` with a 30 s timeout. Add `.gitignore` (`__pycache__/`, `.pytest_cache/`, `.venv/`, `build/`) and `requirements-dev.txt` (`pytest`).

- [ ] **Step 4: Run** the tests. Expected: PASS.

- [ ] **Step 5: Implement `scoreboard/check_token.py`** (`python -m scoreboard.check_token`, reads `PERSONAL_GH_TOKEN` and `WORK_GH_TOKEN` from the environment). For each account prints only: which token is set, `contributions: OK|FAIL (<error class>)`, number of calendar days, and the three all-time totals as counts. No repo names, no tokens.

- [ ] **Step 6: Commit.**

```bash
git add scoreboard tests .gitignore requirements-dev.txt
git commit -m "feat: GitHub contributions client and token check"
```

- [ ] **Step 7: GATE (Alexander runs this; stop here until he reports back).** Create a read-only token on each account (start with the narrowest scope that works, likely `read:user` on a classic token, and authorize it for the company org if required; do not widen to `repo`), then run:

```bash
PERSONAL_GH_TOKEN=... WORK_GH_TOKEN=... python -m scoreboard.check_token
```

Expected: both accounts print `contributions: OK` with nonzero work totals. If the work account fails or shows an all-zero calendar, **stop and report to Alexander before continuing** (spec: failed first-gate check). If it passes, continue.

---

### Task 2: Merge, streaks, dot levels, all-time totals

**Files:**
- Create: `scoreboard/stats.py` (first part), `tests/test_stats.py`
- Modify: `scoreboard/models.py` (add `BoardData`, `BoardStats` and friends)

**Interfaces:**
- Consumes: `AccountData` (Task 1).
- Produces in `models.py`:
  - `BoardData(today: date, personal: AccountData, work: AccountData | None, languages_scope: Literal["combined", "personal"], visitors: int | None, visitors_as_of: date | None)`; `work=None` means work data is unavailable.
  - `AllTime(commits: Split, pull_requests: Split, reviews: Split)` where `Split(total: int, personal: int, work: int | None)`; `work=None` renders the personal-only form.
  - `BoardStats(year_total: int, year_personal: int, year_work: int | None, current_streak: int, best_streak: int, best_streak_end: date | None, best_streak_window_only: bool, all_time: AllTime, stars: int | None, languages: list[tuple[str, int]], weeks: list[list[int | None]], month_labels: list[tuple[int, str]], work_available: bool, all_time_work_available: bool, languages_scope: str, visitors: int | None, visitors_as_of: date | None)`.
- Produces in `stats.py`:
  - `merge_calendars(*cals: dict[date, int]) -> dict[date, int]` (sums per date).
  - `current_streak(cal: dict[date, int], today: date) -> int`.
  - `best_streak(cal: dict[date, int]) -> tuple[int, date | None]`.
  - `dot_levels(counts: list[int]) -> list[int]`: 0 for zero days; 1-4 by quartile of the nonzero counts.
  - `last_12_months_grid(cal: dict[date, int], today: date) -> tuple[list[list[int | None]], list[tuple[int, str]]]`: 53 week columns, Sunday-first, days after `today` are `None`; month labels are `(week_index, "NOV")` where the month changes.

- [ ] **Step 1: Write failing tests** in `tests/test_stats.py`:
  - `test_current_streak_counts_through_today`: days Oct 22-25 active, today Oct 25 → 4.
  - `test_current_streak_survives_empty_today`: Oct 22-24 active, Oct 25 zero → 3 (Review Focus 1).
  - `test_current_streak_zero_when_yesterday_also_empty` → 0.
  - `test_best_streak_returns_longest_run_and_end_date`: runs of 3 and 5 → `(5, end_of_second)`.
  - `test_streak_uses_merged_calendar`: personal active Mon, work active Tue → streak 2.
  - `test_dot_levels_quartiles`: `[0,1,2,3,4,5,6,7,8]` → zeros stay 0; 1-2→1, 3-4→2, 5-6→3, 7-8→4.
  - `test_dot_levels_all_zero_and_single_value`: `[0,0,0]` → `[0,0,0]`; `[0,5]` → `[0,4]` (Review Focus 3).
  - `test_grid_shape`: 53 columns, 7 rows each, trailing future days are `None`, first column starts on a Sunday.
  - `test_month_labels_first_column_of_each_month`.

- [ ] **Step 2: Run** `python -m pytest tests/test_stats.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement the five functions** with the signatures above; quartile rule is "rank among sorted nonzero counts, split into four equal-sized buckets, ties go to the lower bucket".

- [ ] **Step 4: Run** the tests. Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add scoreboard tests
git commit -m "feat: merged calendar, streaks and dot levels"
```

---

### Task 3: Stars and languages; `compute_stats`

**Files:**
- Modify: `scoreboard/github.py`, `scoreboard/stats.py`, `scoreboard/check_token.py`
- Test: `tests/test_github.py`, `tests/test_stats.py`

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces:
  - `github.fetch_stars(gql: GraphQL) -> int`: sum of `stargazerCount` over the viewer's owned, public repos (paginated, 100 per page).
  - `github.fetch_languages(gql: GraphQL) -> dict[str, int]`: bytes per language over the viewer's owned, non-fork repos visible to the token; repo names are never kept.
  - `stats.language_shares(personal: dict[str, int] | None, work: dict[str, int] | None, top: int = 5) -> list[tuple[str, int]]`: merges, keeps the top `top`, integer percents of the *total* bytes (so the shown five need not sum to 100).
  - `stats.compute_stats(data: BoardData) -> BoardStats`: year totals from the last 12 months of the merged calendar; all-time `Split`s with `work=None` when `data.work is None` or `not data.work.history_complete`; `best_streak` over the merged full calendar, with `best_streak_window_only=True` when work history is incomplete; `languages` from `language_shares` using `languages_scope`.

- [ ] **Step 1: Write failing tests:**
  - `test_fetch_languages_sums_bytes_and_drops_repo_names`, `test_fetch_stars_paginates` (two pages).
  - `test_language_shares_merge_and_top_five`: six languages → five returned, descending, percents of total.
  - `test_language_shares_empty` → `[]`; one side `None` → other side only (Review Focus 3).
  - `test_compute_stats_combined`: personal 482 + work 611 in the last 12 months → `year_total == 1093`, `year_personal == 482`, `year_work == 611`, `all_time.commits.total == personal + work`.
  - `test_compute_stats_work_none_is_personal_only`: `work=None` → `work_available is False`, `year_work is None`, every `Split.work is None`.
  - `test_compute_stats_incomplete_history`: `all_time_work_available is False`, `best_streak_window_only is True`.

- [ ] **Step 2: Run** the tests. Expected: FAIL.

- [ ] **Step 3: Implement** the four functions. `check_token` additionally prints `languages: OK|FAIL` and `stars: OK|FAIL` per account (counts only) so Alexander can see whether the work token can read private-repo languages.

- [ ] **Step 4: Run** the tests. Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add scoreboard tests
git commit -m "feat: stars, languages and combined stats"
```

---

### Task 4: Visitors counter

**Files:**
- Create: `scoreboard/visitors.py`, `tests/test_visitors.py`

**Interfaces:**
- Produces:
  - `visitors.BADGE_URL = "https://komarev.com/ghpvc/?username=alexandermcgreevy"`.
  - `visitors.parse_count(svg_text: str) -> int | None`: the last numeric text node in the badge SVG (commas allowed), else `None`.
  - `visitors.fetch_count(fetch: Callable[[str], str] = urllib_get) -> int | None`: never raises; returns `None` on any failure.
  - `visitors.load_state(path: Path) -> tuple[int | None, date | None]` and `visitors.save_state(path: Path, count: int, as_of: date) -> None`: JSON `{"visitors": int, "as_of": "YYYY-MM-DD"}`, nothing else.

- [ ] **Step 1: Write failing tests:**
  - `test_parse_count_reads_last_number`: a komarev-style SVG with text nodes "Profile views" and "658" → 658; "1,234" → 1234.
  - `test_parse_count_garbage_returns_none`: HTML error page, empty string, text with no digits (Review Focus 5).
  - `test_fetch_count_swallows_errors`: fetcher raises → `None`.
  - `test_state_roundtrip_and_missing_file`: missing file → `(None, None)`; save then load → same values; file content has exactly the two keys.

- [ ] **Step 2: Run** `python -m pytest tests/test_visitors.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement.** Verify the real badge's markup once (a single `curl` of `BADGE_URL`, which adds one view) and make `parse_count` match it; the test fixture must be a copy of that real response.

- [ ] **Step 4: Run** the tests. Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add scoreboard tests
git commit -m "feat: visitors counter fetch and state"
```

---

### Task 5: Wide SVG renderer, sample data, preview

**Files:**
- Create: `scoreboard/render.py`, `scoreboard/sample.py`, `tests/test_render.py`
- Modify: `scoreboard/__main__.py` (create with only a `--sample <dir>` path for now)

**Interfaces:**
- Consumes: `BoardStats` (Task 2).
- Produces:
  - `render.render_wide(stats: BoardStats) -> str`: complete SVG, viewBox `0 0 760 H`.
  - `render.VISITORS_ID = "visitors"`: the visitors box is a `<g id="visitors">` so Task 7 can exclude it from change detection.
  - `render.fmt(n: int) -> str`: thousands separators (`12345` → `"12,345"`).
  - `sample.sample_board_data() -> BoardData`: deterministic fake data (clearly fake, e.g. login `sample`).
  - CLI: `python -m scoreboard --sample build/` writes `build/preview-wide.svg`, `build/preview-narrow.svg` (narrow added in Task 6) from sample data.

Layout per the mockups: header row, "THIS YEAR" boxes (contributions with `PERSONAL`/`WORK` split in green/blue, day streak with a pulsing value, best streak with month-year, visitors box), "ALL TIME" boxes (commits, pull requests, code reviews with `P`/`W` splits, stars earned), "LANGUAGES" LED bars (40 LEDs each, lit proportional to percent), "LAST 12 MONTHS" dot grid with month and MON/WED/FRI labels, legend, footer. Animations: `live` light blink (1.6 s), streak value pulse and newest-week active dots pulse (1.4 s), via SVG `<style>` keyframes.

- [ ] **Step 1: Write failing tests** in `tests/test_render.py` (parse output with `xml.etree.ElementTree`):
  - `test_wide_is_valid_svg_with_safe_content`: parses; viewBox width 760; no `script`, `image`, `foreignObject` elements; no `href`/`xlink:href` attributes; no `http` strings other than the SVG namespace.
  - `test_wide_contains_headline_numbers`: for stats with `year_total=1093`, `year_personal=482`, `year_work=611` the text contains `1,093`, `482`, `611`, `ALEX McGREEVY // COMBINED`, `WORK ACTIVITY: PRIVATE REPOS, COUNTS ONLY`.
  - `test_wide_dot_count_matches_grid`: number of dot `circle` elements with class `d` equals the number of non-`None` grid cells (≤ 371), and each carries the ramp color for its level.
  - `test_wide_visitors_group`: `<g id="visitors">` exists with `658` and `AS OF`; with `visitors=None` the group is absent.
  - `test_wide_personal_only_labels`: `work_available=False` → text contains `PERSONAL ONLY` and no `WORK` split text in the year row; `all_time_work_available=False` → all-time boxes show personal only with the tag.
  - `test_wide_large_numbers_fit`: with `commits.total=12345` the text shows `12,345` and the rendered text's estimated width (chars × 0.6 × font size) is ≤ the box width.
  - `test_fmt`: `fmt(0)=="0"`, `fmt(12345)=="12,345"`.
  - `test_wide_no_languages_renders_empty_panel`: `languages=[]` renders the section header without raising.

- [ ] **Step 2: Run** `python -m pytest tests/test_render.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `render_wide`, `fmt`, `sample_board_data` and the `--sample` CLI path.** Build the SVG with string templates plus `xml.sax.saxutils.escape` for all text.

- [ ] **Step 4: Run** the tests. Expected: PASS.

- [ ] **Step 5: Review by eye.** Run `python -m scoreboard --sample build/`, open `build/preview-wide.svg` in a browser, and compare against `docs/superpowers/specs/assets/mockup-visitors-readout.html` (option 2). Fix visible differences in layout, colors and labels.

- [ ] **Step 6: Commit.**

```bash
git add scoreboard tests
git commit -m "feat: wide scoreboard renderer and sample preview"
```

---

### Task 6: Narrow SVG renderer

**Files:**
- Modify: `scoreboard/render.py`, `scoreboard/__main__.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Produces: `render.render_narrow(stats: BoardStats) -> str`, viewBox `0 0 390 H`. Same content and animations as wide; KPI boxes two per row; the 12-month dots drawn as two stacked half-year grids (older half first, each ~27 weeks, dot pitch about 12) with month labels; weekday labels dropped; LED language bars shortened to 24 LEDs.

- [ ] **Step 1: Write failing tests** (same safe-content assertions as wide, parametrized over both renderers where shared):
  - `test_narrow_viewbox_and_safe_content`: width 390, same safety checks.
  - `test_narrow_contains_every_dot`: dot count equals the wide renderer's dot count for the same stats (hard requirement: dots at every width).
  - `test_narrow_same_text_content`: every headline number string present in wide is present in narrow (including `PERSONAL ONLY` labels).
  - `test_narrow_large_numbers_fit`: `12,345` fits its box.
  - `test_narrow_nothing_wider_than_viewbox`: every element's x extent ≤ 390 (compute from the layout constants the renderer exposes as `NARROW_WIDTH` and the placed-element list returned by an internal `layout_narrow(stats)` that tests can inspect).

- [ ] **Step 2: Run** the tests. Expected: FAIL for the new tests.

- [ ] **Step 3: Implement `render_narrow`**, sharing drawing helpers with `render_wide`; extend `--sample` to write `preview-narrow.svg`.

- [ ] **Step 4: Run** the tests. Expected: PASS.

- [ ] **Step 5: Review by eye** with the browser pane resized to 390 px wide; text and dots must be legible.

- [ ] **Step 6: Commit.**

```bash
git add scoreboard tests
git commit -m "feat: narrow scoreboard layout"
```

---

### Task 7: Orchestration, failure policy, change detection

**Files:**
- Modify: `scoreboard/__main__.py`
- Create: `scoreboard/pipeline.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `pipeline.strip_volatile(svg: str) -> str`: removes the `<g id="visitors">...</g>` element.
  - `pipeline.run(env: Mapping[str, str], out_dir: Path, today: date, gql_factory: Callable[[str], GraphQL], fetch_visitors: Callable[[], int | None]) -> int`: returns the process exit code. `0` = healthy; `2` = transient failure, nothing written; `3` = board written but degraded (a persistent problem Alexander must fix). Writes `assets/scoreboard.svg`, `assets/scoreboard-narrow.svg`, `assets/state.json` under `out_dir`.
  - `python -m scoreboard` calls `run` with real transport, `os.environ`, `date.today()`.

Policy (from the spec): personal fetch failing in any way → exit 2, write nothing. Work: `TransientError` → exit 2, write nothing; `PersistentError`, missing `WORK_GH_TOKEN`, or all-time work totals of 0 with an all-zero work calendar → `work=None`, render the personal-only board, exit 3. Work languages failing persistently (expected if a read-only token can't read private repos) → `languages_scope="personal"` with the panel labeled; this alone is not a degraded run (exit 0). Work history incomplete → exit 3. If several conditions apply, the result is 2 if any is transient, else 3 if any is degraded, else 0. Visitors: fetched count if present, else the last known value from state, else omitted. Write the SVGs and state only if `strip_volatile` of the new wide or narrow SVG differs from the existing file (or no file exists).

- [ ] **Step 1: Write failing tests** in `tests/test_pipeline.py` with fake `gql_factory` and `tmp_path`:
  - `test_healthy_run_writes_both_svgs_and_state`: exit 0; both SVGs exist; `state.json` has the visitors count.
  - `test_unchanged_data_does_not_rewrite`: second run with different visitors number but same data → file bytes unchanged, `state.json` unchanged.
  - `test_changed_data_rewrites_with_fresh_visitors`: new contribution day → files rewritten and show the new visitors number.
  - `test_personal_transient_failure_writes_nothing`: exit 2, `out_dir` unchanged (a previously written board is still byte-identical).
  - `test_work_transient_failure_keeps_last_good_board`: exit 2, files unchanged.
  - `test_work_persistent_failure_publishes_personal_only`: exit 3; SVG text contains `PERSONAL ONLY`.
  - `test_missing_work_token_publishes_personal_only`: exit 3.
  - `test_empty_work_calendar_is_treated_as_missing` (Review Focus 2): valid work account returning all zeros → exit 3, `PERSONAL ONLY` present, combined total not shown.
  - `test_work_languages_unavailable_falls_back_to_personal_scope`: exit 0, languages labeled personal.
  - `test_visitors_failure_keeps_last_known`: `fetch_visitors` returns `None`, state has 700 → SVG shows 700; no state and `None` → no visitors group.
  - `test_no_private_details_in_outputs_or_logs`: fake work payloads contain repo and org names (`secret-repo`, `secret-org`); after a run, none of the written files nor captured stdout/stderr contain them or any token value.

- [ ] **Step 2: Run** `python -m pytest tests/test_pipeline.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `pipeline.run` and wire `__main__`.** Log only section names with `ok`/`failed` and counts; emit `::warning::` annotations for degraded states (no repo or org names).

- [ ] **Step 4: Run** the full suite `python -m pytest -v`. Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add scoreboard tests
git commit -m "feat: pipeline with failure policy and change detection"
```

---

### Task 8: Workflow, README swap, ship

**Files:**
- Create: `.github/workflows/scoreboard.yml`, `tests/test_readme.py`, `assets/` outputs (generated)
- Modify: `README.md` (the "GitHub Stats" section only)

**Interfaces:**
- Consumes: `python -m scoreboard` exit codes (Task 7). Secrets: `PERSONAL_GH_TOKEN`, `WORK_GH_TOKEN`.

README change: lines 75-79 (the three `![...]` stat-card images) become a `<picture>` block: `<source media="(max-width: 600px)" srcset="assets/scoreboard-narrow.svg">` and `<img src="assets/scoreboard.svg" alt="Combined GitHub stats for Alexander McGreevy across personal and work accounts">`. The heading `## 📈 GitHub Stats`, the `komarev.com` badge line, and every other section stay byte-identical.

- [ ] **Step 1: Write failing tests** in `tests/test_readme.py`:
  - `test_stat_cards_replaced`: README has no `github-readme-stats.vercel.app` and no `streak-stats.demolab.com`.
  - `test_board_embedded_with_narrow_source`: contains `assets/scoreboard.svg`, `assets/scoreboard-narrow.svg`, and `max-width`.
  - `test_komarev_badge_kept_after_board`: the `komarev.com/ghpvc/?username=alexandermcgreevy` line exists and comes after the `<picture>` block.
  - `test_other_sections_untouched`: headings `About Me`, `Tech Stack`, `Featured Projects`, `Let's Connect` still present and the shields.io badge count is unchanged (read the expected count from `git show main:README.md`).

- [ ] **Step 2: Run** `python -m pytest tests/test_readme.py -v`. Expected: FAIL.

- [ ] **Step 3: Edit README.md** as described.

- [ ] **Step 4: Run** `python -m pytest tests/test_readme.py -v`. Expected: PASS.

- [ ] **Step 5: Create `.github/workflows/scoreboard.yml`:** triggers `schedule` (`17 6 * * *`) and `workflow_dispatch`; `permissions: contents: write`; steps: checkout, `actions/setup-python` 3.12, run `python -m scoreboard` as step id `gen` with `continue-on-error: true` and both token secrets in `env`, then a commit step with `if: always()` that commits `assets/` as `github-actions[bot]` only when `git diff --quiet` says there are changes (message `chore: update scoreboard`), then a final step that fails the job when `steps.gen.outcome == 'failure'` so Alexander is notified. Do not echo secrets or print `assets/state.json`.

- [ ] **Step 6: Run the full suite** `python -m pytest -v`. Expected: PASS.

- [ ] **Step 7: Commit and open the PR.**

```bash
git add .github scoreboard tests README.md
git commit -m "feat: scheduled scoreboard workflow and README embed"
```

- [ ] **Step 8: Alexander adds the two secrets** (repo Settings → Secrets and variables → Actions → `PERSONAL_GH_TOKEN`, `WORK_GH_TOKEN`; never in chat), merges the PR to `main`, then runs the workflow once from the Actions tab (`workflow_dispatch`).

- [ ] **Step 9: Verify live.** Expected: the run is green, `assets/scoreboard.svg` and `assets/scoreboard-narrow.svg` were committed, the profile page shows the board above the views badge, and viewed at phone width (or a 390 px browser window) the narrow layout appears and every dot is visible. If the narrow `<picture>` source doesn't switch on GitHub's mobile view, fall back to a single wide board that scales and tell Alexander.
