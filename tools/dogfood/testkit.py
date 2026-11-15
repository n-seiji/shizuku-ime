"""Inputs and small readers shared by the run.py tests."""

from pathlib import Path
from types import SimpleNamespace

import runstore

INPUT = (
    "日常\t基本\twhole\t0\tあ。\tア|。\n"
    "日常\t基本\tchunk\t1\tいう、え。‖お。\tイ|ウ|、|エ|。‖オ|。\n"
)

# One sentence of two clauses, typed whole (the second clause starts in the middle of the one chunk)
# and typed per mark (it starts a chunk).
TWO_CLAUSES = (
    "日常\t基本\twhole\t0\tあ、い。\tア|、|イ|。\n"
    "日常\t基本\tpunct\t0\tあ、い。\tア|、|イ|。\n"
)


def run_dirs(fake: SimpleNamespace) -> list[str]:
    return sorted(p.name for p in fake.runs.iterdir()) if fake.runs.exists() else []


def clauses_of(fake: SimpleNamespace) -> list[runstore.ClauseRow]:
    (name,) = run_dirs(fake)
    return runstore.read_clauses(fake.runs / name / "clauses.tsv")


def write_input(tmp: Path, text: str) -> str:
    path = tmp / "other.tsv"
    path.write_text(text, encoding="utf-8")
    return str(path)
