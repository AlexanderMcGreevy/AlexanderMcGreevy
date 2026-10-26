"""SVG rendering for the combined stats board. Pure string building, no I/O.

The output is embedded in a GitHub README through an <img>, so it uses only
inline CSS animation, local filters and system fonts: no script, no external
fonts or images, no links. Every piece of text goes through `escape`.

The drawing helpers (KPI boxes, LED bars, dot grid, labels) take explicit
coordinates so the wide and narrow layouts can share them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable, Sequence
from xml.sax.saxutils import escape

from .models import BoardStats, Split

VISITORS_ID = "visitors"

HEADER = "ALEX McGREEVY // COMBINED"
FOOTER = "WORK ACTIVITY: PRIVATE REPOS, COUNTS ONLY"
PROFILE = "github.com/AlexanderMcGreevy"
PERSONAL_ONLY = "PERSONAL ONLY"
FONT = "'Courier New', Menlo, monospace"
CHAR_W = 0.6  # advance width of one monospace glyph, in em

# --- palette -----------------------------------------------------------------
BG = "#06070b"
FRAME = "#262626"
PANEL = "#0b0e16"
RULE = "#1d2230"
TEXT = "#e8f1ff"
MUTED = "#7d8aa5"
GREEN = "#4dff91"  # personal
BLUE = "#5db6ff"  # work
PINK = "#ff5d8f"
YELLOW = "#ffd24d"
PURPLE = "#c084fc"
CYAN = "#5dd6ff"
ORANGE = "#fb923c"
LED_OFF = "#15181f"
DIM_DIGIT = "#14301f"
DOT_RAMP = ("#12161c", "#1e7a4a", "#37c46b", "#ffd24d", "#ff5d8f")
LANG_COLORS = ("#ff5d4d", "#f9a03c", "#4d8dff", "#c58a3a", "#5dd6ff")

_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_LANG_ALIASES = {"Jupyter Notebook": "Jupyter", "Objective-C++": "Obj-C++",
                 "Visual Basic .NET": "VB.NET", "Vim Script": "VimScript"}

# --- shared sizes (from the mockups) -----------------------------------------
FRAME_W = 6
VALUE_SIZE, LABEL_SIZE, SUB_SIZE = 30, 9, 9
KPI_PAD_X, KPI_MIN_INNER, KPI_H, KPI_GAP = 14, 120, 78, 14
SECTION_SIZE = 10
LANG_SIZE, LANG_ROW, LANG_NAME_W = 11, 16, 84
LED_W, LED_H, LED_GAP = 7, 11, 2
MONTH_SIZE, DOW_SIZE, LEGEND_SIZE = 9, 8, 10

# --- wide layout -------------------------------------------------------------
WIDE_WIDTH = 760
WIDE_PAD_X, WIDE_PAD_Y = 28, 26
WIDE_LEFT = FRAME_W + WIDE_PAD_X  # 34
WIDE_RIGHT = WIDE_WIDTH - WIDE_LEFT  # 726
WIDE_LEDS = 40
WIDE_DOW_W = 30  # weekday label column, left of the grid
WIDE_PITCH, WIDE_DOT_R = 12.5, 4.6

Seg = tuple[str, "str | None"]  # (text, fill); None inherits the element fill


def fmt(n: int) -> str:
    """Thousands separators: 12345 -> '12,345'."""
    return f"{n:,}"


# --- low-level SVG helpers ---------------------------------------------------

def _num(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") or "0"


def _attrs(attrs: dict[str, object]) -> str:
    out = []
    for key, val in attrs.items():
        if val is None or val is False:
            continue
        name = key.rstrip("_").replace("_", "-")
        if isinstance(val, float):
            val = _num(val)
        out.append(f' {name}="{escape(str(val), {chr(34): "&quot;"})}"')
    return "".join(out)


def text_width(s: str, size: float, spacing: float = 0.0) -> float:
    """Estimated rendered width: monospace advance plus letter-spacing (em)."""
    units = sum(2 if ord(c) >= 0x1F000 else 1 for c in s)
    return units * size * (CHAR_W + spacing)


def text(x: float, y: float, content: str | Sequence[Seg], *, size: float,
         fill: str = TEXT, spacing: float = 0.0, max_width: float | None = None,
         **attrs: object) -> str:
    """A <text> element. `content` is a string or (text, fill) segments.

    `spacing` is letter-spacing in em. If the estimated width exceeds
    `max_width` the text is squeezed with textLength so it can never spill.
    """
    segs: Sequence[Seg] = [(content, None)] if isinstance(content, str) else content
    plain = "".join(s for s, _ in segs)
    if max_width is not None and text_width(plain, size, spacing) > max_width:
        attrs["textLength"] = float(max_width)
        attrs["lengthAdjust"] = "spacingAndGlyphs"
    body = "".join(
        escape(s) if color is None else f'<tspan fill="{color}">{escape(s)}</tspan>'
        for s, color in segs
    )
    return (f"<text{_attrs({'x': float(x), 'y': float(y), 'font_size': size, 'fill': fill})}"
            f"{_attrs({'letter_spacing': float(size * spacing)} if spacing else {})}"
            f"{_attrs(attrs)}>{body}</text>")


def section_label(x: float, y: float, label: str) -> str:
    return text(x, y, label, size=SECTION_SIZE, fill=MUTED, spacing=0.22, class_="sec")


def rule(x1: float, x2: float, y: float) -> str:
    return (f'<line x1="{_num(x1)}" y1="{_num(y)}" x2="{_num(x2)}" y2="{_num(y)}" '
            f'stroke="{RULE}" stroke-width="1"/>')


def defs() -> str:
    """Glow filters and the animation stylesheet (CSS keyframes only)."""
    style = (
        "text{font-family:" + FONT + "}"
        "@keyframes pl{50%{opacity:.35}}"
        ".live{animation:pl 1.6s ease-in-out infinite}"
        ".pulse{animation:pl 1.4s ease-in-out infinite}"
        "@media (prefers-reduced-motion:reduce){.live,.pulse{animation:none}}"
    )
    glow = (
        '<filter id="{id}" x="-50%" y="-50%" width="200%" height="200%">'
        '<feGaussianBlur in="SourceGraphic" stdDeviation="{sd}" result="b"/>'
        '<feComponentTransfer in="b" result="g"><feFuncA type="linear" slope="{a}"/>'
        "</feComponentTransfer>"
        '<feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
    )
    return (
        f"<style>{style}</style><defs>"
        + glow.format(id="glow", sd=4, a=0.55)
        + glow.format(id="glow-sm", sd=2, a=0.8)
        + '<filter id="soft" x="-20%" y="-20%" width="140%" height="140%">'
          '<feGaussianBlur stdDeviation="5"/></filter>'
        + "</defs>"
    )


def frame(width: float, height: float) -> str:
    """The dark board panel with its 6px bezel (outer radius 12)."""
    half = FRAME_W / 2
    return (f'<rect x="{_num(half)}" y="{_num(half)}" width="{_num(width - FRAME_W)}" '
            f'height="{_num(height - FRAME_W)}" rx="9" fill="{BG}" stroke="{FRAME}" '
            f'stroke-width="{FRAME_W}"/>')


def header(left: float, right: float, baseline: float, work_available: bool) -> str:
    status = "UPDATED DAILY · " + ("2 ACCOUNTS" if work_available else PERSONAL_ONLY)
    size, spacing = 12, 0.14
    start = right - text_width(status, size, spacing)
    return (
        text(left, baseline, HEADER, size=15, spacing=0.2, font_weight=700)
        + f'<circle class="live" cx="{_num(start - 10)}" cy="{_num(baseline - 4)}" r="4" '
          f'fill="{GREEN}" filter="url(#glow-sm)"/>'
        + text(start, baseline, status, size=size, spacing=spacing)
    )


def footer(left: float, right: float, baseline: float, size: float = 10,
           show_profile: bool = True) -> str:
    out = text(left, baseline, FOOTER, size=size, fill=MUTED, spacing=0.08)
    if show_profile:
        out += text(right, baseline, PROFILE, size=size, fill=MUTED, spacing=0.08,
                    text_anchor="end")
    return out


# --- KPI boxes ---------------------------------------------------------------

@dataclass(frozen=True)
class Kpi:
    value: tuple[Seg, ...]
    label: str
    sub: tuple[Seg, ...] = ()
    color: str = TEXT
    pulse: bool = False
    led: bool = False  # the glowing VISITORS readout style
    gid: str | None = None

    @property
    def value_spacing(self) -> float:
        return 0.14 if self.led else 0.06

    def inner_width(self) -> float:
        return max(
            text_width("".join(s for s, _ in self.value), VALUE_SIZE, self.value_spacing),
            text_width(self.label, LABEL_SIZE, 0.14),
            text_width("".join(s for s, _ in self.sub), SUB_SIZE, 0.06),
        )

    def natural_width(self) -> float:
        return max(KPI_MIN_INNER, self.inner_width()) + 2 * KPI_PAD_X


def layout_row(kpis: Sequence[Kpi], x: float, width: float,
               gap: float = KPI_GAP) -> list[tuple[Kpi, float, float]]:
    """Place boxes left to right at their natural widths; shrink to fit if needed."""
    widths = [k.natural_width() for k in kpis]
    room = width - gap * (len(kpis) - 1)
    if sum(widths) > room:
        scale = room / sum(widths)
        widths = [w * scale for w in widths]
    placed, cursor = [], x
    for k, w in zip(kpis, widths):
        placed.append((k, cursor, w))
        cursor += w + gap
    return placed


def draw_kpi(k: Kpi, x: float, y: float, w: float, h: float = KPI_H) -> str:
    inner = w - 2 * KPI_PAD_X
    stroke = (f'fill="{PANEL}" stroke="{GREEN}" stroke-opacity="0.33"' if k.led
              else f'fill="{PANEL}" stroke="{RULE}"')
    parts = [f'<rect x="0.5" y="0.5" width="{_num(w - 1)}" height="{_num(h - 1)}" rx="6" '
             f'{stroke}/>']
    if k.led:  # soft inner glow, clipped to the box
        clip = f"{k.gid or 'led'}-clip"
        parts.append(
            f'<clipPath id="{clip}"><rect width="{_num(w)}" height="{_num(h)}" rx="6"/></clipPath>'
            f'<rect width="{_num(w)}" height="{_num(h)}" rx="6" fill="none" stroke="{GREEN}" '
            f'stroke-opacity="0.22" stroke-width="10" filter="url(#soft)" clip-path="url(#{clip})"/>'
        )
    parts.append(text(KPI_PAD_X, 35, k.value, size=VALUE_SIZE, fill=k.color,
                      spacing=k.value_spacing, max_width=inner, font_weight=700,
                      filter="url(#glow)", class_="v pulse" if k.pulse else "v"))
    parts.append(text(KPI_PAD_X, 52, k.label, size=LABEL_SIZE, fill=MUTED, spacing=0.14,
                      max_width=inner, class_="l"))
    if k.sub:
        parts.append(text(KPI_PAD_X, 65, k.sub, size=SUB_SIZE, spacing=0.06,
                          max_width=inner, class_="s"))
    return (f'<g class="kpi"{_attrs({"id": k.gid})} '
            f'transform="translate({_num(x)},{_num(y)})">{"".join(parts)}</g>')


def draw_row(kpis: Sequence[Kpi], x: float, y: float, width: float) -> str:
    return "".join(draw_kpi(k, bx, y, bw) for k, bx, bw in layout_row(kpis, x, width))


def _month_year(d: date) -> str:
    return f"{_MONTHS[d.month - 1]} {d.year}"


def _month_day(d: date) -> str:
    return f"{_MONTHS[d.month - 1]} {d.day}"


def _active_today(weeks: Sequence[Sequence[int | None]]) -> bool:
    cells = [c for col in weeks for c in col if c is not None]
    return bool(cells) and cells[-1] > 0


def _visitors_value(n: int, digits: int = 6) -> tuple[Seg, ...]:
    shown = str(n)
    pad = "0" * max(0, digits - len(shown))
    return ((pad, DIM_DIGIT), (shown, None)) if pad else ((shown, None),)


def year_kpis(s: BoardStats) -> list[Kpi]:
    """THIS YEAR row: contributions, day streak, best streak, visitors (optional)."""
    if s.work_available and s.year_work is not None:
        split: tuple[Seg, ...] = ((f"{fmt(s.year_personal)} PERSONAL", GREEN), (" · ", None),
                                  (f"{fmt(s.year_work)} WORK", BLUE))
    else:
        split = ((PERSONAL_ONLY, GREEN),)
    if s.current_streak == 0:
        streak_note = "NO ACTIVE RUN"
    elif _active_today(s.weeks):
        streak_note = "🔥 ACTIVE TODAY"
    else:
        streak_note = "🔥 THROUGH YESTERDAY"
    best_label = "12-MONTH BEST STREAK" if s.best_streak_window_only else "BEST STREAK"
    best_note = _month_year(s.best_streak_end) if s.best_streak_end else "NONE YET"
    kpis = [
        Kpi(((fmt(s.year_total), None),), "CONTRIBUTIONS", split, GREEN),
        Kpi(((f"{s.current_streak:03d}", None),), "DAY STREAK", ((streak_note, None),),
            PINK, pulse=True),
        Kpi(((f"{s.best_streak:03d}", None),), best_label, ((best_note, None),), BLUE),
    ]
    if s.visitors is not None:
        as_of = _month_day(s.visitors_as_of) if s.visitors_as_of else "N/A"
        kpis.append(Kpi(_visitors_value(s.visitors), "VISITORS",
                        ((f"▲ AS OF {as_of}", GREEN),), GREEN, led=True, gid=VISITORS_ID))
    return kpis


def _split_note(split: Split, work_ok: bool) -> tuple[Seg, ...]:
    if not work_ok or split.work is None:
        return ((PERSONAL_ONLY, GREEN),)
    return ((f"{fmt(split.personal)} P", GREEN), (" · ", None), (f"{fmt(split.work)} W", BLUE))


def all_time_kpis(s: BoardStats) -> list[Kpi]:
    """ALL TIME row: commits, pull requests, code reviews, stars."""
    ok = s.all_time_work_available
    a = s.all_time
    stars = fmt(s.stars) if s.stars is not None else "--"
    return [
        Kpi(((fmt(a.commits.total), None),), "COMMITS", _split_note(a.commits, ok), YELLOW),
        Kpi(((fmt(a.pull_requests.total), None),), "PULL REQUESTS",
            _split_note(a.pull_requests, ok), PURPLE),
        Kpi(((fmt(a.reviews.total), None),), "CODE REVIEWS", _split_note(a.reviews, ok), CYAN),
        Kpi(((stars, None),), "STARS EARNED", (("PERSONAL", None),), ORANGE),
    ]


def section_titles(s: BoardStats) -> dict[str, str]:
    personal = "" if s.work_available else f" · {PERSONAL_ONLY}"
    all_time = "" if s.all_time_work_available else f" · {PERSONAL_ONLY}"
    langs_personal = s.languages_scope == "personal" or not s.work_available
    return {
        "year": f"// THIS YEAR{personal}",
        "all_time": f"// ALL TIME{all_time}",
        "languages": "// LANGUAGES · PERSONAL REPOS" if langs_personal else "// LANGUAGES",
        "calendar": f"// LAST 12 MONTHS{personal}",
    }


# --- LED language bars -------------------------------------------------------

def lit_leds(pct: int, leds: int) -> int:
    """LEDs lit for a percent, rounded half up; any listed language shows one."""
    return max(1, min(leds, (pct * leds * 2 + 100) // 200))


def language_name(name: str, max_chars: int) -> str:
    shown = _LANG_ALIASES.get(name, name).upper()
    return shown if len(shown) <= max_chars else shown[: max_chars - 1] + "."


def led_bar(x: float, y: float, pct: int, color: str, leds: int) -> str:
    lit = lit_leds(pct, leds)
    on = "".join(f'<rect class="led on" x="{_num(x + i * (LED_W + LED_GAP))}" y="{_num(y)}" '
                 f'width="{LED_W}" height="{LED_H}" rx="2"/>' for i in range(lit))
    off = "".join(f'<rect class="led" x="{_num(x + i * (LED_W + LED_GAP))}" y="{_num(y)}" '
                  f'width="{LED_W}" height="{LED_H}" rx="2"/>' for i in range(lit, leds))
    return (f'<g fill="{color}" filter="url(#glow-sm)">{on}</g>'
            + (f'<g fill="{LED_OFF}">{off}</g>' if off else ""))


def led_bar_width(leds: int) -> float:
    return leds * (LED_W + LED_GAP) - LED_GAP


def language_rows(langs: Sequence[tuple[str, int]], x: float, top: float,
                  leds: int, name_w: float = LANG_NAME_W) -> tuple[str, float]:
    """Rows of NAME [LEDs] NN%. Returns (svg, height used)."""
    if not langs:
        return text(x, top + 9, "NO LANGUAGE DATA YET", size=LANG_SIZE, fill=MUTED,
                    spacing=0.06), LANG_SIZE
    max_chars = int(name_w // text_width("M", LANG_SIZE, 0.06))
    bar_x = x + name_w + 10
    pct_x = bar_x + led_bar_width(leds) + 10
    out = []
    for i, (name, pct) in enumerate(langs):
        y = top + i * LANG_ROW
        color = LANG_COLORS[i % len(LANG_COLORS)]
        out.append(text(x, y + 9, language_name(name, max_chars), size=LANG_SIZE,
                        spacing=0.06))
        out.append(led_bar(bar_x, y, pct, color, leds))
        out.append(text(pct_x, y + 9, f"{pct}%" if pct > 0 else "<1%", size=LANG_SIZE,
                        spacing=0.06))
    return "".join(out), len(langs) * LANG_ROW - (LANG_ROW - LED_H)


# --- dot grid ----------------------------------------------------------------

def recent_cells(weeks: Sequence[Sequence[int | None]], days: int = 7) -> set[tuple[int, int]]:
    """(week, day) of active days among the most recent `days` days."""
    cells = [(w, d) for w, col in enumerate(weeks) for d, v in enumerate(col) if v is not None]
    return {(w, d) for w, d in cells[-days:] if (weeks[w][d] or 0) > 0}


def dot_grid(weeks: Sequence[Sequence[int | None]], x: float, y: float, pitch: float,
             r: float, first_col: int = 0,
             pulse: Iterable[tuple[int, int]] = ()) -> str:
    """One round dot per day, Sunday-first columns; (x, y) is the top-left dot's
    bounding-box corner. `first_col` is the absolute index of weeks[0], used to
    match `pulse` cells when drawing part of the grid."""
    pulsing = set(pulse)
    out = []
    for w, col in enumerate(weeks):
        cx = x + r + w * pitch
        for d, level in enumerate(col):
            if level is None:
                continue
            cy = y + r + d * pitch
            cls = "d pulse" if (first_col + w, d) in pulsing else "d"
            glow = ' filter="url(#glow-sm)"' if level >= 3 else ""
            out.append(f'<circle class="{cls}" cx="{_num(cx)}" cy="{_num(cy)}" r="{_num(r)}" '
                       f'fill="{DOT_RAMP[level]}"{glow}/>')
    return "".join(out)


def month_positions(labels: Sequence[tuple[int, str]], col_x: Callable[[int], float],
                    right: float, size: float = MONTH_SIZE, spacing: float = 0.08,
                    min_gap: float = 4) -> list[tuple[float, str]]:
    """x positions for month labels. A label that would overlap the one before it
    (including a repeated month at the far end) is dropped; one that would run
    past `right` is pulled back inside first."""
    placed: list[tuple[float, str]] = []
    end = float("-inf")
    for col, name in sorted(labels):
        w = text_width(name, size, spacing)
        x = min(col_x(col), right - w)
        if x < end + min_gap:
            continue
        placed.append((x, name))
        end = x + w
    return placed


def month_labels(labels: Sequence[tuple[int, str]], col_x: Callable[[int], float],
                 right: float, baseline: float) -> str:
    return "".join(text(x, baseline, name, size=MONTH_SIZE, fill=MUTED, spacing=0.08,
                        class_="m")
                   for x, name in month_positions(labels, col_x, right))


def weekday_labels(x: float, y: float, pitch: float, r: float) -> str:
    return "".join(text(x, y + r + d * pitch + DOW_SIZE * 0.35, name, size=DOW_SIZE,
                        fill=MUTED)
                   for d, name in ((1, "MON"), (3, "WED"), (5, "FRI")))


def legend(x: float, baseline: float) -> str:
    """LESS ● ● ● ● ● MORE"""
    out = [text(x, baseline, "LESS", size=LEGEND_SIZE, fill=MUTED, spacing=0.08)]
    cx = x + text_width("LESS", LEGEND_SIZE, 0.08) + 5 + 5.5
    cy = baseline - 3.5
    for color in DOT_RAMP:
        out.append(f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="5.5" fill="{color}"/>')
        cx += 16
    out.append(text(cx - 5.5, baseline, "MORE", size=LEGEND_SIZE, fill=MUTED, spacing=0.08))
    return "".join(out)


# --- document ----------------------------------------------------------------

def description(s: BoardStats) -> str:
    if s.work_available and s.year_work is not None:
        year = (f"{fmt(s.year_total)} contributions in the last 12 months "
                f"({fmt(s.year_personal)} personal, {fmt(s.year_work)} work)")
    else:
        year = f"{fmt(s.year_total)} contributions in the last 12 months (personal account only)"
    return (f"{year}; current streak {s.current_streak} days; best streak {s.best_streak} days; "
            f"{fmt(s.all_time.commits.total)} commits, {fmt(s.all_time.pull_requests.total)} "
            f"pull requests and {fmt(s.all_time.reviews.total)} code reviews all time.")


def document(width: float, height: float, body: str, s: BoardStats) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_num(width)}" height="{_num(height)}" '
        f'viewBox="0 0 {_num(width)} {_num(height)}" role="img" '
        f'aria-labelledby="title desc" font-family="{escape(FONT, {chr(34): "&quot;"})}">'
        f'<title id="title">{escape(HEADER)}</title>'
        f'<desc id="desc">{escape(description(s))}</desc>'
        f"{defs()}{frame(width, height)}{body}</svg>\n"
    )


def render_wide(stats: BoardStats) -> str:
    """The full board at 760 wide, following the visitors-readout mockup."""
    left, right = WIDE_LEFT, WIDE_RIGHT
    width = right - left
    titles = section_titles(stats)
    parts: list[str] = []

    y = FRAME_W + WIDE_PAD_Y  # top of content
    parts.append(header(left, right, y + 13, stats.work_available))
    y += 27
    parts.append(rule(left, right, y))
    y += 27

    def section(gid: str, title: str, content: Callable[[float], tuple[str, float]],
                after: float) -> None:
        nonlocal y
        body, used = content(y + 12)
        parts.append(f'<g id="{gid}">{section_label(left, y, title)}{body}</g>')
        y += 12 + used + after

    section("this-year", titles["year"],
            lambda top: (draw_row(year_kpis(stats), left, top, width), KPI_H), 29)
    section("all-time", titles["all_time"],
            lambda top: (draw_row(all_time_kpis(stats), left, top, width), KPI_H), 29)
    section("languages", titles["languages"],
            lambda top: language_rows(stats.languages, left, top, WIDE_LEDS), 31)

    def calendar(top: float) -> tuple[str, float]:
        grid_x = left + WIDE_DOW_W
        grid_y = top + 14

        def col_x(col: int) -> float:
            return grid_x + col * WIDE_PITCH

        grid_h = 6 * WIDE_PITCH + 2 * WIDE_DOT_R
        body = (month_labels(stats.month_labels, col_x, right, top + 8)
                + weekday_labels(left, grid_y, WIDE_PITCH, WIDE_DOT_R)
                + dot_grid(stats.weeks, grid_x, grid_y, WIDE_PITCH, WIDE_DOT_R,
                           pulse=recent_cells(stats.weeks))
                + legend(left, grid_y + grid_h + 12 + 9))
        return body, 14 + grid_h + 12 + 11

    section("calendar", titles["calendar"], calendar, 16)

    parts.append(rule(left, right, y))
    y += 10 + 9
    parts.append(footer(left, right, y))
    height = y + 3 + WIDE_PAD_Y + FRAME_W
    return document(WIDE_WIDTH, height, "".join(parts), stats)
