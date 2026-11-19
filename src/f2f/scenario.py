from __future__ import annotations

import re

# Placeholders the app fills from the create-F2F form, so the TL is never asked for them twice.
# Maps each placeholder to a short description of the form field it comes from.
AUTO_PLACEHOLDERS = {
    "CTO Name": "the panelist playing the CTO",
    "Developer Name": "the panelist playing the Developer",
    "Project Manager Name": "the panelist playing the PM",
    "TL Name": "the TL name",
    "IE Name": "the candidate name",
    "NAME": "the candidate name",
    "DATE SCHEDULED": "the date",
}

PLACEHOLDER_RE = re.compile(r"\[([^\[\]\n]{1,60})\]")


def placeholders(text: str) -> list[str]:
    seen: list[str] = []
    for m in PLACEHOLDER_RE.finditer(text):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def fill(text: str, values: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        value = values.get(m.group(1).strip(), "").strip()
        return value or m.group(0)

    return PLACEHOLDER_RE.sub(repl, text)
