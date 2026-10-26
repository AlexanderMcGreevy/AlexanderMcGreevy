import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import replace
from datetime import date

import pytest

from scoreboard import render
from scoreboard.models import AllTime, Split
from scoreboard.render import DOT_RAMP, VISITORS_ID, fmt, render_wide
from scoreboard.sample import sample_board_data
from scoreboard.stats import compute_stats

NS = "{http://www.w3.org/2000/svg}"


def base_stats(**overrides):
    stats = compute_stats(sample_board_data())
    return replace(stats, **overrides)


def parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def all_text(el: ET.Element) -> str:
    return " ".join("".join(t.itertext()) for t in el.iter(f"{NS}text"))


def group(root: ET.Element, gid: str) -> ET.Element | None:
    for g in root.iter(f"{NS}g"):
        if g.get("id") == gid:
            return g
    return None


def classes(el: ET.Element) -> list[str]:
    return (el.get("class") or "").split()


# Both layouts, looked up lazily so a missing renderer fails its own tests only.
BOARDS = {"wide": ("render_wide", 760, 40), "narrow": ("render_narrow", 390, 24)}


@pytest.fixture(params=list(BOARDS))
def board(request):
    """(render function, viewBox width, LEDs per language bar)."""
    name, width, leds = BOARDS[request.param]
    return getattr(render, name), width, leds


def narrow(stats) -> str:
    return render.render_narrow(stats)


def text_contents(root: ET.Element) -> list[str]:
    return ["".join(t.itertext()) for t in root.iter(f"{NS}text")]


def big_stats():
    return base_stats(
        year_total=123456, year_personal=61728, year_work=61728,
        current_streak=1234, best_streak=1234, best_streak_window_only=True,
        visitors=12345678, visitors_as_of=date(2026, 10, 25),
        all_time=AllTime(Split(1234567, 617283, 617284), Split(123456, 61728, 61728),
                         Split(123456, 61728, 61728)),
        stars=123456,
    )


def personal_only_stats():
    split = Split(1310, 1310, None)
    return base_stats(
        work_available=False, year_work=None, year_total=482, year_personal=482,
        all_time_work_available=False,
        all_time=AllTime(split, Split(31, 31, None), Split(4, 4, None)),
    )


def assert_safe(svg: str) -> None:
    root = parse(svg)
    assert root.tag == f"{NS}svg"
    banned = {"script", "image", "foreignObject", "a", "use", "iframe"}
    for el in root.iter():
        assert el.tag.removeprefix(NS) not in banned
        for attr in el.attrib:
            assert not attr.endswith("href")
    assert svg.replace("http://www.w3.org/2000/svg", "").count("http") == 0
    assert "url(" not in svg.replace("url(#", "")  # only local fragment refs
    assert "@import" not in svg and "@font-face" not in svg


def test_fmt():
    assert fmt(0) == "0"
    assert fmt(999) == "999"
    assert fmt(1000) == "1,000"
    assert fmt(12345) == "12,345"


def test_wide_is_valid_svg_with_safe_content():
    svg = render_wide(base_stats())
    assert_safe(svg)
    _, _, width, height = (float(v) for v in parse(svg).get("viewBox").split())
    assert width == 760 and height > 0


@pytest.mark.parametrize("stats", [base_stats(), personal_only_stats(), big_stats(),
                                   base_stats(visitors=None, visitors_as_of=None)])
def test_narrow_viewbox_and_safe_content(stats):
    svg = narrow(stats)
    assert_safe(svg)
    root = parse(svg)
    _, _, width, height = (float(v) for v in root.get("viewBox").split())
    assert width == 390 == float(root.get("width")) and height > 0
    assert render.NARROW_WIDTH == 390
    header = ("ALEX McGREEVY // COMBINED" if stats.work_available
              else "ALEX McGREEVY // PERSONAL")
    assert header in text_contents(root)
    assert "WORK ACTIVITY: PRIVATE REPOS, COUNTS ONLY" in text_contents(root)


def test_wide_contains_headline_numbers():
    stats = base_stats(year_total=1093, year_personal=482, year_work=611)
    text = all_text(parse(render_wide(stats)))
    for needle in ("1,093", "482", "611",
                   "ALEX McGREEVY // COMBINED",
                   "WORK ACTIVITY: PRIVATE REPOS, COUNTS ONLY"):
        assert needle in text


def test_combined_header_is_exact_wide_and_narrow():
    for svg in (render_wide(base_stats()), narrow(base_stats())):
        root = parse(svg)
        assert "ALEX McGREEVY // COMBINED" in text_contents(root)
        assert "PERSONAL" not in "".join(
            t for t in text_contents(root) if t.startswith("ALEX"))
        assert root.find(f"{NS}title").text == "ALEX McGREEVY // COMBINED"


def test_personal_only_header_never_says_combined():
    stats = personal_only_stats()
    for svg in (render_wide(stats), narrow(stats)):
        root = parse(svg)
        assert "ALEX McGREEVY // PERSONAL" in text_contents(root)
        assert "COMBINED" not in all_text(root)
        assert root.find(f"{NS}title").text == "ALEX McGREEVY // PERSONAL"


def test_wide_dot_count_matches_grid():
    weeks = [[(w + d) % 5 for d in range(7)] for w in range(52)]
    weeks.append([1, 4, None, None, None, None, None])
    root = parse(render_wide(base_stats(weeks=weeks)))
    dots = [c for c in root.iter(f"{NS}circle") if "d" in classes(c)]
    cells = [lvl for col in weeks for lvl in col if lvl is not None]
    assert len(dots) == len(cells) == 366
    assert len(dots) <= 371
    # sorted by (x, y) is column-major order, the same order as `cells`
    dots.sort(key=lambda c: (float(c.get("cx")), float(c.get("cy"))))
    assert [c.get("fill") for c in dots] == [DOT_RAMP[lvl] for lvl in cells]
    assert Counter(c.get("fill") for c in dots) == Counter(DOT_RAMP[lvl] for lvl in cells)


@pytest.mark.parametrize("stats", [
    base_stats(),
    base_stats(weeks=[[(w + d) % 5 for d in range(7)] for w in range(52)]
               + [[1, 4, None, None, None, None, None]]),
])
def test_narrow_contains_every_dot(stats):
    wide_dots = [c for c in parse(render_wide(stats)).iter(f"{NS}circle") if "d" in classes(c)]
    root = parse(narrow(stats))
    dots = [c for c in root.iter(f"{NS}circle") if "d" in classes(c)]
    cells = [lvl for col in stats.weeks for lvl in col if lvl is not None]
    assert len(dots) == len(wide_dots) == len(cells)
    assert Counter(c.get("fill") for c in dots) == Counter(c.get("fill") for c in wide_dots)
    # two stacked half-year grids, older half first (above), each in date order
    older, recent = group(root, "dots-older"), group(root, "dots-recent")
    split = (len(stats.weeks) + 1) // 2
    assert 26 <= split <= 28
    for g, weeks in ((older, stats.weeks[:split]), (recent, stats.weeks[split:])):
        got = sorted((c for c in g.iter(f"{NS}circle")),
                     key=lambda c: (float(c.get("cx")), float(c.get("cy"))))
        assert [c.get("fill") for c in got] == [
            DOT_RAMP[lvl] for col in weeks for lvl in col if lvl is not None]
    max_older = max(float(c.get("cy")) for c in older.iter(f"{NS}circle"))
    min_recent = min(float(c.get("cy")) for c in recent.iter(f"{NS}circle"))
    assert max_older < min_recent
    xs = sorted({float(c.get("cx")) for c in older.iter(f"{NS}circle")})
    assert all(11 <= b - a <= 13 for a, b in zip(xs, xs[1:]))  # dot pitch about 12


def test_dots_stay_inside_viewbox(board):
    render_fn, width, _ = board
    root = parse(render_fn(base_stats()))
    for c in root.iter(f"{NS}circle"):
        assert 0 < float(c.get("cx")) - float(c.get("r"))
        assert float(c.get("cx")) + float(c.get("r")) < width


def test_recent_active_dots_pulse(board):
    render_fn, _, _ = board
    weeks = [[0] * 7 for _ in range(52)] + [[3, 2, None, None, None, None, None]]
    root = parse(render_fn(base_stats(weeks=weeks)))
    pulsing = [c for c in root.iter(f"{NS}circle") if "d" in classes(c) and "pulse" in classes(c)]
    assert len(pulsing) == 2
    assert {c.get("fill") for c in pulsing} == {DOT_RAMP[3], DOT_RAMP[2]}


def test_narrow_pulse_uses_absolute_columns():
    # the recent half starts at column 27, so its pulse cells must be offset
    weeks = [[0] * 7 for _ in range(53)]
    weeks[0] = [4] * 7  # old activity never pulses
    weeks[51] = [0, 0, 0, 0, 0, 1, 2]
    weeks[52] = [3, 4, 1, None, None, None, None]
    root = parse(narrow(base_stats(weeks=weeks)))
    for gid, n in (("dots-older", 0), ("dots-recent", 5)):
        g = group(root, gid)
        assert sum("pulse" in classes(c) for c in g.iter(f"{NS}circle")) == n


def test_narrow_drops_weekday_labels():
    texts = text_contents(parse(narrow(base_stats())))
    assert not {"MON", "WED", "FRI"} & set(texts)
    assert "LESS" in texts and "MORE" in texts


@pytest.mark.parametrize("stats", [
    base_stats(year_total=1093, year_personal=482, year_work=611),
    personal_only_stats(),
    big_stats(),
    base_stats(visitors=None, visitors_as_of=None),
    base_stats(all_time_work_available=False,
               all_time=AllTime(Split(10, 10, None), Split(2, 2, None), Split(1, 1, None))),
    base_stats(languages=[]),
])
def test_narrow_same_text_content(stats):
    wide = Counter(text_contents(parse(render_wide(stats))))
    for day in ("MON", "WED", "FRI"):  # weekday labels are dropped by design
        del wide[day]
    got = Counter(text_contents(parse(narrow(stats))))
    assert wide - got == Counter()  # every string, as many times as wide has it
    assert (sum("PERSONAL ONLY" in t for t in wide.elements())
            == sum("PERSONAL ONLY" in t for t in got.elements()))


def test_narrow_kpis_two_per_row():
    root = parse(narrow(base_stats(visitors=658, visitors_as_of=date(2026, 10, 25))))
    for gid, n in (("this-year", 4), ("all-time", 4)):
        boxes = [g for g in group(root, gid).iter(f"{NS}g") if "kpi" in classes(g)]
        assert len(boxes) == n
        rows = Counter(g.get("transform").split(",")[1] for g in boxes)
        assert sorted(rows.values()) == [2, 2]


def test_animations_are_css_only(board):
    render_fn, _, _ = board
    svg = render_fn(base_stats())
    root = parse(svg)
    style = "".join(s.text or "" for s in root.iter(f"{NS}style"))
    assert "@keyframes" in style
    assert "1.6s" in style and "1.4s" in style
    assert any("live" in classes(el) for el in root.iter())


def test_visitors_group(board):
    render_fn, _, _ = board
    stats = base_stats(visitors=658, visitors_as_of=date(2026, 10, 25))
    root = parse(render_fn(stats))
    g = group(root, VISITORS_ID)
    assert g is not None
    text = all_text(g)
    assert "658" in text and "AS OF" in text and "OCT 25" in text

    root = parse(render_fn(replace(stats, visitors=None, visitors_as_of=None)))
    assert group(root, VISITORS_ID) is None
    assert "VISITORS" not in all_text(root)


def test_personal_only_labels(board):
    render_fn, _, _ = board
    root = parse(render_fn(personal_only_stats()))
    year = all_text(group(root, "this-year"))
    assert "PERSONAL ONLY" in year
    assert "WORK" not in year
    assert "482" in year
    all_time = group(root, "all-time")
    boxes = [g for g in all_time.iter(f"{NS}g") if "kpi" in classes(g)]
    split_boxes = [b for b in boxes if any(w in all_text(b) for w in ("COMMITS", "PULL", "REVIEWS"))]
    assert len(split_boxes) == 3
    for box in split_boxes:
        text = all_text(box)
        assert "PERSONAL ONLY" in text
        assert " W" not in text and " P " not in text
    assert "1,310" in all_text(all_time)
    header = all_text(root)
    assert "2 ACCOUNTS" not in header


def test_wide_all_time_personal_only_keeps_year_split():
    stats = base_stats(
        all_time_work_available=False,
        all_time=AllTime(Split(10, 10, None), Split(2, 2, None), Split(1, 1, None)),
    )
    root = parse(render_wide(stats))
    assert "WORK" in all_text(group(root, "this-year"))
    assert "PERSONAL ONLY" in all_text(group(root, "all-time"))


def test_wide_combined_shows_p_w_splits():
    stats = base_stats(all_time=AllTime(Split(2847, 1310, 1537), Split(143, 31, 112),
                                        Split(96, 4, 92)))
    text = all_text(group(parse(render_wide(stats)), "all-time"))
    for needle in ("2,847", "1,310 P", "1,537 W", "143", "31 P", "112 W", "4 P", "92 W"):
        assert needle in text
    assert "PERSONAL ONLY" not in text


def test_wide_best_streak_window_only_label():
    text = all_text(parse(render_wide(base_stats(best_streak_window_only=True))))
    assert "12-MONTH BEST" in text
    text = all_text(parse(render_wide(base_stats(best_streak_window_only=False))))
    assert "12-MONTH" not in text and "BEST STREAK" in text


def test_wide_best_streak_month_year():
    stats = base_stats(best_streak=31, best_streak_end=date(2025, 3, 14))
    text = all_text(group(parse(render_wide(stats)), "this-year"))
    assert "031" in text and "MAR 2025" in text


def test_wide_languages_scope_label():
    text = all_text(group(parse(render_wide(base_stats(languages_scope="personal"))), "languages"))
    assert "PERSONAL" in text
    text = all_text(group(parse(render_wide(base_stats(languages_scope="combined"))), "languages"))
    assert "PERSONAL" not in text


def test_wide_language_bars_have_40_leds_lit_by_percent():
    langs = [("Swift", 74), ("Python", 7), ("Go", 0)]
    root = parse(render_wide(base_stats(languages=langs)))
    leds = [r for r in group(root, "languages").iter(f"{NS}rect") if "led" in classes(r)]
    assert len(leds) == 3 * 40
    lit = [r for r in leds if "on" in classes(r)]
    # 74% of 40 = 29.6 -> 30; 7% -> 2.8 -> 3; 0% still shows one LED
    assert len(lit) == 30 + 3 + 1
    text = all_text(group(root, "languages"))
    assert "74%" in text and "SWIFT" in text and "<1%" in text


def test_narrow_language_bars_have_24_leds():
    langs = [("Swift", 74), ("Python", 7), ("Go", 0), ("TypeScript", 100)]
    root = parse(narrow(base_stats(languages=langs)))
    leds = [r for r in group(root, "languages").iter(f"{NS}rect") if "led" in classes(r)]
    assert len(leds) == 4 * 24
    lit = [r for r in leds if "on" in classes(r)]
    # 74% of 24 = 17.76 -> 18; 7% -> 1.68 -> 2; 0% -> 1; 100% -> 24
    assert len(lit) == 18 + 2 + 1 + 24
    assert max(float(r.get("x")) + float(r.get("width")) for r in leds) < 390
    text = all_text(group(root, "languages"))
    assert "74%" in text and "SWIFT" in text and "<1%" in text


def test_wide_large_numbers_fit():
    assert_large_numbers_fit(render_wide)


def test_narrow_large_numbers_fit():
    assert_large_numbers_fit(narrow)


def assert_large_numbers_fit(render_fn):
    stats = base_stats(all_time=AllTime(Split(12345, 5000, 7345), Split(1, 1, 0),
                                        Split(1, 1, 0)))
    root = parse(render_fn(stats))
    found = False
    for g in root.iter(f"{NS}g"):
        if "kpi" not in classes(g):
            continue
        box = next(r for r in g if r.tag == f"{NS}rect")
        box_w = float(box.get("width"))
        for t in g.iter(f"{NS}text"):
            content = "".join(t.itertext())
            size = float(t.get("font-size"))
            assert len(content) * 0.6 * size <= box_w, content
            if content == "12,345":
                found = True
                # unsqueezed and inside the box padding
                assert t.get("textLength") is None
                assert float(t.get("x")) + render.text_width(content, size, 0.06) <= box_w
    assert found


def test_rows_fit_inside_board(board):
    render_fn, width, _ = board
    root = parse(render_fn(big_stats()))
    for g in root.iter(f"{NS}g"):
        if "kpi" in classes(g):
            x = float(g.get("transform").split("(")[1].split(",")[0])
            w = float(next(r for r in g if r.tag == f"{NS}rect").get("width"))
            margin = {760: 30, 390: 16}[width]  # bezel plus some padding
            assert x >= margin and x + w <= width - margin
            for t in g.iter(f"{NS}text"):  # text never spills out of its box
                content = "".join(t.itertext())
                tw = float(t.get("textLength") or render.text_width(
                    content, float(t.get("font-size")),
                    float(t.get("letter-spacing") or 0) / float(t.get("font-size"))))
                assert float(t.get("x")) + tw <= w


@pytest.mark.parametrize("stats", [base_stats(), big_stats(), personal_only_stats(),
                                   base_stats(languages=[("Jupyter Notebook", 100)] * 5)])
def test_narrow_nothing_wider_than_viewbox(stats):
    layout = render.layout_narrow(stats)
    assert layout.width == render.NARROW_WIDTH == 390
    kinds = {item.kind for item in layout.items}
    assert {"header", "kpi", "languages", "months", "dots", "legend", "footer"} <= kinds
    for item in layout.items:
        assert item.w > 0, item
        assert 6 <= item.x and item.x + item.w <= render.NARROW_WIDTH - 6, item
        assert 6 <= item.y and item.y + item.h <= layout.height - 6, item
    dots = [i for i in layout.items if i.kind == "dots"]
    assert len(dots) == 2 and dots[0].y + dots[0].h < dots[1].y
    # and the SVG agrees with the layout
    assert narrow(stats) == render.render_layout(layout, stats)


def test_wide_no_languages_renders_empty_panel():
    root = parse(render_wide(base_stats(languages=[])))
    text = all_text(group(root, "languages"))
    assert "// LANGUAGES" in text


def test_wide_month_labels_duplicates_and_collisions():
    labels = [(0, "OCT"), (4, "NOV"), (9, "DEC"), (10, "JAN"), (52, "OCT")]
    root = parse(render_wide(base_stats(month_labels=labels)))
    months = [t for t in root.iter(f"{NS}text") if "m" in classes(t)]
    names = ["".join(t.itertext()) for t in months]
    assert names == ["OCT", "NOV", "DEC", "OCT"]  # JAN collides with DEC and is dropped
    xs = [float(t.get("x")) for t in months]
    assert xs == sorted(xs)
    for a, b in zip(xs, xs[1:]):
        assert b - a >= 3 * 0.6 * 9  # no overlapping text
    assert xs[-1] + 3 * 0.6 * 9 * 1.2 <= 760 - 30


def test_narrow_month_labels_split_without_overlap():
    labels = [(0, "OCT"), (4, "NOV"), (9, "DEC"), (10, "JAN"), (30, "MAY"), (52, "OCT")]
    root = parse(narrow(base_stats(month_labels=labels)))
    months = [t for t in root.iter(f"{NS}text") if "m" in classes(t)]
    rows: dict[float, list[ET.Element]] = {}
    for t in months:
        rows.setdefault(float(t.get("y")), []).append(t)
    assert len(rows) == 2
    top, bottom = (rows[y] for y in sorted(rows))
    assert ["".join(t.itertext()) for t in top] == ["OCT", "NOV", "DEC"]  # JAN collides
    assert ["".join(t.itertext()) for t in bottom] == ["MAY", "OCT"]
    for row in (top, bottom):
        xs = [float(t.get("x")) for t in row]
        assert xs == sorted(xs)
        for a, b in zip(xs, xs[1:]):
            assert b - a >= 3 * 0.6 * 9 * 1.08
        assert xs[-1] + 3 * 0.6 * 9 * 1.08 <= 390 - 6


def test_escapes_text(board):
    render_fn, _, _ = board
    root = parse(render_fn(base_stats(languages=[("C<&>", 50)])))
    assert "C<&>" in all_text(group(root, "languages"))


def test_sample_data_is_fake_and_deterministic():
    a, b = sample_board_data(), sample_board_data()
    assert a == b
    assert a.personal.login == "sample"
    assert a.work is not None and a.work.login.startswith("sample")


def test_sample_cli_writes_wide_and_narrow_previews(tmp_path):
    from scoreboard.__main__ import main

    assert main(["--sample", str(tmp_path / "build")]) == 0
    for name, width in (("preview-wide.svg", "760"), ("preview-narrow.svg", "390")):
        svg = (tmp_path / "build" / name).read_text(encoding="utf-8")
        assert parse(svg).tag == f"{NS}svg"
        assert parse(svg).get("viewBox").split()[2] == width


@pytest.mark.parametrize("argv", [["--bogus"], ["--sample"]])
def test_cli_rejects_bad_arguments(argv):
    from scoreboard.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
