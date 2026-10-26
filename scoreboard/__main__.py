"""Command line entry point.

    python -m scoreboard [--out DIR]

runs the daily pipeline against GitHub with PERSONAL_GH_TOKEN and
WORK_GH_TOKEN from the environment, writing `assets/` under DIR (default: the
current directory). The exit code is the pipeline's (0, 2 or 3; see
`pipeline.py`).

    python -m scoreboard --sample build/

renders the board from the fake data in `sample.py` into that directory.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from typing import Sequence

from . import pipeline
from .github import make_transport
from .render import render_narrow, render_wide
from .stats import compute_stats
from .visitors import fetch_count


def write_previews(out_dir: Path) -> list[Path]:
    # Imported here so the live pipeline never loads the fake sample data.
    from .sample import sample_board_data

    stats = compute_stats(sample_board_data())
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, render in (("preview-wide.svg", render_wide), ("preview-narrow.svg", render_narrow)):
        path = out_dir / name
        path.write_text(render(stats), encoding="utf-8")
        written.append(path)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scoreboard")
    parser.add_argument("--sample", metavar="DIR", type=Path,
                        help="write preview SVGs rendered from fake sample data")
    parser.add_argument("--out", metavar="DIR", type=Path, default=Path("."),
                        help="directory that holds assets/ (default: current directory)")
    args = parser.parse_args(argv)
    if args.sample is not None:
        for path in write_previews(args.sample):
            print(f"wrote {path}")
        return 0
    return pipeline.run(os.environ, args.out, date.today(), make_transport, fetch_count)


if __name__ == "__main__":
    sys.exit(main())
