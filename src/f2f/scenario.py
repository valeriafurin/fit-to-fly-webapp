from __future__ import annotations

import re

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
