"""The binary wrapper (against the fake binary in conftest.py) and the output parsers."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import simulator
from simulator import (
    SimulatorError,
    make_config,
    parse_candidates,
    parse_file_output,
    parse_rust_string,
    parse_verbose,
    preflight,
    simulate_batch,
    simulate_keys,
    split_steps,
)

REPO = Path(__file__).resolve().parents[2]

REAL_OUTPUT = """   <live>  Empty                              marked=""  committed=""
        k  Empty                              marked="k"  committed=""
        a  Composing                          marked="か"  committed=""
           judge 3.3 ms
  <space>  Converting { selected: 1, window: false } marked="今日は"  committed="\\u{1b}x"
           1.今日は 2.強は* 3.教派
  <enter>  Empty                              marked=""  committed="か"
final: "か"
"""


@pytest.mark.parametrize(
    "literal, text",
    [
        ('"a\\u{1b}b"', "a\x1bb"),
        (
            '"\\\\u{41}"',
            "\\u{41}",
        ),  # an escaped backslash followed by plain text, not an escape
        ('"\\n\\t\\"q\\""', '\n\t"q"'),
        ('"\\u{3042}"', "あ"),
    ],
)
def test_rust_strings_are_read_including_unicode_escapes(
    literal: str, text: str
) -> None:
    assert parse_rust_string(literal) == text


def test_an_unreadable_string_is_an_error_not_a_question_mark() -> None:
    with pytest.raises(SimulatorError):
        parse_rust_string('"unterminated')


def test_candidates_are_cut_at_the_running_numbers_and_the_selected_star_is_dropped() -> (
    None
):
    assert parse_candidates("   1.今日は* 2.強は 3.教派", 0) == (
        "今日は",
        "強は",
        "教派",
    )
    assert parse_candidates("1.a b 2.c* 3.d", 1) == ("a b", "c", "d")


def test_key_steps_are_split_like_the_simulator_does() -> None:
    assert split_steps("<live>ka<enter>") == ["<live>", "k", "a", "<enter>"]
    assert split_steps("a<lt>b") == ["a", "<lt>", "b"]


def test_a_verbose_run_is_parsed_step_by_step() -> None:
    run = parse_verbose(REAL_OUTPUT, "<live>ka<space><enter>")
    assert [s.token for s in run.steps] == ["<live>", "k", "a", "<space>", "<enter>"]
    assert run.judge_lines == 1 and run.final == "か"
    assert run.steps[3].candidates == ("今日は", "強は", "教派")
    assert run.steps[3].committed == "\x1bx"


def test_a_missing_or_extra_line_is_an_error_not_a_shift() -> None:
    lines = REAL_OUTPUT.splitlines()
    without_first = "\n".join(lines[1:]) + "\n"
    with pytest.raises(SimulatorError, match="4 step lines for 5 key steps"):
        parse_verbose(without_first, "<live>ka<space><enter>")
    with pytest.raises(SimulatorError, match="6 step lines"):
        parse_verbose(
            REAL_OUTPUT.replace(
                "final", '  <enter>  Empty  marked=""  committed="か"\nfinal'
            ),
            "<live>ka<space><enter>",
        )
    with pytest.raises(SimulatorError, match="unexpected simulator output"):
        parse_verbose(REAL_OUTPUT + "something else\n", "<live>ka<space><enter>")


def test_file_output_is_matched_to_scenarios_by_count_and_by_keys() -> None:
    out = '     <live>ka<enter>  =>  "か"\nWYSI <live>kb<enter>  =>  "b" +composing "x"   after k\njudge: n=3 median 1.0 ms\ntiming: keys=2\n'
    batch = parse_file_output(out, ["<live>ka<enter>", "<live>kb<enter>"])
    assert [(r.verdict, r.committed, r.composing) for r in batch.rows] == [
        ("", "か", ""),
        ("WYSI", "b", "x"),
    ]
    assert batch.judge_n == 3
    with pytest.raises(SimulatorError, match="1 result lines for 2 scenarios"):
        parse_file_output(
            '     <live>ka<enter>  =>  "か"\n', ["<live>ka<enter>", "<live>kb<enter>"]
        )
    with pytest.raises(SimulatorError, match="does not belong"):
        parse_file_output(out, ["<live>kb<enter>", "<live>ka<enter>"])


def test_the_binary_gets_exactly_one_simulate_flag_and_nothing_else(
    fake: SimpleNamespace,
) -> None:
    config = make_config("required", os.environ, REPO)
    simulate_keys(config, "<live>ka<enter>")
    simulate_batch(config, ["<live>ka<enter>"], check_preedit=True)
    first, second = (c["argv"] for c in fake.calls())
    assert first == ["--simulate", "<live>ka<enter>"]
    assert [second[0], second[2]] == ["--simulate-file", "--check-preedit"] and len(
        second
    ) == 3


@pytest.mark.parametrize(
    "flag, arg",
    [
        ("--kkc-check", "x"),
        ("--version", "x"),
        ("", "x"),
        ("--simulate", "--kkc-check"),
        ("--simulate", ""),
        ("--simulate-file", "-x"),
    ],
)
def test_other_flags_and_flag_like_arguments_never_reach_the_binary(
    fake: SimpleNamespace, flag: str, arg: str
) -> None:
    config = make_config("required", os.environ, REPO)
    with pytest.raises(ValueError):
        simulator._invoke(config, flag, arg)
    assert fake.calls() == []


def test_only_the_dictionary_and_judge_variables_survive(
    fake: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHIZUKU_SIM_LEARNING", "1")
    monkeypatch.setenv("SHIZUKU_MEMORY_DIR", "/elsewhere")
    config = make_config("required", os.environ, REPO)
    simulate_keys(config, "<live>ka<enter>")
    simulate_keys(config, "<live>ka<enter>", timing=True)
    assert fake.calls()[0]["env"] == ["SHIZUKU_DICTIONARY", "SHIZUKU_JUDGE_DIR"]
    assert fake.calls()[1]["env"] == [
        "SHIZUKU_DICTIONARY",
        "SHIZUKU_JUDGE_DIR",
        "SHIZUKU_SIM_TIMING",
    ]


def test_judge_off_drops_the_judge_directory_from_the_child(
    fake: SimpleNamespace,
) -> None:
    config = make_config("off", os.environ, REPO)
    assert config.judge_dir is None
    simulate_keys(config, "<live>ka<enter>")
    assert fake.calls()[0]["env"] == ["SHIZUKU_DICTIONARY"]


def test_configuration_without_a_dictionary_or_judge_is_refused(
    fake: SimpleNamespace,
) -> None:
    env = dict(os.environ)
    for name, expect in (
        ("SHIZUKU_DICTIONARY", "not set"),
        ("SHIZUKU_JUDGE_DIR", "not set"),
    ):
        broken = {k: v for k, v in env.items() if k != name}
        with pytest.raises(SimulatorError, match=expect):
            make_config("required", broken, REPO)
    (fake.tmp / "empty").mkdir()
    with pytest.raises(SimulatorError, match="missing or empty"):
        make_config("off", {**env, "SHIZUKU_DICTIONARY": str(fake.tmp / "empty")}, REPO)
    (fake.judge / "tokenizer.json").unlink()
    with pytest.raises(SimulatorError, match="lacks tokenizer.json"):
        make_config("required", env, REPO)
    assert (
        make_config(
            "off", {k: v for k, v in env.items() if k != "SHIZUKU_JUDGE_DIR"}, REPO
        ).judge
        == "off"
    )


def test_the_preflight_needs_proof_that_the_judge_ran(
    fake: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config("required", os.environ, REPO)
    assert preflight(config) == 1
    monkeypatch.setenv("FAKE_MODE", "no_judge")
    with pytest.raises(SimulatorError, match="judge did not run"):
        preflight(config)
    monkeypatch.setenv("FAKE_MODE", "judge_lost")
    with pytest.raises(SimulatorError, match="judge did not load"):
        preflight(config)


def test_judge_off_must_really_run_without_the_judge_and_a_lost_dictionary_stops_everything(
    fake: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    off = make_config("off", os.environ, REPO)
    monkeypatch.setenv("FAKE_MODE", "judge_lost")
    assert preflight(off) == 0  # "not configured" is what off means
    monkeypatch.setenv("FAKE_MODE", "dictionary_lost")
    with pytest.raises(SimulatorError, match="dictionary could not be opened"):
        preflight(off)
