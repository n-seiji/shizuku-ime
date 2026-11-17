"""Kana to the romaji keys a person types on Shizuku's romaji table, and the key counter.

`to_keys` writes the spelling the simulator's romaji table accepts (`nn` for ん, `xtu` for a
small っ before a vowel, `-` for ー). ASCII passes through, `<` and `>` become the `<lt>` /
`<gt>` key tokens. Anything else raises ValueError so a bad reading stops the run instead of
being skipped.
"""

from __future__ import annotations

import re

_BASE = dict(
    zip(
        "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをんがぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽぁぃぅぇぉゃゅょっゎゔ",
        "a i u e o ka ki ku ke ko sa si su se so ta ti tu te to na ni nu ne no ha hi hu he ho ma mi mu me mo ya yu yo ra ri ru re ro wa wo nn ga gi gu ge go za zi zu ze zo da di du de do ba bi bu be bo pa pi pu pe po xa xi xu xe xo xya xyu xyo xtu xwa vu".split(),  # noqa: SIM905  (a hundred short keys read better as one string than as a list)
    )
)
_YOON = {
    "き": "ky",
    "し": "sy",
    "ち": "ty",
    "に": "ny",
    "ひ": "hy",
    "み": "my",
    "り": "ry",
    "ぎ": "gy",
    "じ": "zy",
    "ぢ": "dy",
    "び": "by",
    "ぴ": "py",
}
_SMALL_Y = {"ゃ": "a", "ゅ": "u", "ょ": "o"}
_SPECIAL = {
    "しぇ": "sye",
    "ちぇ": "tye",
    "じぇ": "zye",
    "ふぁ": "fa",
    "ふぃ": "fi",
    "ふぇ": "fe",
    "ふぉ": "fo",
    "てぃ": "thi",
    "でぃ": "dhi",
    "とぅ": "twu",
    "どぅ": "dwu",
    "うぃ": "wi",
    "うぇ": "we",
    "うぉ": "uxo",
    "ゔぁ": "va",
    "ゔぃ": "vi",
    "ゔぇ": "ve",
    "ゔぉ": "vo",
    "つぁ": "tsa",
}
_PUNCT = {
    "（": "(",
    "）": ")",
    "～": "~",
    "：": ":",
    "、": ",",
    "。": ".",
    "？": "?",
    "！": "!",
    "「": "[",
    "」": "]",
    "・": "/",
    "〜": "~",
    "ー": "-",
    "　": " ",
    "，": ",",
    "．": ".",
}
_ASCII_KEYS = {"<": "<lt>", ">": "<gt>"}
_KEY_TOKEN = re.compile(r"<[^<>]*>|.", re.DOTALL)


def hira(text: str) -> str:
    """Katakana to hiragana; everything else is unchanged."""
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def to_keys(kana: str) -> str:
    """The keys that type `kana` (katakana is typed as its hiragana)."""
    text = hira(kana)
    out: list[str] = []
    i = 0
    while i < len(text):
        pair = text[i : i + 2]
        if pair in _SPECIAL:
            out.append(_SPECIAL[pair])
            i += 2
            continue
        ch = text[i]
        if ch in _YOON and text[i + 1 : i + 2] in _SMALL_Y:
            out.append(_YOON[ch] + _SMALL_Y[text[i + 1]])
            i += 2
            continue
        if ch == "っ":
            following = to_keys(text[i + 1 : i + 3])[:1] if i + 1 < len(text) else ""
            doubles = following.isascii() and following.isalpha()
            out.append(following if doubles and following not in "aiueon" else "xtu")
        elif ch in _BASE:
            out.append(_BASE[ch])
        elif ch in _PUNCT:
            out.append(_PUNCT[ch])
        elif ord(ch) < 128:
            out.append(_ASCII_KEYS.get(ch, ch))
        else:
            raise ValueError(f"no romaji for U+{ord(ch):04X} at position {i}")
        i += 1
    return "".join(out)


def key_count(keys: str) -> int:
    """Number of key presses in a key string (`<enter>` and `<lt>` are one key each)."""
    return len(_KEY_TOKEN.findall(keys))
