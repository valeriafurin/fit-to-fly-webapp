"""Warn when a note reads very differently from its score (e.g. "Yes amazing" scored 1).

This is a quick word-based check that runs on every autosave, so it needs no AI. It only warns:
the panelist can keep the score and the note as they are.
"""

from __future__ import annotations

import re

POSITIVE = {
    "amazing",
    "awesome",
    "brilliant",
    "clear",
    "clearly",
    "confident",
    "confidently",
    "excellent",
    "exceeded",
    "exceeds",
    "exceptional",
    "fantastic",
    "good",
    "great",
    "impressive",
    "impressed",
    "nailed",
    "outstanding",
    "perfect",
    "perfectly",
    "solid",
    "strong",
    "strongly",
    "structured",
    "superb",
    "thorough",
    "thoroughly",
    "well",
    "wonderful",
    "yes",
}
NEGATIVE = {
    "bad",
    "confused",
    "confusing",
    "forgot",
    "incorrect",
    "lacked",
    "lacking",
    "lacks",
    "missed",
    "missing",
    "no",
    "none",
    "poor",
    "poorly",
    "struggled",
    "struggles",
    "struggling",
    "terrible",
    "unclear",
    "unprepared",
    "unsure",
    "vague",
    "weak",
    "wrong",
}
NEGATIONS = {
    "not",
    "no",
    "never",
    "didn't",
    "didnt",
    "wasn't",
    "wasnt",
    "couldn't",
    "couldnt",
    "isn't",
    "isnt",
    "hardly",
    "without",
}
NEGATIVE_PHRASES = ("needs to improve", "needs improvement", "room for improvement", "did not", "could not")

_WORD = re.compile(r"[a-z']+")


def sentiment(note: str) -> int:
    """Positive minus negative signals in the note. A negation flips the next word ("not clear")."""
    text = note.lower().replace("’", "'")
    words = _WORD.findall(text)
    score = 0
    for i, w in enumerate(words):
        negated = i > 0 and words[i - 1] in NEGATIONS
        if w in POSITIVE:
            score += -1 if negated else 1
        elif w in NEGATIVE and w not in NEGATIONS:
            score += 1 if negated else -1
        elif w in NEGATIONS and not (i + 1 < len(words) and words[i + 1] in POSITIVE | NEGATIVE):
            score -= 1
    score -= sum(text.count(p) for p in NEGATIVE_PHRASES)
    return score


def mismatch_warning(rating: int | None, note: str) -> str:
    """Return a warning if the note and score point in opposite directions, else an empty string."""
    if rating is None or not note.strip():
        return ""
    s = sentiment(note)
    if rating <= 2 and s > 0:
        return f"Your note reads positive, but you scored {rating}. Check that the score is right."
    if rating >= 4 and s < 0:
        return f"Your note reads negative, but you scored {rating}. Check that the score is right."
    return ""
