"""Input paragraphs and the way a person types them: one key line per paragraph.

Input TSV, one paragraph per line (`#` lines and blank lines are skipped), six columns:

    scene <TAB> aspect <TAB> split <TAB> seed <TAB> golds <TAB> readings

  scene, aspect  free-text labels, kept in the result files.
  split          chunk | punct | whole (see below).
  seed           integer; the only source of randomness (chunk sizes), so one input gives one key line.
  golds          the correct text, sentences separated by `‖`. A sentence may list alternatives
                 separated by `|` (`十時|10時`); matching any of them is correct.
  readings       the same sentences as katakana/hiragana tokens, tokens separated by `|`, sentences
                 separated by `‖`. A token is a morpheme-sized piece of the reading (`コウエン`,
                 `ヲ`); ASCII tokens (`Rust`) are typed as they are; a token that is only 、。？！ is
                 the punctuation key.

A paragraph is typed as one key line: `<live>` first, then each piece of reading as romaji,
then `<enter>`. `split` decides where the Enters go; a sentence always ends with an Enter:

  whole  one Enter at the end of each sentence.
  punct  an Enter after every 、。？！ token (and at the end of the sentence).
  chunk  an Enter after every 1 to 3 tokens (drawn from the seed; punctuation tokens stay with
         the piece before them, never starting a piece).

A clause (節) is a stretch of a sentence that ends with 、。？！ (the last one may end without
a mark). A sentence's reading and every one of its golds (the alternatives too) must have the
same number of clauses; a gold that does not is an input error, never skipped.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from kana import to_keys

CLAUSE_END = "、。？！"
SENTENCE_SEP = "‖"
SPACE_MODE = "<space-mode>"
SPLITS = ("chunk", "punct", "whole")
COLUMNS = 6


class InputError(ValueError):
    """The input file is malformed (the message names the line)."""


@dataclass(frozen=True)
class Sentence:
    golds: tuple[str, ...]
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class Paragraph:
    index: int  # 1-based, counting data lines only
    scene: str
    aspect: str
    split: str
    seed: int
    sentences: tuple[Sentence, ...]


@dataclass(frozen=True)
class Chunk:
    """Tokens [start, end) of sentence `sentence`, typed and then committed with one Enter."""

    sentence: int
    start: int
    end: int


def split_clauses(text: str) -> list[str]:
    """Cut after every 、。？！; a remainder without a mark is a clause of its own."""
    out: list[str] = []
    start = 0
    for i, ch in enumerate(text):
        if ch in CLAUSE_END:
            out.append(text[start : i + 1])
            start = i + 1
    if start < len(text):
        out.append(text[start:])
    return out


def clause_spans(tokens: tuple[str, ...]) -> list[tuple[int, int]]:
    """Token ranges [start, end) of each clause (a token ending in 、。？！ ends its clause)."""
    spans: list[tuple[int, int]] = []
    start = 0
    for i, token in enumerate(tokens):
        if token[-1] in CLAUSE_END:
            spans.append((start, i + 1))
            start = i + 1
    if start < len(tokens):
        spans.append((start, len(tokens)))
    return spans


def _is_mark(token: str) -> bool:
    return all(ch in CLAUSE_END for ch in token)


def _parse_sentence(golds: str, readings: str, where: str) -> Sentence:
    alternatives = tuple(golds.split("|"))
    tokens = tuple(readings.split("|"))
    if not all(alternatives) or not all(tokens):
        raise InputError(f"{where}: empty gold or reading token")
    try:
        for token in tokens:
            to_keys(token)
    except ValueError as err:
        raise InputError(f"{where}: {err}") from err
    clauses = len(clause_spans(tokens))
    for number, alternative in enumerate(alternatives, 1):
        if len(split_clauses(alternative)) != clauses:
            raise InputError(
                f"{where}: gold {number} has {len(split_clauses(alternative))} clauses "
                f"but the reading has {clauses}"
            )
    return Sentence(alternatives, tokens)


def _parse_line(line: str, index: int, number: int) -> Paragraph:
    where = f"line {number}"
    cols = line.split("\t")
    if len(cols) != COLUMNS:
        raise InputError(
            f"{where}: expected {COLUMNS} tab-separated columns, got {len(cols)}"
        )
    scene, aspect, split, seed_text, golds, readings = cols
    if split not in SPLITS:
        raise InputError(
            f"{where}: split must be one of {', '.join(SPLITS)}, got {split!r}"
        )
    try:
        seed = int(seed_text)
    except ValueError as err:
        raise InputError(
            f"{where}: seed must be an integer, got {seed_text!r}"
        ) from err
    gold_groups = golds.split(SENTENCE_SEP)
    reading_groups = readings.split(SENTENCE_SEP)
    if len(gold_groups) != len(reading_groups):
        raise InputError(
            f"{where}: {len(gold_groups)} gold sentences but {len(reading_groups)} reading sentences"
        )
    pairs = enumerate(zip(gold_groups, reading_groups), 1)
    sentences = tuple(
        _parse_sentence(g, r, f"{where} sentence {k}") for k, (g, r) in pairs
    )
    return Paragraph(index, scene, aspect, split, seed, sentences)


def parse_input(text: str) -> list[Paragraph]:
    """All paragraphs of an input file. Raises InputError on a malformed line or a repeated key line."""
    paragraphs: list[Paragraph] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        paragraphs.append(_parse_line(line, len(paragraphs) + 1, number))
    seen: dict[str, int] = {}
    for p in paragraphs:
        keys = key_line(p, make_chunks(p))
        if keys in seen:
            raise InputError(
                f"paragraphs {seen[keys]} and {p.index} type the same key line"
            )
        seen[keys] = p.index
    return paragraphs


def make_chunks(paragraph: Paragraph) -> tuple[Chunk, ...]:
    """Where the Enters go. One `random()` draw per chunk keeps sizes stable across Python versions."""
    rng = random.Random(paragraph.seed)
    chunks: list[Chunk] = []
    for si, sentence in enumerate(paragraph.sentences):
        tokens = sentence.tokens
        pos = 0
        while pos < len(tokens):
            if paragraph.split == "whole":
                end = len(tokens)
            elif paragraph.split == "punct":
                end = pos + 1
                while end < len(tokens) and tokens[end - 1][-1] not in CLAUSE_END:
                    end += 1
            else:
                end = min(len(tokens), pos + 1 + int(rng.random() * 3))
                while end < len(tokens) and _is_mark(tokens[end]):
                    end += 1
            chunks.append(Chunk(si, pos, end))
            pos = end
    return tuple(chunks)


def tokens_keys(tokens: tuple[str, ...]) -> str:
    return "".join(to_keys(t) for t in tokens)


def key_line(paragraph: Paragraph, chunks: tuple[Chunk, ...]) -> str:
    """`<live>` followed by every chunk's romaji and an Enter."""
    parts = ["<live>"]
    for c in chunks:
        parts.append(
            tokens_keys(paragraph.sentences[c.sentence].tokens[c.start : c.end])
        )
        parts.append("<enter>")
    return "".join(parts)


def clause_query_keys(
    paragraph: Paragraph,
    chunks: tuple[Chunk, ...],
    sentence: int,
    span: tuple[int, int],
) -> str:
    """Keys that type everything before a clause the way the paragraph is typed, then convert
    the clause alone with Space: `<live>...<enter><space-mode>CLAUSE<space>`. When the clause starts
    inside a chunk, that chunk is cut there and committed so the clause begins a new composition.
    """
    start = span[0]
    parts = ["<live>"]
    for c in chunks:
        tokens = paragraph.sentences[c.sentence].tokens
        if c.sentence > sentence or (c.sentence == sentence and c.start >= start):
            break
        if c.sentence == sentence and c.end > start:
            parts.append(tokens_keys(tokens[c.start : start]) + "<enter>")
            break
        parts.append(tokens_keys(tokens[c.start : c.end]) + "<enter>")
    clause_tokens = paragraph.sentences[sentence].tokens[span[0] : span[1]]
    parts.append(SPACE_MODE + tokens_keys(clause_tokens) + "<space>")
    return "".join(parts)


def query_cuts_chunk(paragraph_keys: str, query_keys: str) -> bool:
    """Whether what a query types before the clause is not the start of the paragraph's own key
    line, which happens when the clause begins in the middle of a chunk (the query adds an Enter
    there that the real typing did not press). The place of the gold in such a list is then
    measured after a different history than the real one."""
    return not paragraph_keys.startswith(query_keys.split(SPACE_MODE, 1)[0])
