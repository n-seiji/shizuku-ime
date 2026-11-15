#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Type paragraphs through Shizuku's real key path (the headless simulator, live conversion and the
judge) and score what comes out as extra keystrokes per clause.

    mise run dogfood                                  # tools/dogfood/seed.tsv, judge required
    uv run --script tools/dogfood/run.py INPUT.tsv [--judge required|off] [--check-preedit]
                                         [--against RUN] [--show N] [--print-keys]

Input: a TSV, one paragraph per line, six tab-separated columns

    scene  aspect  split(chunk|punct|whole)  seed  golds  readings

golds: the correct sentences separated by `‖`, each with alternatives separated by `|`.
readings: the same sentences as katakana tokens, tokens separated by `|`, sentences by `‖`.
`seed` fixes the chunk sizes, so one input always types the same key line. The typing rules are
in typing_plan.py, the scoring in scoring.py, the files written in reporting.py and runstore.py;
seed.tsv is an example.

Environment: SHIZUKU_DICTIONARY (the dictionary/ directory) and, with --judge required (the
default), SHIZUKU_JUDGE_DIR must be set; SHIZUKU_BIN overrides target/release/shizuku;
SHIZUKU_DOGFOOD_DIR (default ~/.local/share/shizuku-dogfood) receives runs/<commit>-<NNN>/.
The commit and dirty flag in a run's name and summary describe the checkout this script lives in;
the binary that was run (SHIZUKU_BIN or target/release/shizuku) and when it was built are
recorded separately. Nothing is written to the repository. If the judge cannot be shown to have run, or the
simulator prints a different number of lines than expected, the run stops without writing.

How a paragraph is scored. The simulator prints the committed text after every key, so the text
that each Enter committed is known. A sentence always ends with an Enter, so the text of a
sentence is the sum of its Enters' text; it is cut into clauses after 、。？！ and lined up with the
clauses of the gold (and of the reading). A sentence whose clause count differs from its
reading is not lined up: all its clauses count as typed again. A clause that equals a gold, or
differs only in how numerals are written (十時 / 10時), costs 0. For any other clause the
paragraph is typed again up to that clause with the same Enters, then `<space-mode>`, the
clause and `<space>`, and the place of the gold in the candidate list gives the score. Kana for
kanji is not the gold (a spelling that is fine either way is a second gold in the input). When
Space opens no list (a clause that starts with English is committed as typed) the status is
`nolist`, scored like a retype. When the clause starts in the middle of a chunk, the query has to
commit that chunk early, so the keys before it are not the start of the paragraph's key line:
such clauses are marked `cut` and counted in the summary.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import runstore
from reporting import Outcome, report_lines, summary_items, write_run
from runstore import Baseline, ClauseRow
from scoring import Probe, Verdict, classify_sentence, rank_of, settle
from simulator import (
    SimConfig,
    SimulatorError,
    VerboseRun,
    make_config,
    preflight,
    simulate_batch,
    simulate_keys,
)
from typing_plan import (
    Chunk,
    InputError,
    Paragraph,
    clause_query_keys,
    clause_spans,
    key_line,
    make_chunks,
    parse_input,
    query_cuts_chunk,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = Path(__file__).resolve().parent / "seed.tsv"
SOURCE_PATHS = ("src", "resources", "dictionary", "Cargo.toml", "Cargo.lock")
log = logging.getLogger("dogfood")
Probes = dict[tuple[int, int], Probe]


def sentence_texts(run: VerboseRun, chunks: tuple[Chunk, ...], count: int) -> list[str]:
    """The text committed for each sentence: what each Enter added, in order."""
    enters = [s for s in run.steps if s.token == "<enter>"]
    if len(enters) != len(chunks):
        raise SimulatorError(f"{len(enters)} Enter steps for {len(chunks)} chunks")
    texts = [""] * count
    previous = ""
    for step, chunk in zip(enters, chunks):
        if not step.committed.startswith(previous):
            raise SimulatorError("the committed text changed other than by appending")
        texts[chunk.sentence] += step.committed[len(previous) :]
        previous = step.committed
    if run.final != previous:
        raise SimulatorError("text was committed after the last Enter")
    return texts


def judge_expected(p: Paragraph, chunks: tuple[Chunk, ...]) -> bool:
    """A composition that starts with an ASCII token stays raw (`Rust...`) and is never judged;
    one that starts with Japanese is, so a paragraph with such a chunk must show judge lines.
    """
    return any(not p.sentences[c.sentence].tokens[c.start].isascii() for c in chunks)


def measure_probes(
    config: SimConfig,
    p: Paragraph,
    chunks: tuple[Chunk, ...],
    keys: str,
    verdicts: list[list[Verdict]],
) -> Probes:
    """For each clause that is a miss, what Space shows when only that clause is converted:
    whether a list opened, the place of the gold in it (0 = absent), whether the query had to
    cut a chunk."""
    probes: Probes = {}
    for si, sentence in enumerate(p.sentences):
        spans = clause_spans(sentence.tokens)
        for ci, verdict in enumerate(verdicts[si]):
            if verdict.kind != "miss":
                continue
            query = clause_query_keys(p, chunks, si, spans[ci])
            shown = simulate_keys(config, query).steps[-1]
            probes[(si, ci)] = Probe(
                shown.listed,
                rank_of(shown.candidates, verdict),
                query_cuts_chunk(keys, query),
            )
    return probes


def build_rows(
    p: Paragraph, keys: str, verdicts: list[list[Verdict]], probes: Probes
) -> list[ClauseRow]:
    rows = []
    for si, sentence_verdicts in enumerate(verdicts):
        for ci, verdict in enumerate(sentence_verdicts):
            probe = probes.get((si, ci), Probe(True, 0))
            status, score = settle(verdict, probe)
            rows.append(
                ClauseRow(
                    p.index,
                    si + 1,
                    ci + 1,
                    p.split,
                    p.scene,
                    p.aspect,
                    status,
                    probe.rank if status == "rank" else 0,
                    score,
                    int(probe.cut),
                    "|".join(verdict.options),
                    verdict.got,
                    keys,
                )
            )
    return rows


def run_paragraph(config: SimConfig, p: Paragraph) -> Outcome:
    chunks = make_chunks(p)
    keys = key_line(p, chunks)
    run = simulate_keys(config, keys)
    if (
        config.judge == "required"
        and run.judge_lines == 0
        and judge_expected(p, chunks)
    ):
        raise SimulatorError(
            f"paragraph {p.index}: the judge never ran (judge=required)"
        )
    texts = sentence_texts(run, chunks, len(p.sentences))
    verdicts = [classify_sentence(text, s) for text, s in zip(texts, p.sentences)]
    probes = measure_probes(config, p, chunks, keys, verdicts)
    rows = build_rows(p, keys, verdicts, probes)
    return Outcome(p, keys, run.final, run.composing, tuple(rows))


def apply_checks(config: SimConfig, outcomes: list[Outcome]) -> list[Outcome]:
    """--check-preedit: one --simulate-file batch over every key line. Its committed text must
    equal the verbose run's, which also cross-checks the two output formats."""
    batch = simulate_batch(
        config, [o.keys for o in outcomes], check_preedit=True, timing=True
    )
    if config.judge == "required" and not batch.judge_n:
        raise SimulatorError(
            "the judge did not run in the --check-preedit batch (judge=required)"
        )
    checked = []
    for o, row in zip(outcomes, batch.rows):
        if (row.committed, row.composing) != (o.committed, o.composing):
            raise SimulatorError(
                f"paragraph {o.paragraph.index}: --simulate and --simulate-file committed different text"
            )
        checked.append(
            Outcome(o.paragraph, o.keys, o.committed, o.composing, o.rows, row.verdict)
        )
    return checked


def ensure_outside_repo(path: Path) -> None:
    """Results never go into the checkout (a clean would delete them, a commit could pick them up)."""
    if path.resolve().is_relative_to(REPO_ROOT.resolve()):
        raise OSError(f"SHIZUKU_DOGFOOD_DIR must be outside the repository, got {path}")


def git_state(root: Path) -> tuple[str, bool]:
    """(short commit, whether the code the binary is built from has uncommitted changes).
    Without git the run is named nogit and counts as clean; the warning says so."""

    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            encoding="utf-8",
            check=True,
        )
        return done.stdout.strip()

    try:
        return git("rev-parse", "--short", "HEAD"), bool(
            git("status", "--porcelain", "--", *SOURCE_PATHS)
        )
    except (OSError, subprocess.CalledProcessError) as err:
        log.warning(
            "git state unavailable (%s); the run is named nogit and counts as clean",
            err,
        )
        return "nogit", False


def choose_baseline(against: str | None, runs_dir: Path) -> Baseline | None:
    """The run to compare with, read before anything is typed or written. A run asked for with
    --against must be readable (an error, before the paragraphs are typed). The previous run is
    only a convenience: when it cannot be read it is skipped with a warning, so one damaged old
    run cannot keep a new run from being saved."""
    if against:
        return runstore.read_baseline(runstore.resolve_run(against, runs_dir))
    path = runstore.previous_run(runs_dir)
    if path is None:
        return None
    try:
        return runstore.read_baseline(path)
    except (OSError, KeyError, ValueError) as err:
        log.warning(
            "previous run %s cannot be read (%s); this run is not compared with it",
            path.name,
            err,
        )
        return None


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Type paragraphs through the Shizuku simulator and score them."
    )
    ap.add_argument(
        "input",
        nargs="?",
        default=str(DEFAULT_INPUT),
        help="input TSV (default: seed.tsv)",
    )
    ap.add_argument("--judge", choices=("required", "off"), default="required")
    ap.add_argument(
        "--check-preedit",
        action="store_true",
        help="also run the WYSIWYG check on every paragraph",
    )
    ap.add_argument(
        "--against",
        help="compare with this run (path or name) instead of the previous one",
    )
    ap.add_argument(
        "--show", type=int, default=20, help="most fixed/broken clauses to list"
    )
    ap.add_argument(
        "--print-keys",
        action="store_true",
        help="print each key line and stop (no simulator)",
    )
    return ap.parse_args(argv)


def run_all(
    config: SimConfig, paragraphs: list[Paragraph], check_preedit: bool
) -> list[Outcome]:
    outcomes = []
    for p in paragraphs:
        started = time.monotonic()
        outcomes.append(run_paragraph(config, p))
        log.info(
            "paragraph %d/%d  %.1fs",
            p.index,
            len(paragraphs),
            time.monotonic() - started,
        )
    return apply_checks(config, outcomes) if check_preedit else outcomes


def execute(
    args: argparse.Namespace, input_bytes: bytes, paragraphs: list[Paragraph]
) -> None:
    runs_dir = runstore.dogfood_dir(os.environ) / "runs"
    ensure_outside_repo(runs_dir)
    baseline = choose_baseline(args.against, runs_dir)
    config = make_config(args.judge, os.environ, REPO_ROOT)
    preflight(config)
    outcomes = run_all(config, paragraphs, args.check_preedit)
    commit, dirty = git_state(REPO_ROOT)
    items = summary_items(config, args, outcomes, commit, dirty, input_bytes)
    run_dir = runstore.create_run_dir(runs_dir, commit)
    write_run(run_dir, outcomes, items)
    rows = [r for o in outcomes for r in o.rows]
    print("\n".join(report_lines(run_dir, items, rows, baseline, args.show)))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    args = parse_args(argv)
    try:
        input_bytes = Path(args.input).read_bytes()
        paragraphs = parse_input(input_bytes.decode("utf-8"))
        if args.print_keys:
            print(
                "\n".join(
                    f"{p.index}\t{key_line(p, make_chunks(p))}" for p in paragraphs
                )
            )
            return 0
        execute(args, input_bytes, paragraphs)
    except (InputError, SimulatorError, OSError, KeyError, ValueError) as err:
        log.error("dogfood: %s", err)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
