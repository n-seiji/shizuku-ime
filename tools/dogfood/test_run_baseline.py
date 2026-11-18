"""Which earlier run a new run is compared with, and what happens when it cannot be read."""

import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import run
import runstore
from testkit import run_dirs


def old_format_run(path: Path, keys: str) -> None:
    """A run written before the `cut` column existed."""
    columns = [c for c in runstore.CLAUSE_COLUMNS if c != "cut"]
    row = (
        "1",
        "1",
        "1",
        "whole",
        "日常",
        "基本",
        "retype",
        "0",
        "9",
        "あ。",
        "x",
        keys,
    )
    path.mkdir(parents=True)
    runstore.write_table(path / "clauses.tsv", tuple(columns), [row])
    runstore.write_summary(
        path / "summary.tsv", [("input", "input.tsv"), ("judge", "required")]
    )


def test_a_run_from_before_the_cut_column_is_still_a_baseline(
    fake: SimpleNamespace, input_file: str, capsys: pytest.CaptureFixture[str]
) -> None:
    old_format_run(fake.runs / "aaaaaaa-001", "<live>a.<enter>")
    assert run.main([input_file]) == 0
    out = capsys.readouterr().out
    assert "previous run: aaaaaaa-001" in out and "compared clauses: 1" in out


def damaged_run(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "clauses.tsv").write_text("para\tsent\n1\t1\n", encoding="utf-8")
    (path / "summary.tsv").write_text("input\tx\n", encoding="utf-8")


def test_an_unreadable_previous_run_is_a_warning_and_the_new_run_is_still_saved(
    fake: SimpleNamespace,
    input_file: str,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    damaged_run(fake.runs / "aaaaaaa-001")
    with caplog.at_level(logging.WARNING, logger="dogfood"):
        assert run.main([input_file]) == 0
    assert run_dirs(fake)[-1].endswith("-002")
    assert (fake.runs / run_dirs(fake)[-1] / "clauses.tsv").is_file()
    assert "aaaaaaa-001 cannot be read" in caplog.text
    assert "previous run: none" in capsys.readouterr().out


@pytest.mark.parametrize("against", ["aaaaaaa-001", "nowhere-009"])
def test_a_run_asked_for_with_against_that_cannot_be_read_fails_before_anything_is_typed(
    fake: SimpleNamespace, input_file: str, against: str
) -> None:
    damaged_run(fake.runs / "aaaaaaa-001")
    assert run.main([input_file, "--against", against]) == 2
    assert fake.calls() == []
    assert run_dirs(fake) == ["aaaaaaa-001"]


@pytest.mark.parametrize(
    "error", [FileNotFoundError("git"), subprocess.CalledProcessError(128, "git")]
)
def test_a_failing_git_is_named_nogit_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    def failing(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(run.subprocess, "run", failing)
    with caplog.at_level(logging.WARNING, logger="dogfood"):
        assert run.git_state(Path(".")) == ("nogit", False)
    assert "git state unavailable" in caplog.text
