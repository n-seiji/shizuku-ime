"""--check-preedit: what run.apply_checks accepts and refuses."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import run
from reporting import Outcome
from simulator import BatchRun, FileRow, SimConfig, SimulatorError
from typing_plan import parse_input


def outcome(committed: str = "あ。", composing: str = "") -> Outcome:
    (p,) = parse_input("日常\t基本\twhole\t0\tあ。\tア|。\n")
    return Outcome(p, "<live>a.<enter>", committed, composing, ())


def config(judge: str) -> SimConfig:
    return SimConfig(Path("shizuku"), Path("dictionary"), None, judge)


def test_the_check_batch_must_commit_what_the_verbose_run_committed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = BatchRun((FileRow("", "あ。", ""),), 1)
    monkeypatch.setattr(run, "simulate_batch", lambda *a, **k: batch)
    (checked,) = run.apply_checks(config("required"), [outcome()])
    assert checked.check == "" and checked.committed == "あ。"


@pytest.mark.parametrize("row", [FileRow("", "い。", ""), FileRow("", "あ。", "x")])
def test_a_batch_that_committed_other_text_stops_the_run(
    monkeypatch: pytest.MonkeyPatch, row: FileRow
) -> None:
    monkeypatch.setattr(run, "simulate_batch", lambda *a, **k: BatchRun((row,), 1))
    with pytest.raises(
        SimulatorError,
        match="paragraph 1: --simulate and --simulate-file committed different text",
    ):
        run.apply_checks(config("required"), [outcome()])


def test_the_preedit_verdict_of_the_batch_is_recorded_on_its_paragraph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run,
        "simulate_batch",
        lambda *a, **k: BatchRun((FileRow("WYSI", "あ。", ""),), 1),
    )
    (checked,) = run.apply_checks(config("required"), [outcome()])
    assert checked.check == "WYSI"


@pytest.mark.parametrize(
    "judge, judge_n, fails",
    [
        ("required", 0, True),
        ("required", None, True),
        ("required", 2, False),
        ("off", 0, False),
    ],
)
def test_a_check_batch_without_judge_lines_fails_only_when_the_judge_is_required(
    monkeypatch: pytest.MonkeyPatch, judge: str, judge_n: int | None, fails: bool
) -> None:
    monkeypatch.setattr(
        run,
        "simulate_batch",
        lambda *a, **k: BatchRun((FileRow("", "あ。", ""),), judge_n),
    )
    if fails:
        with pytest.raises(
            SimulatorError, match="judge did not run in the --check-preedit batch"
        ):
            run.apply_checks(config(judge), [outcome()])
    else:
        assert len(run.apply_checks(config(judge), [outcome()])) == 1


def test_a_check_batch_that_disagrees_with_the_verbose_run_writes_nothing(
    fake: SimpleNamespace, input_file: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MODE", "file_differs")
    assert run.main([input_file, "--check-preedit"]) == 2
    assert not fake.data.exists()
