"""Notation, clause alignment and the extra-keystroke score."""

import pytest
from scoring import (
    Probe,
    Verdict,
    classify_sentence,
    is_notation_variant,
    normalize_numbers,
    rank_of,
    score_for_rank,
    settle,
)
from typing_plan import Sentence


def sentence(golds: str, readings: str) -> Sentence:
    return Sentence(tuple(golds.split("|")), tuple(readings.split("|")))


def miss(*options: str, cost: int = 10, got: str = "x") -> Verdict:
    return Verdict("miss", options, cost, got)


@pytest.mark.parametrize(
    "text, normalized",
    [
        ("十時", "10時"),
        ("三日", "3日"),
        ("二十五日", "25日"),
        ("百二十", "120"),
        ("一万二千円", "12000円"),
        ("二〇二六年", "2026年"),
        ("３時", "3時"),
        ("一緒に", "1緒に"),
        ("万", "10000"),
    ],
)
def test_numerals_become_arabic_digits(text: str, normalized: str) -> None:
    assert normalize_numbers(text) == normalized


@pytest.mark.parametrize(
    "a, b",
    [
        ("五万円", "5万円"),
        ("二十日", "20日"),
        ("三百円", "300円"),
        ("二千五百", "2500"),
        ("1万2千", "一万二千"),
        ("1万2千円", "12000円"),
        ("三億五千万円", "3億5千万円"),
        ("3億5千万円", "350000000円"),
        ("十分", "10分"),
    ],
)
def test_numbers_mixing_units_and_digits_are_the_same_notation(a: str, b: str) -> None:
    assert is_notation_variant(a, b)
    assert is_notation_variant(b, a)


@pytest.mark.parametrize(
    "a, b",
    [
        ("今日", "きょう"),
        ("一番", "いちばん"),
        ("十分", "じゅうぶん"),
        ("5万円", "6万円"),
        ("1万2千", "一万三千"),
        ("二十日", "21日"),
    ],
)
def test_words_and_different_numbers_are_not_notation(a: str, b: str) -> None:
    assert not is_notation_variant(a, b)


def test_normalizing_is_only_for_comparing_and_leaves_a_plain_digit_run_alone() -> None:
    assert normalize_numbers("2026年") == "2026年"
    assert normalize_numbers("5万円") == "50000円"


@pytest.mark.parametrize(
    "got, gold",
    [
        ("明日は10時から。", "明日は十時から。"),
        ("厚い本を読むのに3日かかった。", "厚い本を読むのに三日かかった。"),
        ("10時にログが分からなかった。", "十時にログが分からなかった。"),
        ("３時に集合。", "3時に集合。"),
    ],
)
def test_numerals_written_the_other_way_are_notation(got: str, gold: str) -> None:
    assert is_notation_variant(got, gold)
    assert is_notation_variant(gold, got)


@pytest.mark.parametrize(
    "got, gold",
    [
        ("彼の公演を聞いた。", "彼の講演を聞いた。"),  # homophone: a real miss
        ("10時から。", "11時から。"),
        ("Rustdeパーサー。", "Rustでパーサー。"),  # raw romaji left behind
        (
            "原因がわからなかった。",
            "原因が分からなかった。",
        ),  # a preference goes in the input as a second gold
        (
            "ねつがあるので休みます。",
            "熱があるので休みます。",
        ),  # kana that was never converted
        ("ひとつ選ぶ。", "一つ選ぶ。"),  # 一つ is 1つ, which is not ひとつ
        ("一つ選ぶ。", "ひとつ選ぶ。"),
        ("ふたりで行く。", "二人で行く。"),
        ("11時にログがわからなかった。", "十時にログが分からなかった。"),
        ("同じ。", "同じ。"),  # equal text is a match, not a notation variant
    ],
)
def test_nothing_but_numerals_is_notation(got: str, gold: str) -> None:
    assert not is_notation_variant(got, gold)


def test_a_sentence_is_lined_up_clause_by_clause() -> None:
    s = sentence(
        "昨日は雨が降ったので、傘を持った。",
        "キノウ|ハ|アメ|ガ|フッタ|ノデ|、|カサ|ヲ|モッタ|。",
    )
    verdicts = classify_sentence("昨日は雨が降ったので、傘を持った。", s)
    assert [v.kind for v in verdicts] == ["match", "match"]
    verdicts = classify_sentence("昨日は雨が降ったので、笠を持った。", s)
    assert [v.kind for v in verdicts] == ["match", "miss"]
    assert verdicts[1].options == ("傘を持った。",)
    assert verdicts[1].got == "笠を持った。"
    assert verdicts[1].retype_cost == len("kasawomotta.") + 1


def test_any_gold_alternative_counts_per_clause() -> None:
    s = sentence(
        "明日の十時に会う。|明日の10時に会う。", "アシタ|ノ|ジュウジ|ニ|アウ|。"
    )
    assert classify_sentence("明日の10時に会う。", s)[0].kind == "match"
    assert classify_sentence("明日の三時に会う。", s)[0].kind == "miss"


def test_a_second_gold_makes_the_other_spelling_a_match_and_without_it_the_spelling_is_a_miss() -> (
    None
):
    reading = "ゲンイン|ガ|ワカラナカッタ|。"
    both = sentence("原因が分からなかった。|原因がわからなかった。", reading)
    one = sentence("原因が分からなかった。", reading)
    assert classify_sentence("原因がわからなかった。", both)[0].kind == "match"
    assert classify_sentence("原因がわからなかった。", one)[0].kind == "miss"


def test_a_clause_left_in_kana_is_a_miss_not_a_match_or_notation() -> None:
    s = sentence(
        "熱があるので、今日は休みます。", "ネツ|ガ|アル|ノデ|、|キョウ|ハ|ヤスミマス|。"
    )
    verdicts = classify_sentence("ねつがあるので、今日は休みます。", s)
    assert [v.kind for v in verdicts] == ["miss", "match"]
    assert verdicts[0].got == "ねつがあるので、"


def test_a_different_clause_count_makes_every_clause_typed_again() -> None:
    s = sentence("雨なので、帰る。", "アメ|ナノデ|、|カエル|。")
    verdicts = classify_sentence("amenanode,kaeru.\n", s)
    assert [v.kind for v in verdicts] == ["unaligned", "unaligned"]
    assert verdicts[0].got == "amenanode,kaeru.\n"
    assert [v.retype_cost for v in verdicts] == [
        len("amenanode,") + 1,
        len("kaeru.") + 1,
    ]
    assert [v.kind for v in classify_sentence("", s)] == ["unaligned", "unaligned"]


def test_a_gold_that_does_not_line_up_with_the_reading_is_an_error_not_skipped() -> (
    None
):
    s = sentence("雨なので、帰る。|雨なので帰る。", "アメ|ナノデ|、|カエル|。")
    with pytest.raises(ValueError, match="clause count"):
        classify_sentence("雨なので、帰る。", s)


def test_a_sentence_without_a_final_mark_is_one_clause() -> None:
    s = sentence("意外と簡単に直せた", "イガイ|ト|カンタン|ニ|ナオセタ")
    assert classify_sentence("意外と簡単に直せた", s)[0].kind == "match"


@pytest.mark.parametrize(
    "rank, score", [(1, 1), (2, 2), (9, 2), (10, 10), (12, 12), (30, 30)]
)
def test_the_score_of_a_rank(rank: int, score: int) -> None:
    assert score_for_rank(rank) == score


def test_settling_a_clause_gives_status_and_score() -> None:
    verdict = miss("講演を", cost=10, got="公演を")
    assert settle(verdict, Probe(True, 3)) == ("rank", 2)
    assert settle(verdict, Probe(True, 0)) == ("retype", 10)  # not among the candidates
    assert settle(verdict, Probe(False, 0)) == (
        "nolist",
        10,
    )  # Space opened no list: scored as a retype
    assert settle(verdict, Probe(True, 14)) == ("rank", 14)
    assert settle(Verdict("match", ("a",), 3, "a"), Probe(True, 0)) == ("match", 0)
    assert settle(Verdict("notation", ("十時",), 8, "10時"), Probe(True, 0)) == (
        "notation",
        0,
    )
    assert settle(Verdict("unaligned", ("a",), 3, "x"), Probe(True, 4)) == ("retype", 3)


def test_the_cut_flag_does_not_change_the_score() -> None:
    verdict = miss("講演を", got="公演を")
    assert settle(verdict, Probe(True, 2, cut=True)) == settle(verdict, Probe(True, 2))


def test_the_rank_is_the_first_candidate_equal_to_a_gold_or_a_numeral_variant_of_it() -> (
    None
):
    verdict = miss("十時に会う。", cost=12)
    assert rank_of(("九時に会う。", "10時に会う。", "十時に会う。"), verdict) == 2
    assert rank_of(("九時に会う。",), verdict) == 0
    assert rank_of((), verdict) == 0


def test_a_candidate_in_kana_is_not_the_gold_though_the_list_nearly_always_holds_one() -> (
    None
):
    verdict = miss("熱があるので休みます。")
    reading_in_kana = "ねつがあるので休みます。"
    assert (
        rank_of(
            ("寝津があるので休みます。", reading_in_kana, "ネツガアルノデヤスミマス。"),
            verdict,
        )
        == 0
    )
    assert rank_of((reading_in_kana, "熱があるので休みます。"), verdict) == 2


def test_a_candidate_that_is_a_second_gold_counts() -> None:
    verdict = miss("原因が分からなかった。", "原因がわからなかった。")
    assert rank_of(("原因が早からなかった。", "原因がわからなかった。"), verdict) == 2


def test_a_candidate_with_raw_romaji_is_never_the_gold() -> None:
    assert rank_of(("Rustdeパーサー。", "Rust"), miss("Rustでパーサー。")) == 0
