"""Where runs are written ($SHIZUKU_DOGFOOD_DIR/runs/<commit>-<NNN>/), how they are read back
and how two runs are compared.

A run directory holds:
  clauses.tsv     one line per clause: status, rank, score, cut, want, got, the paragraph's key line
  paragraphs.tsv  one line per paragraph: split, check verdict, committed text, key line
  summary.tsv     key<TAB>value lines (commit, totals, judge)

A clause is identified by (key line, sentence, clause): the key line comes from the input, so
the same clause is found again whatever a new build commits. <NNN> counts runs across all
commits, so the previous run is the highest number.

`cut` is 1 for a clause whose Space query could not type the paragraph's own history: the clause
starts in the middle of a chunk, so the query commits that chunk early (typing_plan.py). Its
rank is a good estimate, not a measurement of the real typing. Runs written before the column
existed read as 0.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

CLAUSE_COLUMNS = (
    "para",
    "sent",
    "clause",
    "split",
    "scene",
    "aspect",
    "status",
    "rank",
    "score",
    "cut",
    "want",
    "got",
    "keys",
)
PARAGRAPH_COLUMNS = ("para", "split", "check", "committed", "keys")
_RUN_NAME = re.compile(r"^(?P<commit>[0-9A-Za-z]+)-(?P<seq>\d{3,})$")


class ClauseRow(NamedTuple):
    para: int
    sent: int  # 1-based within the paragraph
    clause: int  # 1-based within the sentence
    split: str
    scene: str
    aspect: str
    status: str  # match | notation | rank | retype | nolist
    rank: int  # 0 unless status is rank
    score: int
    cut: int  # 1 when the Space query cut a chunk (see the module docstring), else 0
    want: str  # accepted clauses joined by |
    got: str
    keys: str

    @property
    def identity(self) -> tuple[str, int, int]:
        return (self.keys, self.sent, self.clause)


def dogfood_dir(environ: Mapping[str, str]) -> Path:
    default = Path.home() / ".local" / "share" / "shizuku-dogfood"
    return Path(environ.get("SHIZUKU_DOGFOOD_DIR") or default)


_ESCAPES = {"\\": "\\\\", "\n": "\\n", "\t": "\\t", "\r": "\\r"}
_UNESCAPES = {"\\": "\\", "n": "\n", "t": "\t", "r": "\r"}
_ESCAPED = re.compile(r"\\(.)", re.DOTALL)


def _escape(text: str) -> str:
    """Backslash, newline, tab and carriage return as `\\`, `\\n`, `\\t`, `\\r`; reversible."""
    return "".join(_ESCAPES.get(c, c) for c in text)


def _unescape(text: str) -> str:
    return _ESCAPED.sub(lambda m: _UNESCAPES.get(m[1], m[0]), text)


def _write_atomically(path: Path, text: str) -> None:
    """Write beside the file and rename, so the file exists only when it is whole."""
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_table(
    path: Path, columns: tuple[str, ...], rows: list[tuple[object, ...]]
) -> None:
    lines = ["\t".join(columns)]
    lines += ["\t".join(_escape(str(v)) for v in row) for row in rows]
    _write_atomically(path, "\n".join(lines) + "\n")


def read_table(path: Path) -> list[dict[str, str]]:
    # split on "\n" only: str.splitlines also cuts at U+2028, \x0b, \x85 and so on
    lines = path.read_text(encoding="utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        raise ValueError(f"{path} is empty")
    header = lines[0].split("\t")
    return [
        dict(zip(header, (_unescape(v) for v in line.split("\t"))))
        for line in lines[1:]
    ]


def read_clauses(path: Path) -> list[ClauseRow]:
    out = []
    for r in read_table(path):
        out.append(
            ClauseRow(
                int(r["para"]),
                int(r["sent"]),
                int(r["clause"]),
                r["split"],
                r["scene"],
                r["aspect"],
                r["status"],
                int(r["rank"]),
                int(r["score"]),
                int(r.get("cut", "0")),
                r["want"],
                r["got"],
                r["keys"],
            )
        )
    return out


def write_summary(path: Path, items: list[tuple[str, str]]) -> None:
    _write_atomically(path, "".join(f"{k}\t{_escape(v)}\n" for k, v in items))


def read_summary(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").split("\n")
    pairs = (line.split("\t", 1) for line in lines if "\t" in line)
    return {k: _unescape(v) for k, v in pairs}


@dataclass(frozen=True)
class Baseline:
    """A finished run, read back to compare a new one with."""

    name: str
    summary: Mapping[str, str]
    clauses: tuple[ClauseRow, ...]


def read_baseline(path: Path) -> Baseline:
    """Raises OSError, KeyError or ValueError when the run's files cannot be read."""
    summary = read_summary(path / "summary.tsv")
    return Baseline(path.name, summary, tuple(read_clauses(path / "clauses.tsv")))


def list_runs(runs_dir: Path) -> list[tuple[int, Path]]:
    """Complete runs (a clauses.tsv exists) as (sequence, path), oldest first."""
    found = []
    if runs_dir.is_dir():
        for entry in runs_dir.iterdir():
            match = _RUN_NAME.match(entry.name)
            if match and (entry / "clauses.tsv").is_file():
                found.append((int(match["seq"]), entry))
    return sorted(found)


def previous_run(runs_dir: Path) -> Path | None:
    runs = list_runs(runs_dir)
    return runs[-1][1] if runs else None


def create_run_dir(runs_dir: Path, commit: str) -> Path:
    """Make runs/<commit>-<NNN> with the next number across all runs (a taken name is an error)."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    taken = [
        int(m["seq"])
        for m in (_RUN_NAME.match(e.name) for e in runs_dir.iterdir())
        if m
    ]
    seq = max(taken, default=0) + 1
    path = runs_dir / f"{commit}-{seq:03d}"
    path.mkdir()
    return path


def resolve_run(arg: str, runs_dir: Path) -> Path:
    """A run given as a path, or as a name under the runs directory."""
    for candidate in (Path(arg), runs_dir / arg):
        if (candidate / "clauses.tsv").is_file():
            return candidate
    raise FileNotFoundError(f"no run (clauses.tsv) at {arg} or under {runs_dir}")


@dataclass(frozen=True)
class Comparison:
    shared: int
    old_score: int  # totals over the clauses both runs have
    new_score: int
    fixed: tuple[tuple[ClauseRow, ClauseRow], ...]  # wrong -> right
    broken: tuple[tuple[ClauseRow, ClauseRow], ...]  # right -> wrong
    cheaper: tuple[
        tuple[ClauseRow, ClauseRow], ...
    ]  # wrong both times, lower score now
    costlier: tuple[
        tuple[ClauseRow, ClauseRow], ...
    ]  # wrong both times, higher score now
    # score 0 both times, but match <-> notation (for example 十時 that became 10時)
    drifted: tuple[tuple[ClauseRow, ClauseRow], ...]
    added: tuple[ClauseRow, ...]  # only in the new run
    removed: tuple[ClauseRow, ...]  # only in the old run


def compare(old: Sequence[ClauseRow], new: Sequence[ClauseRow]) -> Comparison:
    """Match clauses by identity. Right means score 0 (an exact or notation match)."""
    old_by = {r.identity: r for r in old}
    new_by = {r.identity: r for r in new}
    pairs = [(old_by[k], new_by[k]) for k in new_by if k in old_by]
    return Comparison(
        shared=len(pairs),
        old_score=sum(o.score for o, _ in pairs),
        new_score=sum(n.score for _, n in pairs),
        fixed=tuple(p for p in pairs if p[0].score > 0 and p[1].score == 0),
        broken=tuple(p for p in pairs if p[0].score == 0 and p[1].score > 0),
        cheaper=tuple(p for p in pairs if 0 < p[1].score < p[0].score),
        costlier=tuple(p for p in pairs if 0 < p[0].score < p[1].score),
        drifted=tuple(
            p
            for p in pairs
            if p[0].score == p[1].score == 0 and p[0].status != p[1].status
        ),
        added=tuple(r for r in new if r.identity not in old_by),
        removed=tuple(r for r in old if r.identity not in new_by),
    )


def _show_pairs(
    title: str,
    pairs: tuple[tuple[ClauseRow, ClauseRow], ...],
    limit: int,
    show_text: bool,
) -> list[str]:
    if not pairs:
        return []
    lines = [f"{title} ({len(pairs)}):"]
    for old, new in pairs[:limit]:
        where = f"  para {new.para}.{new.sent}.{new.clause}"
        lines.append(f"{where}  want {new.want}" if show_text else where)
        was = f"{old.got!r} " if show_text else ""
        now = f"{new.got!r} " if show_text else ""
        lines.append(f"      was {was}({old.status}, score {old.score})")
        lines.append(f"      now {now}({new.status}, score {new.score})")
    if len(pairs) > limit:
        lines.append(f"  ... {len(pairs) - limit} more")
    return lines


def format_comparison(
    c: Comparison, limit: int = 20, show_text: bool = False
) -> list[str]:
    """The report shared by run.py and cmp_runs.py. The clauses are named by para.sent.clause,
    status and score; the wanted and committed text (which may be private) only with show_text.
    """
    delta = c.new_score - c.old_score
    lines = [
        f"compared clauses: {c.shared}  score {c.old_score} -> {c.new_score} ({delta:+d})",
        (
            f"fixed {len(c.fixed)}  broken {len(c.broken)}  cheaper {len(c.cheaper)}"
            f"  costlier {len(c.costlier)}"
            f"  match<->notation {len(c.drifted)}  new {len(c.added)}  gone {len(c.removed)}"
        ),
    ]
    lines += _show_pairs("fixed", c.fixed, limit, show_text)
    lines += _show_pairs("broken", c.broken, limit, show_text)
    lines += _show_pairs(
        "match <-> notation (score stays 0)", c.drifted, limit, show_text
    )
    return lines
