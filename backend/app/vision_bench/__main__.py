"""`python -m app.vision_bench` — run the corpus and print the report."""

from __future__ import annotations

import argparse
import json
import sys
import warnings

from .runner import run, summary, table


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="app.vision_bench", description=__doc__)
    parser.add_argument("--model", default=None, help="model name to record (nothing is called)")
    parser.add_argument("--only", nargs="*", default=None, help="run only these cases")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    # Pillow warns about the decompression-bomb case by design; the bench is where that case is
    # supposed to be, so the warning is noise here rather than news.
    warnings.filterwarnings("ignore", message=".*decompression bomb.*")

    rows = run(model=args.model, only=args.only)
    if args.json:
        print(json.dumps({"rows": [row.as_dict() for row in rows], "summary": summary(rows)}, indent=2))
    else:
        print(table(rows))
        print()
        for key, value in summary(rows).items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
