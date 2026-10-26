"""Command line entry point.

For now only the preview path exists:

    python -m scoreboard --sample build/

renders the board from the fake data in `sample.py` into that directory.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .render import render_wide
from .sample import sample_board_data
from .stats import compute_stats


def write_previews(out_dir: Path) -> list[Path]:
    stats = compute_stats(sample_board_data())
    out_dir.mkdir(parents=True, exist_ok=True)
    wide = out_dir / "preview-wide.svg"
    wide.write_text(render_wide(stats), encoding="utf-8")
    return [wide]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scoreboard")
    parser.add_argument("--sample", metavar="DIR", type=Path,
                        help="write preview SVGs rendered from fake sample data")
    args = parser.parse_args(argv)
    if args.sample is None:
        parser.error("only --sample DIR is available so far")
    for path in write_previews(args.sample):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
