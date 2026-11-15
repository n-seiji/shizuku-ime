"""The phases the simulator prints, parsed from output the real binary produced."""

import dataclasses

import pytest
import simulator
from simulator import parse_verbose

# What the real binary printed (target/release/shizuku --simulate KEYS), one fixture per phase
# that matters to the parsers: the phase column is `{:<34}` wide, so a long phase pushes the
# marked text right, the label column grows with the token, and a visible panel adds `panel@N`.
CONVERTING_WITH_PANEL = (
    "<live>ka<space><down>",
    """   <live>  Empty                              marked=""  committed=""
        k  Empty                              marked="k"  committed=""
        a  Composing                          marked="か"  committed=""
           judge 5.2 ms
  <space>  Converting { selected: 0, window: false } marked="か"  committed=""
           1.か* 2.car 3.科 4.カ 5.🉑 6.🦟 7.可 8.禍 9.果 10.過 11.加 12.火 13.蚊 14.化 15.家 16.下 17.日 18.課 19.歌 20.嘉 21.価 22.駆 23.賈 24.狩 25.架 26.華 27.借 28.刈 29.駈 30.戈 31.彼 32.嫁 33.穫 34.ka
   <down>  Converting { selected: 1, window: true } marked="car" panel@2  committed=""
           1.か 2.car* 3.科 4.カ 5.🉑 6.🦟 7.可 8.禍 9.果 10.過 11.加 12.火 13.蚊 14.化 15.家 16.下 17.日 18.課 19.歌 20.嘉 21.価 22.駆 23.賈 24.狩 25.架 26.華 27.借 28.刈 29.駈 30.戈 31.彼 32.嫁 33.穫 34.ka
final: ""
still composing: "car"
""",
)
HIGHLIGHT_BEYOND_NINE = (
    "<space-mode>kyouha<space><highlight:13>",
    """<space-mode>  Empty                              marked=""  committed=""
        k  Empty                              marked="k"  committed=""
        y  Empty                              marked="ky"  committed=""
        o  Composing                          marked="きょ"  committed=""
           judge 5.1 ms
        u  Composing                          marked="きょう"  committed=""
           judge 3.7 ms
        h  Composing                          marked="きょうh"  committed=""
        a  Composing                          marked="きょうは"  committed=""
           judge 8.7 ms
  <space>  Converting { selected: 0, window: false } marked="今日は"  committed=""
           1.今日は* 2.きょうは 3.強は 4.教派 5.卿は 6.京は 7.境は 8.興は 9.教は 10.強派 11.姜は 12.凶は 13.供は 14.恭は 15.巨は 16.キョウは 17.狂は 18.経は 19.今日派 20.強波 21.キョウハ 22.kyouha
<highlight:13>  Converting { selected: 12, window: true } marked="供は"  committed=""
           1.今日は 2.きょうは 3.強は 4.教派 5.卿は 6.京は 7.境は 8.興は 9.教は 10.強派 11.姜は 12.凶は 13.供は* 14.恭は 15.巨は 16.キョウは 17.狂は 18.経は 19.今日派 20.強波 21.キョウハ 22.kyouha
final: ""
still composing: "供は"
""",
)
ENGLISH_IS_LITERAL_AND_SPACE_OPENS_NO_LIST = (
    "<space-mode>Rustde<space>",
    """<space-mode>  Empty                              marked=""  committed=""
        R  Literal                            marked="R"  committed=""
        u  Literal                            marked="Ru"  committed=""
        s  Literal                            marked="Rus"  committed=""
        t  Literal                            marked="Rust"  committed=""
        d  Literal                            marked="Rustd"  committed=""
        e  Literal                            marked="Rustde"  committed=""
  <space>  Empty                              marked=""  committed="Rustde "
final: "Rustde "
""",
)
DANGLING = (
    "stuf<space>",
    """        s  Empty                              marked="s"  committed=""
        t  Dangling                           marked="st"  committed=""
        u  Dangling                           marked="stu"  committed=""
        f  Dangling                           marked="stuf"  committed=""
  <space>  Empty                              marked=""  committed="stuf "
final: "stuf "
""",
)
MIXED = (
    "kaA<space>",
    """        k  Empty                              marked="k"  committed=""
        a  Composing                          marked="か"  committed=""
           judge 4.8 ms
        A  Mixed                              marked="かA"  committed=""
  <space>  Converting { selected: 0, window: false } marked="かA"  committed=""
           1.かA* 2.kaA
final: ""
still composing: "かA"
""",
)
TRANSLITERATED_THEN_REVERTED = (
    "kyo<F7><bs>",
    """        k  Empty                              marked="k"  committed=""
        y  Empty                              marked="ky"  committed=""
        o  Composing                          marked="きょ"  committed=""
           judge 5.1 ms
     <F7>  Transliterated(Katakana)           marked="キョ"  committed=""
     <bs>  Reverted                           marked="きょ"  committed=""
final: ""
still composing: "きょ"
""",
)


def test_the_phase_of_every_step_is_kept_as_printed_even_with_a_panel_or_a_long_phase() -> (
    None
):
    keys, output = CONVERTING_WITH_PANEL
    run = parse_verbose(output, keys)
    assert [s.phase for s in run.steps] == [
        "Empty",
        "Empty",
        "Composing",
        "Converting { selected: 0, window: false }",
        "Converting { selected: 1, window: true }",
    ]
    assert (
        run.steps[3].candidates[:3] == ("か", "car", "科")
        and len(run.steps[3].candidates) == 34
    )
    assert run.steps[4].candidates[:3] == (
        "か",
        "car",
        "科",
    )  # the star moved to car and is dropped there
    assert run.steps[4].marked == "car" and run.composing == "car"


def test_a_selection_past_the_ninth_candidate_loses_only_its_own_star() -> None:
    keys, output = HIGHLIGHT_BEYOND_NINE
    run = parse_verbose(output, keys)
    assert run.steps[-1].phase == "Converting { selected: 12, window: true }"
    assert run.steps[-1].candidates[11:14] == ("凶は", "供は", "恭は")
    assert run.steps[-1].candidates[-1] == "kyouha"
    assert (
        run.steps[-2].candidates[0] == "今日は"
    )  # the first step's star is on candidate 1


def test_a_label_wider_than_its_column_still_parses() -> None:
    keys, output = HIGHLIGHT_BEYOND_NINE
    assert [s.token for s in parse_verbose(output, keys).steps][-2:] == [
        "<space>",
        "<highlight:13>",
    ]


def test_an_english_composition_is_literal_and_space_on_it_shows_no_list() -> None:
    keys, output = ENGLISH_IS_LITERAL_AND_SPACE_OPENS_NO_LIST
    run = parse_verbose(output, keys)
    assert [s.phase for s in run.steps] == ["Empty"] + ["Literal"] * 6 + ["Empty"]
    assert (
        run.steps[0].token == "<space-mode>" and run.steps[1].token == "R"
    )  # an upper-case key is a label too
    last = run.steps[-1]
    assert (last.listed, last.candidates, last.committed) == (False, (), "Rustde ")
    assert run.final == "Rustde "


@pytest.mark.parametrize(
    "fixture, phases",
    [
        (DANGLING, ["Empty", "Dangling", "Dangling", "Dangling", "Empty"]),
        (
            MIXED,
            [
                "Empty",
                "Composing",
                "Mixed",
                "Converting { selected: 0, window: false }",
            ],
        ),
        (
            TRANSLITERATED_THEN_REVERTED,
            ["Empty", "Empty", "Composing", "Transliterated(Katakana)", "Reverted"],
        ),
    ],
)
def test_the_other_phases_the_composer_prints_are_read(
    fixture: tuple[str, str], phases: list[str]
) -> None:
    keys, output = fixture
    assert [s.phase for s in parse_verbose(output, keys).steps] == phases


def test_a_list_is_shown_only_by_a_step_that_printed_candidates() -> None:
    keys, output = MIXED
    run = parse_verbose(output, keys)
    assert [s.listed for s in run.steps] == [False, False, False, True]
    assert run.steps[-1].candidates == ("かA", "kaA")


def test_a_judge_line_belongs_to_the_step_above_it_only() -> None:
    keys, output = TRANSLITERATED_THEN_REVERTED
    run = parse_verbose(output, keys)
    assert [s.judge_ran for s in run.steps] == [False, False, True, False, False]


def test_a_parsed_step_cannot_be_changed_afterwards() -> None:
    keys, output = MIXED
    step = parse_verbose(output, keys).steps[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        step.committed = "x"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        simulator._RawStep("Empty", "", "").judge_ran = True  # type: ignore[misc]
