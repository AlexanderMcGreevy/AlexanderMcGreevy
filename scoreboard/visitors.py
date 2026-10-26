"""Profile-views counter: read the komarev.com badge and keep a tiny state file.

The state file holds exactly two keys (the count and the date it was read) and
nothing that identifies anyone. Reading the badge adds one view per run, which
is accepted.
"""

import json
import os
import re
import tempfile
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path

BADGE_URL = "https://komarev.com/ghpvc/?username=alexandermcgreevy"

_TEXT_NODE = re.compile(r"<text\b[^>]*>([^<]*)</text>", re.IGNORECASE)
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")


def urllib_get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "scoreboard"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_count(svg_text: str) -> int | None:
    """Return the last purely numeric <text> node (commas allowed), else None."""
    count = None
    for node in _TEXT_NODE.findall(svg_text or ""):
        value = node.strip()
        if _NUMBER.fullmatch(value):
            count = int(value.replace(",", ""))
    return count


def fetch_count(fetch: Callable[[str], str] = urllib_get) -> int | None:
    """Read the current count; any failure at all yields None."""
    try:
        return parse_count(fetch(BADGE_URL))
    except Exception:
        return None


def load_state(path: Path) -> tuple[int | None, date | None]:
    """Return (visitors, as_of) from the state file, or (None, None)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        count = data["visitors"]
        as_of = date.fromisoformat(data["as_of"])
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return None, None
        return count, as_of
    except Exception:
        return None, None


def atomic_write_text(path: Path, content: str) -> None:
    """Write via a temp file in the same directory, then rename over `path`.

    A crash or full disk leaves either the old file or the new one, never a
    half-written file. Missing parent directories are created.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.chmod(tmp, 0o644)  # mkstemp makes it owner-only
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_state(path: Path, count: int, as_of: date) -> None:
    payload = {"visitors": int(count), "as_of": as_of.isoformat()}
    atomic_write_text(Path(path), json.dumps(payload, indent=2) + "\n")
