import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import replace
from datetime import date

import pytest

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


def test_fmt():
    assert fmt(0) == "0"
    assert fmt(999) == "999"
    assert fmt(1000) == "1,000"
    assert fmt(12345) == "12,345"


def test_wide_is_valid_svg_with_safe_content():
    svg = render_wide(base_stats())
    root = parse(svg)
    assert root.tag == f"{NS}svg"
    _, _, width, height = (float(v) for v in root.get("viewBox").split())
    assert width == 760 and height > 0
    banned = {"script", "image", "foreignObject", "a", "use", "iframe"}
    for el in root.iter():
        assert el.tag.removeprefix(NS) not in banned
        for attr in el.attrib:
            assert not attr.endswith("href")
    assert svg.replace("http://www.w3.org/2000/svg", "").count("http") == 0
    assert "url(" not in svg.replace("url(#", "")  # only local fragment refs
    assert "@import" not in svg and "@font-face" not in svg


def test_wide_contains_headline_numbers():
    stats = base_stats(year_total=1093, year_personal=482, year_work=611)
    text = all_text(parse(render_wide(stats)))
    for needle in ("1,093", "482", "611",
                   "ALEX McGREEVY // COMBINED",
                   "WORK ACTIVITY: PRIVATE REPOS, COUNTS ONLY"):
        assert needle in text


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


def test_wide_dots_stay_inside_viewbox():
    root = parse(render_wide(base_stats()))
    for c in root.iter(f"{NS}circle"):
        assert 0 < float(c.get("cx")) - float(c.get("r"))
        assert float(c.get("cx")) + float(c.get("r")) < 760


def test_wide_recent_active_dots_pulse():
    weeks = [[0] * 7 for _ in range(52)] + [[3, 2, None, None, None, None, None]]
    root = parse(render_wide(base_stats(weeks=weeks)))
    pulsing = [c for c in root.iter(f"{NS}circle") if "d" in classes(c) and "pulse" in classes(c)]
    assert len(pulsing) == 2


def test_wide_animations_are_css_only():
    svg = render_wide(base_stats())
    root = parse(svg)
    style = "".join(s.text or "" for s in root.iter(f"{NS}style"))
    assert "@keyframes" in style
    assert "1.6s" in style and "1.4s" in style
    assert any("live" in classes(el) for el in root.iter())


def test_wide_visitors_group():
    stats = base_stats(visitors=658, visitors_as_of=date(2026, 10, 25))
    root = parse(render_wide(stats))
    g = group(root, VISITORS_ID)
    assert g is not None
    text = all_text(g)
    assert "658" in text and "AS OF" in text and "OCT 25" in text

    root = parse(render_wide(replace(stats, visitors=None, visitors_as_of=None)))
    assert group(root, VISITORS_ID) is None
    assert "VISITORS" not in all_text(root)


def test_wide_personal_only_labels():
    split = Split(1310, 1310, None)
    stats = base_stats(
        work_available=False, year_work=None, year_total=482, year_personal=482,
        all_time_work_available=False,
        all_time=AllTime(split, Split(31, 31, None), Split(4, 4, None)),
    )
    root = parse(render_wide(stats))
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


def test_wide_large_numbers_fit():
    stats = base_stats(all_time=AllTime(Split(12345, 5000, 7345), Split(1, 1, 0),
                                        Split(1, 1, 0)))
    root = parse(render_wide(stats))
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
    assert found


def test_wide_rows_fit_inside_board():
    stats = base_stats(
        year_total=123456, year_personal=61728, year_work=61728,
        current_streak=1234, best_streak=1234, best_streak_window_only=True,
        visitors=12345678, visitors_as_of=date(2026, 10, 25),
        all_time=AllTime(Split(1234567, 617283, 617284), Split(123456, 61728, 61728),
                         Split(123456, 61728, 61728)),
        stars=123456,
    )
    root = parse(render_wide(stats))
    for g in root.iter(f"{NS}g"):
        if "kpi" in classes(g):
            x = float(g.get("transform").split("(")[1].split(",")[0])
            w = float(next(r for r in g if r.tag == f"{NS}rect").get("width"))
            assert x >= 30 and x + w <= 730


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


def test_wide_escapes_text():
    root = parse(render_wide(base_stats(languages=[("C<&>", 50)])))
    assert "C<&>" in all_text(group(root, "languages"))


def test_sample_data_is_fake_and_deterministic():
    a, b = sample_board_data(), sample_board_data()
    assert a == b
    assert a.personal.login == "sample"
    assert a.work is not None and a.work.login.startswith("sample")


def test_sample_cli_writes_wide_preview(tmp_path):
    from scoreboard.__main__ import main

    assert main(["--sample", str(tmp_path / "build")]) == 0
    svg = (tmp_path / "build" / "preview-wide.svg").read_text(encoding="utf-8")
    assert parse(svg).tag == f"{NS}svg"


@pytest.mark.parametrize("argv", [[], ["--bogus"]])
def test_cli_without_sample_is_an_error(argv):
    from scoreboard.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
