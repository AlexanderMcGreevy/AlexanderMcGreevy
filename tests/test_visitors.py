import json
from datetime import date

from scoreboard import visitors

# Verbatim copy of the live komarev.com badge response (count was 661 when captured).
REAL_BADGE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="110.2" height="20">
    <linearGradient id="b" x2="0" y2="100%">
        <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
        <stop offset="1" stop-opacity=".1"/>
    </linearGradient>
    <mask id="a">
        <rect width="110.2" height="20" rx="3" fill="#fff"/>
    </mask>
    <g mask="url(#a)">
        <rect width="79.2" height="20" fill="#555"/>
        <rect x="79.2" width="31" height="20" fill="#007ec6"/>
        <rect width="110.2" height="20" fill="url(#b)"/>
    </g>
    <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
        <text x="40.6" y="15" fill="#010101" fill-opacity=".3">Profile views</text>
        <text x="40.6" y="14">Profile views</text>
        <text x="93.7" y="15" fill="#010101" fill-opacity=".3">661</text>
        <text x="93.7" y="14">661</text>
    </g>
</svg>
"""


def test_parse_count_reads_last_number():
    assert visitors.parse_count(REAL_BADGE_SVG) == 661
    assert visitors.parse_count(REAL_BADGE_SVG.replace(">661<", ">658<")) == 658
    assert visitors.parse_count(REAL_BADGE_SVG.replace(">661<", ">1,234<")) == 1234


def test_parse_count_garbage_returns_none():
    html = "<html><body><h1>502 Bad Gateway</h1><p>Try again later.</p></body></html>"
    assert visitors.parse_count(html) is None
    assert visitors.parse_count("") is None
    assert visitors.parse_count("<svg><text>Profile views</text><text>n/a</text></svg>") is None
    assert visitors.parse_count("no digits here at all") is None


def test_fetch_count_swallows_errors():
    def boom(url):
        raise OSError("network down")

    assert visitors.fetch_count(boom) is None
    assert visitors.fetch_count(lambda url: "<html>nope</html>") is None
    assert visitors.fetch_count(lambda url: REAL_BADGE_SVG) == 661


def test_fetch_count_requests_badge_url():
    seen = []

    def fake(url):
        seen.append(url)
        return REAL_BADGE_SVG

    visitors.fetch_count(fake)
    assert seen == [visitors.BADGE_URL]


def test_state_roundtrip_and_missing_file(tmp_path):
    path = tmp_path / "state.json"
    assert visitors.load_state(path) == (None, None)

    visitors.save_state(path, 661, date(2026, 10, 25))
    assert visitors.load_state(path) == (661, date(2026, 10, 25))
    assert json.loads(path.read_text()) == {"visitors": 661, "as_of": "2026-10-25"}


def test_load_state_corrupt_file_returns_none_pair(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    assert visitors.load_state(path) == (None, None)
