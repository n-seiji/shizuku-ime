"""The only place that runs the shizuku binary, and the parsers for what it prints.

Running `shizuku` without a flag, or with one it does not know, starts the real input method
and takes over the user's keyboard. `_invoke` therefore builds the command line itself: the
flag is `--simulate` or `--simulate-file` (plus an optional `--check-preedit`), the argument
cannot look like a flag, and nothing else can be passed.

Output formats (src/simulate.rs):
  --simulate KEYS      one line per key step (`label  phase  marked="..."  committed="..."`),
                       `judge N ms` and candidate-list lines under a step, then `final: "..."`.
  --simulate-file F    one line per scenario (`verdict KEYS  =>  "committed"`); with
                       SHIZUKU_SIM_TIMING set, `judge: n=` and `timing:` summary lines follow.
Strings are Rust `{:?}` strings. A parsed output whose line count does not match the keys that
were sent is an error, never a silent shift.
"""

from __future__ import annotations

import ast
import logging
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

log = logging.getLogger("dogfood")

ALLOWED_FLAGS = ("--simulate", "--simulate-file")
CHECK_PREEDIT = "--check-preedit"
TIMEOUT_SECONDS = 900
JUDGE_FILES = ("model_q8_0.gguf", "tokenizer.json")
PREFLIGHT_KEYS = "<live>kareno<enter>"
_QUOTED = r'"(?:[^"\\]|\\.)*"'
_PHASE = r"[A-Z]\w*(?:\([^)]*\)|\s\{[^}]*\})?"
_STEP = re.compile(
    rf"^.*?  (?P<phase>{_PHASE})\s+marked=(?P<marked>{_QUOTED})(?: panel@\d+)?  committed=(?P<committed>{_QUOTED})$"
)
_JUDGE_MS = re.compile(r"^\s+judge \d+(?:\.\d+)? ms$")
_SELECTED = re.compile(r"Converting \{ selected: (\d+)")
_UNICODE_ESCAPE = re.compile(r"\\(?:u\{([0-9a-fA-F]{1,6})\}|[\s\S])")
_FILE_SHOWN = re.compile(
    rf"^(?P<shown>{_QUOTED})(?: \+composing (?P<marked>{_QUOTED}))?(?P<rest>.*)$"
)
_SUMMARY_JUDGE = re.compile(r"^judge: n=(\d+)")
_DICTIONARY_LOST = "dictionary unavailable"
_JUDGE_LOST = re.compile(
    r"judge: (?:not configured|model unavailable|model load panicked|unavailable"
    r"|preload thread failed|scoring failed)"
)


class SimulatorError(RuntimeError):
    """The simulator could not be run, or what it printed cannot be trusted."""


@dataclass(frozen=True)
class SimConfig:
    binary: Path
    dictionary: Path
    judge_dir: Path | None  # None when judge == "off"
    judge: str  # "required" | "off"


@dataclass(frozen=True)
class Step:
    token: str
    marked: str
    committed: str
    judge_ran: bool
    candidates: tuple[str, ...]  # empty unless the step opened a candidate list
    phase: str = (
        ""  # as printed: Empty, Composing, Converting { selected: 0, window: false }, ...
    )

    @property
    def listed(self) -> bool:
        """Whether the step shows a candidate list (Space on English text commits it without one)."""
        return bool(self.candidates)


@dataclass(frozen=True)
class VerboseRun:
    steps: tuple[Step, ...]
    final: str
    composing: str
    stale: bool
    wysiwyg_broken: bool

    @property
    def judge_lines(self) -> int:
        return sum(step.judge_ran for step in self.steps)


@dataclass(frozen=True)
class FileRow:
    verdict: str  # "" (no expectation) | "STAL" | "WYSI"
    committed: str
    composing: str


@dataclass(frozen=True)
class BatchRun:
    rows: tuple[FileRow, ...]
    judge_n: int | None  # the `judge: n=` summary, None when it was not printed


def make_config(judge: str, environ: Mapping[str, str], repo_root: Path) -> SimConfig:
    """Resolve the binary, dictionary and (when required) judge directory; no fallbacks."""
    if judge not in ("required", "off"):
        raise ValueError(f"judge must be required or off, got {judge!r}")
    binary = Path(
        environ.get("SHIZUKU_BIN") or repo_root / "target" / "release" / "shizuku"
    ).resolve()
    if not (binary.is_file() and os.access(binary, os.X_OK)):
        raise SimulatorError(
            f"binary not found or not executable: {binary} (cargo build --release, or set SHIZUKU_BIN)"
        )
    dictionary_value = environ.get("SHIZUKU_DICTIONARY")
    if not dictionary_value:
        raise SimulatorError(
            "SHIZUKU_DICTIONARY is not set (use the dictionary/ directory)"
        )
    dictionary = Path(dictionary_value).resolve()
    if not dictionary.is_dir() or not any(dictionary.iterdir()):
        raise SimulatorError(f"dictionary directory is missing or empty: {dictionary}")
    judge_dir = None
    if judge == "required":
        judge_value = environ.get("SHIZUKU_JUDGE_DIR")
        if not judge_value:
            raise SimulatorError("SHIZUKU_JUDGE_DIR is not set (judge=required)")
        judge_dir = Path(judge_value).resolve()
        missing = [name for name in JUDGE_FILES if not (judge_dir / name).is_file()]
        if missing:
            raise SimulatorError(
                f"judge directory {judge_dir} lacks {', '.join(missing)} (mise run judge-model)"
            )
    return SimConfig(binary, dictionary, judge_dir, judge)


def build_env(
    config: SimConfig, base: Mapping[str, str], timing: bool
) -> dict[str, str]:
    """The environment of one run: every SHIZUKU_* variable but the two we set is dropped, so a
    stray SHIZUKU_SIM_LEARNING or SHIZUKU_MEMORY_DIR cannot change the result."""
    env = {k: v for k, v in base.items() if not k.startswith("SHIZUKU_")}
    env["SHIZUKU_DICTIONARY"] = str(config.dictionary)
    if config.judge_dir is not None:
        env["SHIZUKU_JUDGE_DIR"] = str(config.judge_dir)
    if timing:
        env["SHIZUKU_SIM_TIMING"] = "1"
    return env


def _check_stderr(config: SimConfig, stderr: str) -> None:
    for line in stderr.splitlines():
        if _DICTIONARY_LOST in line:
            raise SimulatorError(
                "the dictionary could not be opened (see SHIZUKU_DICTIONARY)"
            )
        if config.judge == "required" and _JUDGE_LOST.search(line):
            raise SimulatorError(
                "the judge did not load: " + line.split("]", 1)[-1].strip()
            )


def _invoke(
    config: SimConfig,
    flag: str,
    arg: str,
    check_preedit: bool = False,
    timing: bool = False,
) -> subprocess.CompletedProcess[str]:
    """The single call of the binary. Anything but the two simulate flags is refused."""
    if flag not in ALLOWED_FLAGS:
        raise ValueError(f"flag not allowed: {flag!r}")
    if not arg or arg.startswith("-"):
        raise ValueError(
            "the argument of a simulate flag must be non-empty and must not start with '-'"
        )
    argv = [str(config.binary), flag, arg]
    if check_preedit:
        argv.append(CHECK_PREEDIT)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            encoding="utf-8",
            env=build_env(config, os.environ, timing),
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as err:
        raise SimulatorError(f"simulator timed out after {TIMEOUT_SECONDS}s") from err
    _check_stderr(config, proc.stderr)
    return proc


def split_steps(keys: str) -> list[str]:
    """Key steps as the simulator splits them: `<name>` tokens and single characters."""
    steps: list[str] = []
    i = 0
    while i < len(keys):
        end = keys.find(">", i) if keys[i] == "<" else -1
        if end >= 0:
            steps.append(keys[i : end + 1])
            i = end + 1
        else:
            steps.append(keys[i])
            i += 1
    return steps


def parse_rust_string(literal: str) -> str:
    """A Rust `{:?}` string. `\\u{1b}` is not Python syntax, so it is widened first."""

    def widen(match: re.Match[str]) -> str:
        return f"\\U{int(match.group(1), 16):08x}" if match.group(1) else match.group(0)

    try:
        value = ast.literal_eval(_UNICODE_ESCAPE.sub(widen, literal.strip()))
    except (ValueError, SyntaxError) as err:
        raise SimulatorError("cannot parse a string printed by the simulator") from err
    if not isinstance(value, str):
        raise SimulatorError(
            "the simulator printed a non-string where a string was expected"
        )
    return value


def parse_candidates(line: str, selected: int | None) -> tuple[str, ...]:
    """`1.今日は* 2.強は ...`: cut at the running ` N.` numbers; the `*` of the selected one is
    dropped. A candidate that itself contains ` N.` with the next number would be cut wrongly.
    """
    text = line.strip()
    if not text.startswith("1."):
        raise SimulatorError("a candidate list does not start with 1.")
    items: list[str] = []
    start, n = 2, 1
    while True:
        marker = f" {n + 1}."
        nxt = text.find(marker, start)
        if nxt < 0:
            items.append(text[start:])
            break
        items.append(text[start:nxt])
        start, n = nxt + len(marker), n + 1
    if selected is not None and selected < len(items) and items[selected].endswith("*"):
        items[selected] = items[selected][:-1]
    return tuple(items)


@dataclass(frozen=True)
class _RawStep:
    phase: str
    marked: str
    committed: str
    judge_ran: bool = False
    candidate_line: str | None = None


def _candidates(raw: _RawStep) -> tuple[str, ...]:
    if raw.candidate_line is None:
        return ()
    picked = _SELECTED.search(raw.phase)
    return parse_candidates(raw.candidate_line, int(picked[1]) if picked else None)


def parse_verbose(stdout: str, keys: str) -> VerboseRun:
    """Parse `--simulate KEYS` output; one step must come back for every key step sent."""
    raw: list[_RawStep] = []
    final: str | None = None
    composing, stale, wysiwyg = "", False, False
    for number, line in enumerate(stdout.splitlines(), 1):
        match = _STEP.match(line)
        if match:
            marked, committed = parse_rust_string(match["marked"]), parse_rust_string(
                match["committed"]
            )
            raw.append(_RawStep(match["phase"], marked, committed))
        elif line.startswith("final: "):
            final = parse_rust_string(line[len("final: ") :])
        elif line.startswith("still composing: "):
            composing = parse_rust_string(line[len("still composing: ") :])
        elif line.startswith("STALE marked text after"):
            stale = True
        elif line.startswith("WYSIWYG preedit differs"):
            wysiwyg = True
        elif line[:1].isspace() and raw and _JUDGE_MS.match(line):
            raw[-1] = replace(raw[-1], judge_ran=True)
        elif line[:1].isspace() and raw and line.strip().startswith("1."):
            raw[-1] = replace(raw[-1], candidate_line=line)
        else:
            raise SimulatorError(f"unexpected simulator output at line {number}")
    tokens = split_steps(keys)
    if len(raw) != len(tokens):
        raise SimulatorError(
            f"simulator printed {len(raw)} step lines for {len(tokens)} key steps"
        )
    if final is None or (raw and final != raw[-1].committed):
        raise SimulatorError(
            "the final committed text is missing or disagrees with the last step"
        )
    steps = tuple(
        Step(t, r.marked, r.committed, r.judge_ran, _candidates(r), r.phase)
        for t, r in zip(tokens, raw)
    )
    return VerboseRun(steps, final, composing, stale, wysiwyg)


def parse_file_output(stdout: str, key_lines: list[str]) -> BatchRun:
    """Parse `--simulate-file` output for scenarios that carry no expectation."""
    judge_n: int | None = None
    lines: list[str] = []
    for line in stdout.splitlines():
        summary = _SUMMARY_JUDGE.match(line)
        if summary:
            judge_n = int(summary[1])
        elif not line.startswith(("judge-locked ", "timing: ")):
            lines.append(line)
    if len(lines) != len(key_lines):
        raise SimulatorError(
            f"simulator printed {len(lines)} result lines for {len(key_lines)} scenarios"
        )
    rows: list[FileRow] = []
    for number, (line, keys) in enumerate(zip(lines, key_lines), 1):
        verdict = line[:4]
        head = f"{verdict} {keys}  =>  "
        if verdict not in ("    ", "STAL", "WYSI") or not line.startswith(head):
            raise SimulatorError(
                f"the result line of scenario {number} does not belong to it"
            )
        shown = _FILE_SHOWN.match(line[len(head) :])
        if shown is None or (
            shown["rest"] and not shown["rest"].startswith("   after ")
        ):
            raise SimulatorError(f"cannot parse the result line of scenario {number}")
        marked = parse_rust_string(shown["marked"]) if shown["marked"] else ""
        rows.append(FileRow(verdict.strip(), parse_rust_string(shown["shown"]), marked))
    return BatchRun(tuple(rows), judge_n)


def simulate_keys(
    config: SimConfig, keys: str, check_preedit: bool = False, timing: bool = False
) -> VerboseRun:
    proc = _invoke(config, "--simulate", keys, check_preedit, timing)
    if proc.returncode != 0:
        raise SimulatorError(f"simulator exited with status {proc.returncode}")
    return parse_verbose(proc.stdout, keys)


def simulate_batch(
    config: SimConfig,
    key_lines: list[str],
    check_preedit: bool = False,
    timing: bool = False,
) -> BatchRun:
    if not key_lines or any(
        not k or "\t" in k or "\n" in k or k.startswith("#") for k in key_lines
    ):
        raise ValueError(
            "every scenario must be a non-empty single key line without tabs"
        )
    with tempfile.TemporaryDirectory(prefix="dogfood-") as tmp:
        path = Path(tmp) / "keys.sim"
        path.write_text("\n".join(key_lines) + "\n", encoding="utf-8")
        proc = _invoke(config, "--simulate-file", str(path), check_preedit, timing)
    if proc.returncode not in (0, 1):  # 1 = a --check-preedit scenario failed
        raise SimulatorError(f"simulator exited with status {proc.returncode}")
    return parse_file_output(proc.stdout, key_lines)


def preflight(config: SimConfig) -> int:
    """Run a short key sequence and prove the judge ran (required) or did not (off).
    Returns the number of judged steps."""
    run = simulate_keys(config, PREFLIGHT_KEYS, timing=True)
    if config.judge == "required" and run.judge_lines == 0:
        raise SimulatorError(
            "the judge did not run in the preflight keys (judge=required)"
        )
    if config.judge == "off" and run.judge_lines > 0:
        raise SimulatorError("the judge ran although judge=off")
    log.info("preflight: judge=%s, %d judged steps", config.judge, run.judge_lines)
    return run.judge_lines
