# Combined Stats Board — Design

## Intent

Alexander has two GitHub accounts by accident: a personal one
(`AlexanderMcGreevy`, public student/hackathon work) and a work one
(`AlexanderMcGreevy1`, SWE at The Waterside Group, all private repos).
Visitors and recruiters who open his profile README see only the personal
account's stats, which understates what he does. The work account is described
as his *more active* one.

Build one image for the profile README that merges both accounts so a visitor
gets an accurate read of his activity and abilities, and looks distinctive
while doing it.

## What gets built

A single animated SVG, the "Combined Stats Board", regenerated daily by a
GitHub Action in this repo (`AlexanderMcGreevy/AlexanderMcGreevy`) and embedded
in `README.md`. It replaces the three third-party stat cards currently in the
"GitHub Stats" section.

Visual style: **RGB Scoreboard** — black LED-panel look, glowing full-color dots,
monospace type. The reference mockups are the source of truth for layout, color
and spacing; the numbers in them are **made-up sample data**:

- `assets/mockup-scoreboard-board.html` — the full board, plus the degraded
  "no work token" variant at the bottom.
- `assets/mockup-visitors-readout.html` — the same board with the LED
  "VISITORS" box added (option 2 in that file; this is the chosen one). Option 1
  in that file (separate badge under the board) is *not* what was chosen as the
  counter's only form; see "Visitors counter" below.

Open both in a browser to see them.

### Contents, top to bottom

1. **Header:** name, "UPDATED DAILY · 2 ACCOUNTS", slowly blinking live light.
2. **This year (last 12 months):** total contributions with the
   personal / work split; current streak; best streak (**all-time**, not limited
   to the 12-month window, labeled with the month and year it ended);
   **visitors** LED box (see below).
3. **All time:** commits, pull requests, code reviews, each shown as a total
   with a personal `P` / work `W` breakdown; stars earned (personal only).
4. **Languages:** colored LED bars, top five, with percentages.
5. **Daily dots:** the last 12 months, one round dot per day, both accounts
   combined, five-step color ramp (dark → green → yellow → pink), month and
   weekday labels, legend. The most recent active days pulse softly.
6. **Footer:** "WORK ACTIVITY: PRIVATE REPOS, COUNTS ONLY" and the profile URL.

Color coding used for the split: **green = personal, blue = work**.

### Visitors counter

The README already shows a profile-views badge from `komarev.com`
(`https://komarev.com/ghpvc/?username=alexandermcgreevy`, currently ~658).
Decisions:

- **Keep that badge in the README, visible, unchanged**, directly under the
  board. It is what actually counts visits (the count only goes up when that
  image is loaded from the README).
- **Also show the count on the board** as an LED "VISITORS" box, with an
  "as of <date>" note. The daily job reads the current count and paints it.
  It can be up to a day behind the live badge; that is accepted.
- The job's own read of the counter adds one view per run; accepted.
- If the count can't be read or parsed on a given run, keep the last known
  value (or omit the box) rather than failing the whole board.

### Data

- **Two accounts, each queried with its own read-only token** stored as
  repository secrets. Alexander has agreed to provide a read-only token for the
  work account.
- **Daily dots and this-year total:** merge the two accounts' daily
  contribution calendars by date. Work private activity appears as counts only.
- **Streaks:** computed on the merged calendar; a day counts if either
  account has activity.
- **All-time commits / PRs / reviews:** summed across every year since each
  account's creation, per account, then added for the total.
- **Stars:** personal account only.
- **Languages:** the builder decides the exact method. Intent: reflect what he
  actually writes, including private work repos, as proportions only. A
  read-only token may not be allowed to read private-repo language data; if it
  can't, show languages from the personal account (public repos) and label the
  panel accordingly. Do not ask for a broader token to get around this. Noise
  such as notebook files is for the builder to handle; see "Left to the
  builder".

## When data is missing or fails

- **Transient failure** (API error, rate limit, timeout): keep the last good
  board untouched, fail the job visibly, and retry on the next run. Never
  replace a good combined board with a degraded one because of a one-off outage.
- **Persistent loss of work data** (token expired, revoked or blocked by the
  org, or the work calendar comes back empty): publish the board with the full
  layout, every affected figure relabeled "PERSONAL ONLY", and make the failure
  visible in the job (and to Alexander) so it gets fixed. Never show
  personal-only numbers as the combined total.
- **Partial failure** (for example the calendar works but all-time counts or
  languages don't): each section degrades on its own, labeled, rather than
  all-or-nothing. The "no work token" mockup variant shows one such state (work
  adds to the daily dots and this-year total only; the all-time row is personal
  only).
- **If the first-gate check on the work token fails outright** (cannot return
  even the calendar): stop and report back to Alexander before building
  further. Shipping a labeled personal-only board is the fallback, not the
  plan.

## Goals

- A recruiter sees one honest, combined picture on first load of the profile.
- The daily boxes are present and prominent (hard requirement).
- It looks distinctive and clearly "made", not a stock stats card.
- It stays current with no manual work after setup.
- Setup is simple: one repo, one scheduled job, two read-only tokens.

## Non-goals

- No hosted service, server, database or web app.
- No live/real-time data inside the image (GitHub cannot load live external
  content inside an embedded image).
- No changes to the rest of `README.md` (about me, tech stack, featured
  projects, links stay exactly as they are).
- Not a tool for other users; this is for Alexander's profile only.

## Anti-goals (a failure even if it technically works)

- **Leaking work details.** The board, the workflow logs (public in a public
  repo), commit messages and any committed data must contain no work repo
  names, org names, commit messages, file names or other identifying detail from
  private repos. Counts and language proportions only. Tokens are never printed.
- **Misleading numbers.** Sample data from the mockups must never ship. If the
  work half of the data is unavailable, the board must say so honestly (use the
  "personal only" variant and label it) rather than silently showing the
  personal numbers as the combined total.
- **A board that looks broken on a phone** or when the viewer's system
  monospace font differs.
- **A noisy repo history** (e.g. a commit on every run when nothing changed).

## Constraints

- Lives in this repo; default branch `main`. The README embeds the image via a
  relative path.
- Output must render when embedded in a GitHub README: static SVG with
  embedded CSS/SMIL animation only; no scripts, no external fonts or images.
  Use a system monospace font stack and tolerate width differences.
- The board is its own dark panel, so it must look right in both GitHub light
  and dark themes.
- Must be readable at roughly phone width (about 390px). A separate narrow
  layout is allowed (for example stacked stat boxes, a taller dot grid, or no
  weekday labels), but the daily dots stay on the board at every width.
- Scheduled once a day plus manual trigger; commits only when the output
  changed. The visitors number and its "as of" date do **not** count as a
  change by themselves; they are refreshed whenever anything else changes.
- The work account is in a company org. That org may restrict tokens (SSO
  authorization, token policies). Treat "does the work token return the
  needed counts" as the first thing to verify before building the rest.
- Reference style details (sizes, colors, labels) come from the mockups.

## Decisions Alexander made

- Merge both accounts into one picture; counts only for private work.
- Style: RGB Scoreboard (dot-matrix family), with a language display above
  the daily dots; "stylistic", not GitHub-clone.
- Include: daily grid, headline totals, streaks, languages, personal/work split,
  and all-time commits, PRs and reviews.
- Replace all three existing third-party cards (stats, streak, top languages).
- Visitors: LED readout on the board **and** keep the visible komarev badge on
  the page.
- Will supply a read-only token for the work account.

## My calls (not yet confirmed by Alexander)

- Tech approach: scheduled GitHub Action generating an SVG, committed to the
  repo, embedded in the README.
- Animation: gentle pulse on streak, newest dots and live light.
- Work token feeds the languages data (private repos) only if a read-only token
  allows it; otherwise languages are personal and labeled — a guess.
- Stars shown as personal only.
- Failure behavior as set out in "When data is missing or fails".
- Best streak is all-time; the narrow-screen layout may differ; the visitors
  number does not trigger a commit on its own (see Constraints).
- The spec and mockups live in `docs/superpowers/specs/` in this repo.

## Left to the builder

- Language and runtime for the generator and the exact workflow layout.
- GraphQL queries, pagination, rate-limit handling, retries.
- Exact method and noise handling for language proportions.
- How day boundaries/time zones are handled for streaks and the calendar
  (current streak should not break just because today has no activity yet).
- Intensity thresholds for the five-step dot colors.
- Narrow-screen reflow details, file names and paths, bot commit message and
  identity.
- Where the "last known visitors count" is kept between runs (counts only,
  nothing identifying).
- Which token type to ask Alexander for, once the first-gate check shows what
  is needed (keep it read-only).
- Tests, including a way to render the SVG locally with fake data for review.
