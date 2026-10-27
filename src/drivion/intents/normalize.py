"""Turns a raw transcript into a predictable lowercase phrase for the parser.

    "Hey Drivion, could you set the volume to Forty-five %, please?"
      -> "set the volume to 45 percent"

Steps: lowercase, "%" -> "percent", drop punctuation, expand contractions,
number words -> digits, then strip polite and addressing words at the
start and end ("please", "can you", "Drivion", ...).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

_CONTRACTIONS = {
    "what's": "what is", "that's": "that is", "it's": "it is", "i'm": "i am",
    "don't": "do not", "can't": "cannot", "won't": "will not", "let's": "let us",
    "i'd": "i would", "you're": "you are", "who's": "who is", "where's": "where is",
    "how's": "how is", "there's": "there is",
}

ASSISTANT_NAME = "drivion"
# Whisper has never heard "Drivion", so it spells it differently each time:
# "Drivian", "Dravian", even "Dr. Vian". Anything similar enough at the start
# or end of a command counts as the name, except real words that are too close.
_NAME_SIMILARITY = 0.7
_NOT_THE_NAME = {"driving", "drive", "drives", "drivein", "diving", "division", "derivation"}

_LEADING = [
    "hey", "hi", "hello", "please", "can you", "could you",
    "would you", "will you", "would you please", "could you please", "can you please",
    "i want you to", "i would like you to", "i need you to", "kindly",
]
_TRAILING = ["please", "for me", "thanks", "thank you", "now"]
# "okay" alone means "yes"; only strip it when more words follow.
_LEADING_IF_MORE = ["ok", "okay", "so", "um", "uh", "alright"]


def is_assistant_name(words: list[str]) -> bool:
    joined = "".join(words)
    # About the right length as well as similar: "drvian" yes, "divisionof" no.
    if joined in _NOT_THE_NAME or not joined.isalpha() or not 5 <= len(joined) <= 9:
        return False
    return SequenceMatcher(None, joined, ASSISTANT_NAME).ratio() >= _NAME_SIMILARITY


def words_to_numbers(text: str) -> str:
    """'forty five percent' -> '45 percent', 'a hundred' -> '100'."""
    tokens = text.split()
    out: list[str] = []
    value: int | None = None

    def flush() -> None:
        nonlocal value
        if value is not None:
            out.append(str(value))
            value = None

    def ends_in_round_hundred() -> bool:  # 100, 200, ... can take "and five", "forty"
        return value is not None and value >= 100 and value % 100 == 0

    def ends_in_bare_tens() -> bool:      # 40, 140, ... can take a unit: "forty five"
        return value is not None and value % 100 >= 20 and value % 10 == 0

    for i, token in enumerate(tokens):
        following = tokens[i + 1] if i + 1 < len(tokens) else ""
        if token in _TENS:
            if not ends_in_round_hundred():
                flush()
            value = (value or 0) + _TENS[token]
        elif token in _UNITS:
            unit = _UNITS[token]
            if ends_in_round_hundred() or (ends_in_bare_tens() and unit < 10):
                value += unit
            else:
                flush()
                value = unit
        elif token == "hundred" and (value is None or value < 100):
            value = (value or 1) * 100
        elif token == "a" and following == "hundred":
            flush()
            value = 1
        elif token == "and" and ends_in_round_hundred() and (following in _UNITS or following in _TENS):
            continue  # "one hundred and five"
        else:
            flush()
            out.append(token)
    flush()
    return " ".join(out)


def _strip_name(text: str) -> tuple[str, bool]:
    """Remove the assistant's name (1 or 2 words) from the start or end.

    A command that is *only* the name becomes the canonical "drivion".
    """
    words = text.split()
    # One word first: otherwise "drivion go" (-> "driviongo") would swallow "go".
    # Two words only for splits like "Dr. Vian".
    for size in (1, 2):
        if len(words) == size and is_assistant_name(words):
            return (ASSISTANT_NAME, text != ASSISTANT_NAME)
        if len(words) > size and is_assistant_name(words[:size]):
            return " ".join(words[size:]), True
        if len(words) > size and is_assistant_name(words[-size:]):
            return " ".join(words[:-size]), True
    return text, False


def _strip_edges(text: str) -> str:
    changed = True
    while changed and text:
        changed = False
        for phrase in sorted(_LEADING, key=len, reverse=True):
            if text == phrase:
                continue
            if text.startswith(phrase + " "):
                text, changed = text[len(phrase) + 1:], True
                break
        for phrase in _LEADING_IF_MORE:
            if text.startswith(phrase + " "):
                text, changed = text[len(phrase) + 1:], True
        for phrase in sorted(_TRAILING, key=len, reverse=True):
            if text.endswith(" " + phrase):
                text, changed = text[: -len(phrase) - 1], True
                break
        # Last, so "hey drivian" first loses "hey" and is then seen as just the name.
        text, name_removed = _strip_name(text)
        changed = changed or name_removed
    return text


def normalize(text: str) -> str:
    text = text.lower().replace("%", " percent ").replace("-", " ")
    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    words = [_CONTRACTIONS.get(word, word) for word in text.split()]
    text = " ".join(words).replace("'", "")
    text = words_to_numbers(text)
    return _strip_edges(" ".join(text.split()))
