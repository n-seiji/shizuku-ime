"""A stand-in for the shizuku binary, so the wrapper and run.py can be tested without the real one.

The fake prints what the real simulator prints (src/simulate.rs) but its "conversion" just
commits the typed keys. Behaviour comes from the FAKE_* environment variables:
  FAKE_MODE   ok | no_judge | drop_line | judge_lost | dictionary_lost | file_differs (the judge also
              stays silent when SHIZUKU_JUDGE_DIR is not set, as the real one does; file_differs makes
              --simulate-file commit different text from --simulate)
  FAKE_CANDS  candidates listed after <space>, separated by |; unset or empty: Space opens no list
              (the typed text is not converted, 、。？！ are typed as the marks)
  FAKE_LOG    a file that receives one JSON line per call (argv and the SHIZUKU_* variables)
"""

import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from testkit import INPUT

FAKE_SOURCE = """#!{python}
import json, os, re, sys

args = sys.argv[1:]
mode = os.environ.get("FAKE_MODE", "ok")
judge_on = "SHIZUKU_JUDGE_DIR" in os.environ and mode != "no_judge"
log = os.environ.get("FAKE_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({{"argv": args, "env": sorted(k for k in os.environ if k.startswith("SHIZUKU_"))}}) + "\\n")
if mode == "judge_lost":
    sys.stderr.write("2026-11-15 12:00:00.000 shizuku[1:2] judge: not configured; conversion keeps the engine order\\n")
if mode == "dictionary_lost":
    sys.stderr.write("2026-11-15 12:00:00.000 shizuku[1:2] dictionary unavailable; conversion falls back to kana\\n")

MARKS = {{",": "、", ".": "。", "?": "？", "!": "！"}}

def steps(keys):
    return re.findall(r"<[^<>]*>|.", keys)

def play(keys):
    marked = committed = ""
    lines = []
    judged = False
    for token in steps(keys):
        phase = "Empty"
        cands = None
        if token == "<enter>":
            committed += marked if marked else "\\n"
            marked = ""
        elif token == "<space>":
            phase = "Converting {{ selected: 0, window: false }}"
            cands = os.environ.get("FAKE_CANDS", "")
        elif not token.startswith("<"):
            marked += MARKS.get(token, token)
            phase = "Composing"
        lines.append("%9s  %-34s marked=%s  committed=%s" % (token, phase, json.dumps(marked, ensure_ascii=False), json.dumps(committed, ensure_ascii=False)))
        if judge_on and not judged and phase == "Composing":
            lines.append("%9s  judge 1.0 ms" % "")
            judged = True
        if cands:
            lines.append("%9s  %s" % ("", " ".join("%d.%s%s" % (i + 1, c, "*" if i == 0 else "") for i, c in enumerate(cands.split("|")))))
    if mode == "drop_line":
        del lines[0]
    return lines, committed, marked, judged

if args[0] == "--simulate":
    lines, committed, marked, _ = play(args[1])
    print("\\n".join(lines))
    print("final: " + json.dumps(committed, ensure_ascii=False))
    if marked:
        print("still composing: " + json.dumps(marked, ensure_ascii=False))
elif args[0] == "--simulate-file":
    count = 0
    for line in open(args[1], encoding="utf-8").read().splitlines():
        _, committed, marked, judged = play(line)
        count += judged
        if mode == "file_differs":
            committed += "x"
        print("     %s  =>  %s" % (line, json.dumps(committed, ensure_ascii=False)))
    if "SHIZUKU_SIM_TIMING" in os.environ:
        print("judge: n=%d median 1.0 ms p90 1.0 ms max 1.0 ms" % count)
        print("timing: keys=0")
else:
    sys.exit(3)
"""


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Tests that run the fake binary are integration tests; the rest are unit tests (see pytest.ini)."""
    for item in items:
        item.add_marker(
            pytest.mark.integration if "fake" in item.fixturenames else pytest.mark.unit
        )


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A fake binary, dictionary and judge directory, wired through the environment."""
    binary = tmp_path / "shizuku"
    binary.write_text(FAKE_SOURCE.format(python=sys.executable), encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    dictionary = tmp_path / "dictionary"
    dictionary.mkdir()
    (dictionary / "louds").write_text("x")
    judge = tmp_path / "judge"
    judge.mkdir()
    for name in ("model_q8_0.gguf", "tokenizer.json"):
        (judge / name).write_text("x")
    log = tmp_path / "calls.jsonl"
    data = tmp_path / "data"
    for key in [k for k in os.environ if k.startswith(("SHIZUKU_", "FAKE_"))]:
        monkeypatch.delenv(key)
    for key, value in {
        "SHIZUKU_BIN": binary,
        "SHIZUKU_DICTIONARY": dictionary,
        "SHIZUKU_JUDGE_DIR": judge,
        "SHIZUKU_DOGFOOD_DIR": data,
        "FAKE_LOG": log,
    }.items():
        monkeypatch.setenv(key, str(value))

    def calls() -> list[dict[str, object]]:
        return (
            [json.loads(line) for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )

    return SimpleNamespace(
        binary=binary,
        dictionary=dictionary,
        judge=judge,
        data=data,
        runs=data / "runs",
        calls=calls,
        tmp=tmp_path,
    )


@pytest.fixture
def input_file(tmp_path: Path) -> str:
    """The two-paragraph input the run.py tests type."""
    path = tmp_path / "input.tsv"
    path.write_text(INPUT, encoding="utf-8")
    return str(path)
