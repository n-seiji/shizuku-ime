"""Run files, comparison of runs, cmp_runs.py and leakcheck.py."""

from pathlib import Path

import cmp_runs
import leakcheck
import pytest
import runstore
from runstore import ClauseRow


def row(
    clause: int,
    score: int,
    got: str = "x",
    keys: str = "<live>a<enter>",
    want: str = "あ。",
) -> ClauseRow:
    status = "match" if score == 0 else "retype"
    return ClauseRow(
        1, 1, clause, "whole", "日常", "基本", status, 0, score, 0, want, got, keys
    )


def write_run(path: Path, rows: list[ClauseRow]) -> None:
    path.mkdir(parents=True)
    runstore.write_table(
        path / "clauses.tsv", runstore.CLAUSE_COLUMNS, [tuple(r) for r in rows]
    )
    runstore.write_summary(path / "summary.tsv", [("input", "seed.tsv")])


def touch_clauses(run_dir: Path) -> None:
    runstore.write_table(run_dir / "clauses.tsv", runstore.CLAUSE_COLUMNS, [])


def test_text_with_newlines_and_tabs_survives_a_round_trip(tmp_path: Path) -> None:
    original = [row(1, 3, got="ab\n\tc")]
    write_run(tmp_path / "r", original)
    assert runstore.read_clauses(tmp_path / "r" / "clauses.tsv") == original


def test_run_numbers_count_across_commits_and_the_previous_run_is_the_highest(
    tmp_path: Path,
) -> None:
    runs = tmp_path / "runs"
    first = runstore.create_run_dir(runs, "aaaaaaa")
    touch_clauses(first)
    second = runstore.create_run_dir(runs, "bbbbbbb")
    touch_clauses(second)
    third = runstore.create_run_dir(
        runs, "aaaaaaa"
    )  # not written yet: not a complete run
    assert [p.name for p in (first, second, third)] == [
        "aaaaaaa-001",
        "bbbbbbb-002",
        "aaaaaaa-003",
    ]
    assert runstore.previous_run(runs) == second
    assert runstore.resolve_run("aaaaaaa-001", runs) == first


def test_clauses_are_matched_by_key_line_and_position_not_by_text() -> None:
    old = [row(1, 5, got="a"), row(2, 0), row(3, 4, got="p"), row(4, 2), row(5, 1)]
    new = [row(1, 0, got="b"), row(2, 3), row(3, 1, got="q"), row(4, 6), row(6, 2)]
    c = runstore.compare(old, new)
    assert (len(c.fixed), len(c.broken), len(c.cheaper), len(c.costlier)) == (
        1,
        1,
        1,
        1,
    )
    assert [r.clause for r in c.added] == [6] and [r.clause for r in c.removed] == [5]
    assert (c.shared, c.old_score, c.new_score) == (4, 11, 10)
    assert "score 11 -> 10 (-1)" in runstore.format_comparison(c)[0]


def test_a_clause_that_moves_between_match_and_notation_is_listed_though_its_score_stays_zero() -> (
    None
):
    drifted = row(1, 0, got="10時")._replace(status="notation")
    c = runstore.compare([row(1, 0, got="十時")], [drifted, row(2, 0)])
    assert (len(c.drifted), len(c.fixed), len(c.broken)) == (1, 0, 0)
    report = "\n".join(runstore.format_comparison(c))
    assert "match<->notation 1" in report and "now '10時' (notation, score 0)" in report


def test_a_clause_of_another_key_line_is_new_not_fixed() -> None:
    c = runstore.compare(
        [row(1, 5, keys="<live>a<enter>")], [row(1, 0, keys="<live>b<enter>")]
    )
    assert (c.shared, len(c.fixed), len(c.added), len(c.removed)) == (0, 0, 1, 1)


def test_cmp_runs_prints_the_fixed_and_broken_clauses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SHIZUKU_DOGFOOD_DIR", str(tmp_path))
    write_run(tmp_path / "runs" / "aaaaaaa-001", [row(1, 5, got="old"), row(2, 0)])
    write_run(
        tmp_path / "runs" / "bbbbbbb-002", [row(1, 0, got="new"), row(2, 3, got="bad")]
    )
    assert cmp_runs.main(["aaaaaaa-001", "bbbbbbb-002"]) == 0
    out = capsys.readouterr().out
    assert "fixed 1  broken 1" in out and "was 'old'" in out and "now 'bad'" in out
    assert cmp_runs.main(["aaaaaaa-001", "nowhere-009"]) == 2


def test_leakcheck_without_private_lines_says_so_and_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SHIZUKU_DOGFOOD_DIR", str(tmp_path))
    target = tmp_path / "report.md"
    target.write_text("anything", encoding="utf-8")
    assert leakcheck.main([str(target)]) == 0
    assert "nothing to check against" in capsys.readouterr().out


def test_leakcheck_finds_a_quoted_fragment_without_printing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SHIZUKU_DOGFOOD_DIR", str(tmp_path))
    (tmp_path / "private").mkdir()
    secret = "田中さんに明日の飲み会の場所を伝えておく"
    (tmp_path / "private" / "real_lines.txt").write_text(
        f"短い\n{secret}\n", encoding="utf-8"
    )
    leaking, clean, allowed = tmp_path / "a.md", tmp_path / "b.md", tmp_path / "c.md"
    leaking.write_text(f"メモ: {secret[3:14]} など", encoding="utf-8")
    clean.write_text("明日の会議は十時からです。", encoding="utf-8")
    allowed.write_text(f"メモ: {secret[3:14]} など", encoding="utf-8")
    assert leakcheck.main([str(clean)]) == 0
    capsys.readouterr()
    assert leakcheck.main([str(leaking)]) == 1
    out = capsys.readouterr().out
    assert "private line 2" in out and secret[3:10] not in out
    (tmp_path / "ok.txt").write_text(secret[3:14] + "\n", encoding="utf-8")
    assert leakcheck.main(["--allow", str(tmp_path / "ok.txt"), str(allowed)]) == 0


def test_leakcheck_matches_typed_keys_of_private_paragraphs_as_a_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SHIZUKU_DOGFOOD_DIR", str(tmp_path))
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "real_lines.txt").write_text(
        "あいうえおかきくけこ\n", encoding="utf-8"
    )
    table = tmp_path / "paragraphs.tsv"
    runstore.write_table(
        table,
        runstore.PARAGRAPH_COLUMNS,
        [(1, "whole", "", "x", "<live>asitanokaigiha<enter>")],
    )
    target = tmp_path / "report.md"
    target.write_text("see asitanokaigiha here", encoding="utf-8")
    assert leakcheck.main(["--private-keys", str(table), str(target)]) == 1
    assert "1 typed key line(s)" in capsys.readouterr().out


def test_leakcheck_with_an_explicit_private_file_that_is_missing_fails_not_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SHIZUKU_DOGFOOD_DIR", str(tmp_path))
    target = tmp_path / "report.md"
    target.write_text("anything", encoding="utf-8")
    assert leakcheck.main(["--private", str(tmp_path / "typo.txt"), str(target)]) == 2
    assert "passed" not in capsys.readouterr().out


def test_leakcheck_with_an_explicit_private_file_checks_against_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SHIZUKU_DOGFOOD_DIR", str(tmp_path / "elsewhere"))
    secret = tmp_path / "lines.txt"
    secret.write_text("田中さんに明日の飲み会の場所を伝えておく\n", encoding="utf-8")
    leaking = tmp_path / "a.md"
    leaking.write_text("田中さんに明日の飲み会の場所を伝えておく", encoding="utf-8")
    assert leakcheck.main(["--private", str(secret), str(leaking)]) == 1
    assert "private line 1" in capsys.readouterr().out


@pytest.mark.parametrize("option", ["--private-keys", "--public", "--allow"])
def test_leakcheck_with_any_other_named_file_missing_fails_instead_of_skipping_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, option: str
) -> None:
    monkeypatch.setenv("SHIZUKU_DOGFOOD_DIR", str(tmp_path))
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "real_lines.txt").write_text(
        "あいうえおかきくけこ\n", encoding="utf-8"
    )
    target = tmp_path / "report.md"
    target.write_text("anything", encoding="utf-8")
    assert leakcheck.main([option, str(tmp_path / "typo"), str(target)]) == 2


def test_leakcheck_with_a_target_that_does_not_exist_fails_even_without_private_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHIZUKU_DOGFOOD_DIR", str(tmp_path))
    assert leakcheck.main([str(tmp_path / "typo.md")]) == 2


def test_the_cut_column_round_trips_and_an_old_file_without_it_reads_as_not_cut(
    tmp_path: Path,
) -> None:
    cut = row(1, 3)._replace(cut=1)
    write_run(tmp_path / "new", [cut])
    assert runstore.read_clauses(tmp_path / "new" / "clauses.tsv")[0].cut == 1
    columns = tuple(c for c in runstore.CLAUSE_COLUMNS if c != "cut")
    old = [v for c, v in zip(runstore.CLAUSE_COLUMNS, tuple(cut)) if c != "cut"]
    (tmp_path / "old").mkdir()
    runstore.write_table(tmp_path / "old" / "clauses.tsv", columns, [tuple(old)])
    assert runstore.read_clauses(tmp_path / "old" / "clauses.tsv")[0].cut == 0


def test_an_empty_clauses_file_is_a_value_error_not_an_index_error(
    tmp_path: Path,
) -> None:
    (tmp_path / "clauses.tsv").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="is empty"):
        runstore.read_clauses(tmp_path / "clauses.tsv")
