"""run.py end to end against the fake binary, and the pure pieces it is made of."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import run
import runstore
from simulator import SimulatorError, Step, VerboseRun
from testkit import TWO_CLAUSES, clauses_of, run_dirs, write_input
from typing_plan import Chunk


def step(token: str, committed: str) -> Step:
    return Step(token, "", committed, False, ())


def test_the_text_of_each_enter_is_added_to_its_sentence() -> None:
    chunks = (Chunk(0, 0, 2), Chunk(0, 2, 5), Chunk(1, 0, 2))
    steps = (
        step("a", ""),
        step("<enter>", "い"),
        step("<enter>", "いう、え。"),
        step("<enter>", "いう、え。お。"),
    )
    run_ = VerboseRun(steps, "いう、え。お。", "", False, False)
    assert run.sentence_texts(run_, chunks, 2) == ["いう、え。", "お。"]


def test_text_that_changes_other_than_by_appending_is_refused() -> None:
    run_ = VerboseRun(
        (step("<enter>", "あ"), step("<enter>", "い")), "い", "", False, False
    )
    with pytest.raises(SimulatorError, match="appending"):
        run.sentence_texts(run_, (Chunk(0, 0, 1), Chunk(0, 1, 2)), 1)


def test_a_run_writes_its_files_once_everything_succeeded_and_prints_the_totals(
    fake: SimpleNamespace,
    input_file: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FAKE_CANDS", "zzz|あ。|yyy"
    )  # the gold clause of the first paragraph is candidate 2
    assert run.main([input_file]) == 0
    (name,) = run_dirs(fake)
    assert name.endswith("-001")
    assert sorted(p.name for p in (fake.runs / name).iterdir()) == [
        "clauses.tsv",
        "paragraphs.tsv",
        "summary.tsv",
    ]
    rows = runstore.read_clauses(fake.runs / name / "clauses.tsv")
    first = rows[0]
    assert (
        first.para,
        first.sent,
        first.clause,
        first.status,
        first.rank,
        first.score,
    ) == (1, 1, 1, "rank", 2, 2)
    assert {r.status for r in rows[1:]} == {"retype"}
    out = capsys.readouterr().out
    assert (
        "paragraphs 2  clauses 4  mismatched 4" in out and "previous run: none" in out
    )


def test_the_run_records_the_binary_and_what_differs_from_the_previous_run(
    fake: SimpleNamespace, input_file: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run.main([input_file]) == 0
    assert run.main([input_file, "--judge", "off"]) == 0
    summary = runstore.read_summary(fake.runs / run_dirs(fake)[0] / "summary.tsv")
    assert summary["binary"] == str(fake.binary.resolve()) and summary["binary_built"]
    out = capsys.readouterr().out
    assert (
        f"binary {fake.binary.resolve()}" in out
        and "(that run had judge required)" in out
    )


def test_the_second_run_is_compared_with_the_first_by_key_line(
    fake: SimpleNamespace,
    input_file: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run.main([input_file]) == 0
    monkeypatch.setenv("FAKE_CANDS", "zzz|あ。|yyy")
    capsys.readouterr()
    assert run.main([input_file]) == 0
    assert len(run_dirs(fake)) == 2 and run_dirs(fake)[1].endswith("-002")
    out = capsys.readouterr().out
    assert (
        "previous run:" in out
        and "compared clauses: 4" in out
        and "cheaper 1" in out
        and "new 0" in out
    )


def test_a_missing_judge_directory_stops_before_anything_is_written(
    fake: SimpleNamespace, input_file: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SHIZUKU_JUDGE_DIR")
    assert run.main([input_file]) == 2
    assert not fake.data.exists()
    assert fake.calls() == []


def test_a_judge_that_never_ran_stops_before_anything_is_written(
    fake: SimpleNamespace, input_file: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MODE", "no_judge")
    assert run.main([input_file]) == 2
    assert not fake.data.exists()


def test_with_the_judge_off_the_judge_is_not_needed(
    fake: SimpleNamespace, input_file: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MODE", "no_judge")
    monkeypatch.delenv("SHIZUKU_JUDGE_DIR")
    assert run.main([input_file, "--judge", "off"]) == 0
    assert len(run_dirs(fake)) == 1


def test_a_simulator_that_prints_a_line_too_few_stops_the_run(
    fake: SimpleNamespace, input_file: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MODE", "drop_line")
    assert run.main([input_file, "--judge", "off"]) == 2
    assert not fake.data.exists()


def test_check_preedit_records_a_verdict_per_paragraph(
    fake: SimpleNamespace, input_file: str
) -> None:
    assert run.main([input_file, "--check-preedit"]) == 0
    (name,) = run_dirs(fake)
    assert [
        r["check"] for r in runstore.read_table(fake.runs / name / "paragraphs.tsv")
    ] == ["", ""]
    assert any(
        c["argv"][0] == "--simulate-file" and c["argv"][-1] == "--check-preedit"
        for c in fake.calls()
    )


def test_a_malformed_input_stops_before_the_binary_is_touched(
    fake: SimpleNamespace, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.tsv"
    bad.write_text("日常\t基本\twhole\t0\tあ、い。\tア|。\n", encoding="utf-8")
    assert run.main([str(bad)]) == 2
    assert fake.calls() == []


def test_print_keys_needs_no_binary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    input_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SHIZUKU_BIN", raising=False)
    assert run.main([input_file, "--print-keys"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "1\t<live>a.<enter>"


def test_results_are_never_written_inside_the_repository_and_the_check_comes_first(
    fake: SimpleNamespace, input_file: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "SHIZUKU_DOGFOOD_DIR", str(run.REPO_ROOT / "tools" / "dogfood" / "results")
    )
    assert run.main([input_file]) == 2
    assert not (run.REPO_ROOT / "tools" / "dogfood" / "results").exists()
    assert fake.calls() == []  # refused before any paragraph was typed


def test_a_space_that_opens_no_list_is_nolist_not_retype_and_costs_the_same(
    fake: SimpleNamespace,
    input_file: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        run.main([input_file]) == 0
    )  # the fake opens no list unless FAKE_CANDS is set
    no_list = clauses_of(fake)
    assert {r.status for r in no_list} == {"nolist"}
    out = capsys.readouterr().out
    assert "retype 0  nolist 4" in out
    summary = runstore.read_summary(fake.runs / run_dirs(fake)[0] / "summary.tsv")
    assert (summary["status_nolist"], summary["status_retype"]) == ("4", "0")

    monkeypatch.setenv("FAKE_CANDS", "zzz|yyy")  # a list without the gold
    assert run.main([input_file]) == 0
    retyped = runstore.read_clauses(fake.runs / run_dirs(fake)[1] / "clauses.tsv")
    assert {r.status for r in retyped} == {"retype"}
    assert [r.score for r in retyped] == [r.score for r in no_list]


def test_a_clause_that_starts_inside_a_chunk_is_marked_cut_and_counted(
    fake: SimpleNamespace,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_CANDS", "zzz|yyy")
    assert run.main([write_input(tmp_path, TWO_CLAUSES)]) == 0
    assert [(r.para, r.clause, r.cut) for r in clauses_of(fake)] == [
        (1, 1, 0),
        (1, 2, 1),
        (2, 1, 0),
        (2, 2, 0),
    ]
    summary = runstore.read_summary(fake.runs / run_dirs(fake)[0] / "summary.tsv")
    assert summary["cut_queries"] == "1"
    assert "cut a chunk (their rank is an estimate): 1" in capsys.readouterr().out


def test_a_clause_that_is_right_runs_no_query_so_it_has_no_cut_mark(
    fake: SimpleNamespace, tmp_path: Path
) -> None:
    # the fake commits the typed keys, so a gold that starts with the ASCII letter is right
    assert (
        run.main(
            [write_input(tmp_path, "日常\t基本\twhole\t0\ta、い。\tア|、|イ|。\n")]
        )
        == 0
    )
    assert [(r.clause, r.status, r.cut) for r in clauses_of(fake)] == [
        (1, "match", 0),
        (2, "nolist", 1),
    ]
