"""Clause alignment and the extra-keystroke score (pure functions, no simulator).

Score of one clause (smaller is better):

  0                      the committed clause equals a gold clause, or differs only in how
                         numerals are written
  1                      Space then Enter picks the gold clause (candidate rank 1)
  2                      Space, then a digit key (rank 2 to 9)
  rank                   rank 10 or more: Space pressed `rank` times (digit keys stop at 9)
  keys of the reading+1  the gold is not among the candidates, or Space opened no list at all
                         (type it again): the keys that type the clause's reading, plus one to delete

Status of a clause: match | notation | rank | retype | nolist. `nolist` scores like `retype`
but is counted apart: Space committed the typed text without a candidate list (a clause that
starts with English), so there was no list to look the gold up in.

A sentence whose committed text has a different number of clauses than its reading cannot be
lined up clause by clause, so every clause of it is counted as typed again.

Notation is only the way numerals are written (`is_notation_variant`): once numerals are digits
the texts are equal (十時 / 10時, 三日 / 3日). Nothing else counts, in particular not text that is
kana where the gold has kanji (ねつが for 熱が): a candidate list nearly always holds the
whole reading in kana, and a clause that stayed unconverted is exactly the regression the score
must show. A spelling that is fine either way (分からない / わからない) is written in the input
as alternatives (`正解1|正解2`). Raw romaji left in the text (`Rustde` for `Rustで`) is not
notation either.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple

from kana import key_count
from typing_plan import Sentence, clause_spans, split_clauses, tokens_keys

_DIGITS = {
    c: n
    for n, cs in enumerate(
        ["〇零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
    )
    for c in cs
}
_UNITS = {"十": 10, "百": 100, "千": 1000}
_NUMBER_RUN = re.compile("[〇零一二三四五六七八九十百千万]+")
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


@dataclass(frozen=True)
class Verdict:
    """What one committed clause is, before any candidate list is looked at."""

    kind: str  # match | notation | miss | unaligned
    options: tuple[str, ...]  # gold clauses that count as correct
    retype_cost: int  # keys of the reading + 1
    got: str  # the committed clause; the whole sentence when kind is unaligned


class Probe(NamedTuple):
    """What the Space query of a missed clause showed."""

    listed: bool  # Space opened a candidate list
    rank: int  # 1-based place of the gold in it, 0 = absent
    cut: bool = (
        False  # the keys before the clause are not the start of the paragraph's key line
    )


def _kanji_number(run: str) -> str | None:
    if not any(c in _UNITS or c == "万" for c in run):
        return "".join(str(_DIGITS[c]) for c in run)
    total = block = 0
    digit: int | None = None
    for c in run:
        if c in _DIGITS:
            if digit is not None:
                return None
            digit = _DIGITS[c]
        elif c in _UNITS:
            block += (1 if digit is None else digit) * _UNITS[c]
            digit = None
        else:
            total += (block + (digit or 0) or 1) * 10000
            block, digit = 0, None
    return str(total + block + (digit or 0))


def normalize_numbers(text: str) -> str:
    """Numerals as Arabic digits: 十時 -> 10時, 二〇二六 -> 2026, ３ -> 3."""

    def replace(match: re.Match[str]) -> str:
        value = _kanji_number(match.group(0))
        return match.group(0) if value is None else value

    return _NUMBER_RUN.sub(replace, text.translate(_FULLWIDTH_DIGITS))


def is_notation_variant(a: str, b: str) -> bool:
    """Different text that is the same once numerals are written as digits."""
    return a != b and normalize_numbers(a) == normalize_numbers(b)


def is_equivalent(a: str, b: str) -> bool:
    return a == b or is_notation_variant(a, b)


def classify_sentence(got: str, sentence: Sentence) -> list[Verdict]:
    """One Verdict per clause of the sentence's reading, from the text committed for the sentence."""
    spans = clause_spans(sentence.tokens)
    golds = [split_clauses(g) for g in sentence.golds]
    if any(len(g) != len(spans) for g in golds):
        raise ValueError("a gold does not have the reading's clause count")
    got_clauses = split_clauses(got)
    verdicts: list[Verdict] = []
    for i, (start, end) in enumerate(spans):
        tokens = sentence.tokens[start:end]
        cost = key_count(tokens_keys(tokens)) + 1
        options = tuple(dict.fromkeys(g[i] for g in golds))
        if len(got_clauses) != len(spans):
            verdicts.append(Verdict("unaligned", options, cost, got))
            continue
        text = got_clauses[i]
        if text in options:
            kind = "match"
        elif any(is_notation_variant(text, o) for o in options):
            kind = "notation"
        else:
            kind = "miss"
        verdicts.append(Verdict(kind, options, cost, text))
    return verdicts


def rank_of(candidates: tuple[str, ...], verdict: Verdict) -> int:
    """1-based place of the first candidate that is a gold clause, or a gold clause with its
    numerals written the other way (0: none). Kana for kanji does not count."""
    for place, candidate in enumerate(candidates, 1):
        if any(is_equivalent(candidate, o) for o in verdict.options):
            return place
    return 0


def score_for_rank(rank: int) -> int:
    if rank <= 1:
        return 1
    return 2 if rank <= 9 else rank


def settle(verdict: Verdict, probe: Probe) -> tuple[str, int]:
    """(status, score) once the Space query of a miss has been looked at."""
    if verdict.kind in ("match", "notation"):
        return verdict.kind, 0
    if verdict.kind == "miss" and not probe.listed:
        return "nolist", verdict.retype_cost
    if verdict.kind == "miss" and probe.rank > 0:
        return "rank", score_for_rank(probe.rank)
    return "retype", verdict.retype_cost
