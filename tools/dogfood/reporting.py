"""What a run leaves behind: the per-paragraph outcome, the summary, the files and the printed report."""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import runstore
from runstore import Baseline, ClauseRow
from simulator import SimConfig
from typing_plan import Paragraph

STATUSES = ("match", "notation", "rank", "retype", "nolist")


@dataclass(frozen=True)
class Outcome:
    """One paragraph's result."""

    paragraph: Paragraph
    keys: str
    committed: str
    composing: str
    rows: tuple[ClauseRow, ...]
    check: str = ""  # "" | STAL | WYSI (only with --check-preedit)


def summary_items(
    config: SimConfig,
    args: argparse.Namespace,
    outcomes: list[Outcome],
    commit: str,
    dirty: bool,
    input_bytes: bytes,
) -> list[tuple[str, str]]:
    rows = [r for o in outcomes for r in o.rows]
    counts = Counter(r.status for r in rows)
    built = datetime.fromtimestamp(config.binary.stat().st_mtime, UTC)
    return [
        ("commit", commit),
        ("dirty", str(int(dirty))),
        ("binary", str(config.binary)),
        ("binary_built", built.isoformat(timespec="seconds")),
        ("input", Path(args.input).name),
        ("input_sha256", hashlib.sha256(input_bytes).hexdigest()),
        ("judge", config.judge),
        ("check_preedit", str(int(args.check_preedit))),
        ("paragraphs", str(len(outcomes))),
        ("clauses", str(len(rows))),
        ("mismatched", str(sum(r.score > 0 for r in rows))),
        ("score", str(sum(r.score for r in rows))),
        *((f"status_{name}", str(counts[name])) for name in STATUSES),
        ("cut_queries", str(sum(r.cut for r in rows))),
        ("check_failures", str(sum(bool(o.check) for o in outcomes))),
        ("finished_at", datetime.now(UTC).isoformat(timespec="seconds")),
    ]


def write_run(
    run_dir: Path, outcomes: list[Outcome], items: list[tuple[str, str]]
) -> None:
    """clauses.tsv goes last: a run counts as complete only once it exists."""
    runstore.write_summary(run_dir / "summary.tsv", items)
    paragraphs = [
        (
            o.paragraph.index,
            o.paragraph.split,
            o.check,
            o.committed + (f" +composing {o.composing}" if o.composing else ""),
            o.keys,
        )
        for o in outcomes
    ]
    runstore.write_table(
        run_dir / "paragraphs.tsv", runstore.PARAGRAPH_COLUMNS, paragraphs
    )
    clauses = [tuple(r) for o in outcomes for r in o.rows]
    runstore.write_table(run_dir / "clauses.tsv", runstore.CLAUSE_COLUMNS, clauses)


def _comparison_lines(
    s: dict[str, str],
    rows: list[ClauseRow],
    baseline: Baseline | None,
    limit: int,
    show_text: bool,
) -> list[str]:
    if baseline is None:
        return ["previous run: none"]
    unlike = [
        f"{k} {baseline.summary.get(k, '?')}"
        for k in ("input", "judge")
        if baseline.summary.get(k) != s[k]
    ]
    note = f"  (that run had {', '.join(unlike)})" if unlike else ""
    comparison = runstore.compare(baseline.clauses, rows)
    return [
        f"previous run: {baseline.name}{note}",
        *runstore.format_comparison(comparison, limit, show_text),
    ]


def report_lines(
    run_dir: Path,
    items: list[tuple[str, str]],
    rows: list[ClauseRow],
    baseline: Baseline | None,
    limit: int,
    show_text: bool = False,
) -> list[str]:
    s = dict(items)
    return [
        f"run: {run_dir}",
        (
            f"commit {s['commit']} (dirty {s['dirty']}, of the checkout this script is in)  "
            f"judge {s['judge']}  input {s['input']}"
        ),
        f"binary {s['binary']} (built {s['binary_built']})",
        (
            f"paragraphs {s['paragraphs']}  clauses {s['clauses']}  "
            f"mismatched {s['mismatched']}  score {s['score']}"
        ),
        (
            f"match {s['status_match']}  notation {s['status_notation']}  "
            f"rank {s['status_rank']}  retype {s['status_retype']}  nolist {s['status_nolist']}  "
            f"check failures {s['check_failures']}"
        ),
        f"Space queries that cut a chunk (their rank is an estimate): {s['cut_queries']}",
        *_comparison_lines(s, rows, baseline, limit, show_text),
    ]
