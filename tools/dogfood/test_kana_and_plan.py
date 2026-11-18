"""Romaji conversion, input parsing and the typing plan (no simulator)."""

from itertools import pairwise

import pytest
from kana import key_count, to_keys
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
    split_clauses,
)

ROW = "日常\t基本\t{split}\t{seed}\t{gold}\t{reading}\n"
KARENO = ROW.format(
    split="chunk",
    seed=9,
    gold="彼の講演を聞いて感動した。",
    reading="カレ|ノ|コウエン|ヲ|キイテ|カンドウ|シタ|。",
)


def one(text: str) -> Paragraph:
    (paragraph,) = parse_input(text)
    return paragraph


@pytest.mark.parametrize(
    "kana, keys",
    [
        ("カレノ", "kareno"),
        ("コウエンヲ", "kouennwo"),
        ("キョウ", "kyou"),
        ("シタ|", "sita|"),
        ("ヤスミマス。", "yasumimasu."),
        ("ガッコウ", "gakkou"),
        ("リリース", "riri-su"),
        ("ファイル", "fairu"),
        ("Rust", "Rust"),
        ("a<b", "a<lt>b"),
        ("？！、", "?!,"),
        ("エッ？", "extu?"),  # っ before a mark is a small っ, not a doubled mark
        ("ッ。", "xtu."),
        ("ッ", "xtu"),
        ("ッパ", "ppa"),
    ],
)
def test_to_keys(kana: str, keys: str) -> None:
    assert to_keys(kana) == keys


def test_to_keys_rejects_kanji_instead_of_skipping_it() -> None:
    with pytest.raises(ValueError):
        to_keys("漢字")


def test_the_error_for_an_untypable_character_leaves_the_text_out() -> None:
    with pytest.raises(ValueError) as err:
        to_keys("ひみつ漢字")
    message = str(err.value)
    assert "U+6F22" in message and "position 3" in message
    assert "漢" not in message and "ひみつ" not in message


def test_key_count_counts_a_token_as_one_key() -> None:
    assert key_count("a<lt>b<enter>") == 4


def test_clauses_are_cut_after_marks_and_a_remainder_is_one_more() -> None:
    assert split_clauses("昨日は、雨でした。傘") == ["昨日は、", "雨でした。", "傘"]
    assert clause_spans(("キノウ", "ハ", "、", "アメ", "。")) == [(0, 3), (3, 5)]


def test_the_plans_example_is_typed_with_enters_after_2_2_1_3_tokens() -> None:
    p = one(KARENO)
    assert (
        key_line(p, make_chunks(p))
        == "<live>kareno<enter>kouennwo<enter>kiite<enter>kanndousita.<enter>"
    )


def test_the_same_seed_gives_the_same_key_line_and_other_seeds_can_differ() -> None:
    first = one(KARENO.replace("\t9\t", "\t5\t"))
    again = one(KARENO.replace("\t9\t", "\t5\t"))
    assert key_line(first, make_chunks(first)) == key_line(again, make_chunks(again))
    other = {
        key_line(p, make_chunks(p))
        for p in (one(KARENO.replace("\t9\t", f"\t{n}\t")) for n in range(20))
    }
    assert len(other) > 1


def test_every_chunk_has_one_to_three_tokens_and_a_mark_never_starts_one() -> None:
    gold = "昨日は雨が降っていたので、傘を持って出かけた。"
    reading = "キノウ|ハ|アメ|ガ|フッテ|イタ|ノデ|、|カサ|ヲ|モッテ|デカケタ|。"
    for seed in range(40):
        p = one(ROW.format(split="chunk", seed=seed, gold=gold, reading=reading))
        tokens = p.sentences[0].tokens
        chunks = make_chunks(p)
        assert chunks[0].start == 0 and chunks[-1].end == len(tokens)
        for a, b in pairwise(chunks):
            assert a.end == b.start
            assert tokens[b.start] not in ("、", "。")
        assert all(1 <= c.end - c.start <= 4 for c in chunks)


def test_whole_puts_one_enter_per_sentence_and_punct_one_per_mark() -> None:
    gold = "昨日は雨が降っていたので、傘を持って出かけた。‖駅前に新しいパン屋ができたらしい。"
    reading = "キノウ|ハ|アメ|ガ|フッテ|イタ|ノデ|、|カサ|ヲ|モッテ|デカケタ|。‖エキマエ|ニ|アタラシイ|パンヤ|ガ|デキタ|ラシイ|。"
    whole = one(ROW.format(split="whole", seed=0, gold=gold, reading=reading))
    punct = one(ROW.format(split="punct", seed=0, gold=gold, reading=reading))
    assert key_line(whole, make_chunks(whole)).count("<enter>") == 2
    assert key_line(punct, make_chunks(punct)).count("<enter>") == 3
    assert key_line(punct, make_chunks(punct)).startswith(
        "<live>kinouhaamegahutteitanode,<enter>"
    )


def test_a_query_types_the_paragraph_up_to_the_clause_then_the_clause_in_space_mode() -> (
    None
):
    p = one(
        ROW.format(
            split="chunk",
            seed=9,
            gold="昨日は、雨でした。",
            reading="キノウ|ハ|、|アメ|デシタ|。",
        )
    )
    chunks = make_chunks(p)
    spans = clause_spans(p.sentences[0].tokens)
    assert (
        clause_query_keys(p, chunks, 0, spans[0]) == "<live><space-mode>kinouha,<space>"
    )
    second = clause_query_keys(p, chunks, 0, spans[1])
    assert second.startswith("<live>") and second.endswith(
        "<enter><space-mode>amedesita.<space>"
    )


def test_a_clause_that_starts_inside_a_chunk_gets_an_extra_enter_there() -> None:
    p = one(
        ROW.format(
            split="whole",
            seed=0,
            gold="昨日は、雨でした。",
            reading="キノウ|ハ|、|アメ|デシタ|。",
        )
    )
    chunks = make_chunks(p)
    assert chunks == (Chunk(0, 0, 6),)
    assert (
        clause_query_keys(p, chunks, 0, (3, 6))
        == "<live>kinouha,<enter><space-mode>amedesita.<space>"
    )


@pytest.mark.parametrize(
    "text, message",
    [
        ("日常\t基本\twhole\t0\tあ。\n", "6 tab-separated"),
        (
            ROW.format(split="often", seed=0, gold="あ。", reading="ア|。"),
            "split must be",
        ),
        (
            ROW.format(split="whole", seed="x", gold="あ。", reading="ア|。"),
            "seed must be an integer",
        ),
        (
            ROW.format(split="whole", seed=0, gold="あ。‖い。", reading="ア|。"),
            "2 gold sentences but 1",
        ),
        (
            ROW.format(split="whole", seed=0, gold="あ、い。", reading="ア|。"),
            "gold 1 has 2 clauses but the reading has 1",
        ),
        (
            ROW.format(
                split="whole", seed=0, gold="あ、い。|あい。", reading="ア|、|イ|。"
            ),
            "gold 2 has 1 clauses but the reading has 2",
        ),
        (ROW.format(split="whole", seed=0, gold="漢。", reading="漢|。"), "no romaji"),
        (ROW.format(split="whole", seed=0, gold="あ。", reading="ア||。"), "empty"),
        (
            ROW.format(split="whole", seed=0, gold="あ。", reading="ア|。") * 2,
            "same key line",
        ),
    ],
)
def test_malformed_input_stops_with_a_message(text: str, message: str) -> None:
    with pytest.raises(InputError, match=message):
        parse_input(text)


def test_comments_and_blank_lines_are_skipped_and_alternatives_are_kept() -> None:
    p = one(
        "# header\n\n"
        + ROW.format(
            split="whole",
            seed=0,
            gold="十時に行く。|10時に行く。",
            reading="ジュウジ|ニ|イク|。",
        )
    )
    assert p.sentences[0].golds == ("十時に行く。", "10時に行く。")


def test_an_alternative_with_another_clause_count_is_an_input_error_naming_it() -> None:
    text = ROW.format(
        split="whole",
        seed=0,
        gold="雨なので、帰る。|雨なので帰る。",
        reading="アメ|ナノデ|、|カエル|。",
    )
    with pytest.raises(
        InputError,
        match=r"line 1 sentence 1: gold 2 has 1 clauses but the reading has 2",
    ):
        parse_input(text)


def test_alternatives_with_the_reading_s_clause_count_are_all_kept() -> None:
    p = one(
        ROW.format(
            split="whole",
            seed=0,
            gold="雨なので、帰る。|雨なので、かえる。",
            reading="アメ|ナノデ|、|カエル|。",
        )
    )
    assert p.sentences[0].golds == ("雨なので、帰る。", "雨なので、かえる。")


def _query(split: str, clause: int) -> tuple[str, str]:
    p = one(
        ROW.format(
            split=split,
            seed=0,
            gold="昨日は、雨でした。",
            reading="キノウ|ハ|、|アメ|デシタ|。",
        )
    )
    chunks = make_chunks(p)
    return key_line(p, chunks), clause_query_keys(
        p, chunks, 0, clause_spans(p.sentences[0].tokens)[clause]
    )


@pytest.mark.parametrize(
    "split, clause, cut",
    [
        ("whole", 0, False),  # nothing is typed before the first clause
        (
            "whole",
            1,
            True,
        ),  # the second clause starts inside the only chunk, so the query commits it early
        ("punct", 0, False),
        (
            "punct",
            1,
            False,
        ),  # the paragraph itself presses Enter after the first clause
    ],
)
def test_a_query_that_commits_a_chunk_early_is_marked(
    split: str, clause: int, cut: bool
) -> None:
    paragraph_keys, query = _query(split, clause)
    assert query_cuts_chunk(paragraph_keys, query) is cut


def test_a_query_that_starts_at_a_chunk_edge_types_a_prefix_of_the_real_key_line() -> (
    None
):
    paragraph_keys, query = _query("punct", 1)
    assert query.split("<space-mode>")[0] == "<live>kinouha,<enter>"
    assert paragraph_keys.startswith("<live>kinouha,<enter>")
