#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Compare two dogfood runs clause by clause: the score change, and the clauses fixed or broken.

    uv run --script tools/dogfood/cmp_runs.py OLD NEW [--show N]

OLD and NEW are run directories, or run names under $SHIZUKU_DOGFOOD_DIR/runs/ (for example
`cc2601e-001`). Clauses are matched by (key line, sentence, clause), so runs of different builds
line up as long as they used the same input. The score totals cover the clauses both runs have.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import runstore

log = logging.getLogger("dogfood")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument(
        "--show", type=int, default=20, help="most fixed/broken clauses to list"
    )
    args = ap.parse_args(argv)
    runs_dir = runstore.dogfood_dir(os.environ) / "runs"
    try:
        old_dir = runstore.resolve_run(args.old, runs_dir)
        new_dir = runstore.resolve_run(args.new, runs_dir)
        comparison = runstore.compare(
            runstore.read_clauses(old_dir / "clauses.tsv"),
            runstore.read_clauses(new_dir / "clauses.tsv"),
        )
    except (OSError, KeyError, ValueError) as err:
        log.error("cmp_runs: %s", err)
        return 2
    print(f"old: {old_dir.name}\nnew: {new_dir.name}")
    print("\n".join(runstore.format_comparison(comparison, args.show)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
