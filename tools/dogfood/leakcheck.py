#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Fail when text meant for publishing quotes the private chat lines.

    uv run --script tools/dogfood/leakcheck.py [--private LINES] [--private-keys TSV]...
                                               [--public FILE]... [--allow FILE] TARGET...

The private lines are $SHIZUKU_DOGFOOD_DIR/private/real_lines.txt unless --private says
otherwise. When that default file does not exist and no --private-keys table is given there is
nothing to check against, which is said out loud and succeeds; with a --private-keys table the
typed keys alone are checked. A file named on the command line (--private, --private-keys,
--public, --allow, a TARGET) that does not exist is an error (exit 2): a gate that was asked to
look somewhere must not pass because the place is missing. Exit 1 is only for a hit.

A hit is a whole private line, or WINDOW characters of one, found in a target. Fragments that
also occur in a --public file (the main tree, constructed corpora) or that are listed in the
--allow file (reviewed false positives) do not count. A --private-keys TSV (the paragraphs.tsv
of a run over the private lines, its `keys` column) adds the romaji typed for each paragraph;
those match only as a whole. Hits are reported by line number, never by text, so the output
can be read without learning the private lines. This finds only verbatim quotes of 7 or more
characters; a reworded line is not found.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

import runstore

WINDOW = 7
MIN_LINE = 4
MIN_KEYS = 8
log = logging.getLogger("dogfood")


def fragments(line: str) -> list[str]:
    return [line[i : i + WINDOW] for i in range(len(line) - WINDOW + 1)]


def is_quoted(line: str, text: str, public: str, allowed: list[str]) -> bool:
    """Whether `text` quotes `line` (the whole line, or a WINDOW-character piece of it)."""
    if line in text and line not in public and line not in allowed:
        return True
    pieces = [f for f in fragments(line) if f in text and f not in public]
    return any(not any(f in a or a in f for a in allowed) for f in pieces)


def typed_keys(paths: list[Path]) -> set[str]:
    """Typed romaji (without `<...>` tokens) of each paragraph in the given run tables."""
    keys = set()
    for path in paths:
        for row in runstore.read_table(path):
            typed = re.sub(r"<[^>]+>", "", row["keys"])
            if len(typed) >= MIN_KEYS:
                keys.add(typed)
    return keys


def find_hits(
    text: str,
    private: list[tuple[int, str]],
    keys: set[str],
    public: str,
    allowed: list[str],
) -> list[str]:
    hits = [
        f"private line {number}"
        for number, line in private
        if is_quoted(line, text, public, allowed)
    ]
    quoted_keys = sum(1 for k in keys if k in text and k not in public)
    return hits + ([f"{quoted_keys} typed key line(s)"] if quoted_keys else [])


def explicit_paths(args: argparse.Namespace) -> list[Path]:
    """Every file the command line names; each must exist."""
    named = [args.private, args.allow, *args.private_keys, *args.public, *args.targets]
    return [p for p in named if p is not None]


def check(args: argparse.Namespace, private_path: Path | None) -> int:
    lines = (
        private_path.read_text(encoding="utf-8").splitlines() if private_path else []
    )
    private = [
        (n, s.strip()) for n, s in enumerate(lines, 1) if len(s.strip()) >= MIN_LINE
    ]
    public = "\n".join(
        p.read_text(encoding="utf-8", errors="replace") for p in args.public
    )
    allowed: list[str] = []
    if args.allow:
        allowed = [
            s.strip()
            for s in args.allow.read_text(encoding="utf-8").splitlines()
            if s.strip()
        ]
    keys = typed_keys(args.private_keys)

    leaked = False
    for target in args.targets:
        text = target.read_text(encoding="utf-8", errors="replace")
        hits = find_hits(text, private, keys, public, allowed)
        if hits:
            leaked = True
            print(f"{target}: quotes private text: {', '.join(hits)}")
    if not leaked:
        print(
            f"leakcheck: {len(args.targets)} file(s) checked against {len(private)} private line(s); passed"
        )
    return 1 if leaked else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--private", type=Path)
    ap.add_argument("--private-keys", action="append", default=[], type=Path)
    ap.add_argument("--public", action="append", default=[], type=Path)
    ap.add_argument("--allow", type=Path)
    ap.add_argument("targets", nargs="*", type=Path)
    args = ap.parse_args(argv)

    missing = [str(p) for p in explicit_paths(args) if not p.is_file()]
    if missing:
        log.error("leakcheck: not a file: %s", ", ".join(missing))
        return 2
    private_path = (
        args.private or runstore.dogfood_dir(os.environ) / "private" / "real_lines.txt"
    )
    if not private_path.is_file():
        if not args.private_keys:
            print(
                "leakcheck: nothing to check against (no private lines file at the default place); passed"
            )
            return 0
        private_path = None  # the typed keys alone are still checked
    if not args.targets:
        ap.error("no TARGET files given")
    try:
        return check(args, private_path)
    except (OSError, KeyError, ValueError) as err:
        log.error("leakcheck: %s", err)
        return 2


if __name__ == "__main__":
    sys.exit(main())
