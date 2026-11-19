"""Seed templates.seed.json from the F2F scoring xlsx.

Usage: uv run python scripts/seed_templates.py "<path to xlsx>"
"""

from __future__ import annotations

import html
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "f2f" / "data" / "templates.seed.json"

SHEETS = {
    "xl/worksheets/sheet1.xml": "Digital",
    "xl/worksheets/sheet2.xml": "UC",
    "xl/worksheets/sheet3.xml": "P&FS",
}
THRESHOLDS = {
    "Digital": {"IE1": 90, "IE2": 117, "Senior IE": 171},
    "UC": {"IE1": 99, "IE2": 126, "Senior IE": 192},
    "P&FS": {"IE1": 117, "IE2": 141, "Senior IE": 219},
}
DIGITAL_SCENARIO = (
    "You are one of our talented IMs, intimately familiar with our Adyen Checkout solution. "
    "You've been assigned to a project and will lead a technical kick off call with a merchant we've been "
    "trying to poach from our competitor for years: [Merchant Name]\n\n"
    "You've aligned with the Adyen commercial sales manager [Insert SM name] on high level topics and now the "
    "SM & [Merchant Name] team has invited their CTO, [IE Name], a technically gifted person who is slow to "
    "warm up to new partners, to learn about Adyen's integration and integration process. Your commercial "
    "colleague has primed the team and has them excited about Adyen.\n\n"
    "We have just found out the CTO has invited members of their technical team to the meeting, including "
    "their developer, [IE Name], who will be in charge of integrating Adyen and the merchants Project manager "
    "[TL Name]. Their developer is a highly technical and organised individual who has worked with the "
    "merchants previous PSP before and the Project Manager is an experienced PM who will be managing the "
    "project from the merchants side and has never done a PSP integration before.\n\n"
    "You're expected to lead the call and:\n"
    "- Uncover the merchant's unique business needs\n"
    "- Present yourself as a subject matter expert\n"
    "- Explain and set expectations for Adyen's way of implementing and what can be achieved in the timeline\n"
    "- Give a technical presentation about our Adyen Ecommerce proposition tailored using the information "
    "you uncover\n"
    "- Close the meeting on time and with immediate next steps for the integration, as well as send a Kick "
    "off summary email afterward that also covers any outstanding questions.\n\n"
    "Your commercial colleague has informed you that the attendees are very detail oriented and will also "
    "have some minor questions on the Adyen Platform / tokenisation / acquiring / financial reconciliation "
    "amongst other topics, so be ready for some off-track questions. There will be a separate POS meeting so "
    "no need to know everything about that, but some general knowledge might be useful.\n\n"
    "The [Merchant Name] team has 1 hour available, so make sure you condense your talking points to the "
    "important topics you want to convey. They look forward to understanding how our solution works and what "
    "they can achieve with Adyen. Attached is the Roll out plan we have received from the SM [SM Name]"
)
UC_SCENARIO = (
    "Hi [NAME],\n"
    "\n"
    "You’re almost at the end of your formal IM onboarding journey which ends in a Fit to Fly assessment on [DATE SCHEDULED]! We hope you’re proud of how far you’ve come!\n"
    "\n"
    "What to expect:\n"
    "\n"
    "- The Fit to Fly assessment is meant to demonstrate whether or not you are ready to take on projects on your own and it’s a space for you and your team lead to align on your readiness through a true-to-life role play scenario\n"
    "- In a 1 hour roleplay, you are the IE leading a technical kick off call with the merchant with a slide deck.\n"
    "- You are roleplaying with your team lead and other experienced IEs playing the merchant per the prompt below\n"
    "- There will be some questions posed during the merchant call that you will need to come back to the ‘merchant’ on via email, alongside a summary of the kick off call.\n"
    "\n"
    "Fit to Fly role play prompt:\n"
    "\n"
    "You are one of our talented IEs, intimately familiar with our Adyen Checkout solution.\n"
    "\n"
    "You’ve been assigned to a project and will lead a technical kick off call with a merchant we’ve been trying to poach from our competitor for years: [Merchant Name]\n"
    "\n"
    "You’ve aligned with the Adyen commercial sales manager [Insert SM name] on high level topics and now [Merchant Name]  has invited their CTO,  [IE Name], a technically gifted person who is slow to warm up to new partners, to learn about Adyen’s integration and integration process.\n"
    "\n"
    "Your commercial colleague has primed the team and has them excited about Adyen.\n"
    "\n"
    "We have just found out the CTO has invited members of their technical team to the meeting, including their developer, [IE Name], who will be in charge of integrating Adyen and the merchants Project manager [TL Name].\n"
    "\n"
    "Their developer is a highly technical and organised individual who has worked with the merchants previous PSP before and the Project Manager is an experienced PM who will be managing the project from the merchants side and has never done a PSP integration before,\n"
    "\n"
    "You’re expected to lead the call and:\n"
    "\n"
    "- Uncover the merchant’s unique business needs\n"
    "- Present yourself as a subject matter expert\n"
    "- Explain and set expectations for Adyen’s way of implementing and what can be achieved in the timeline\n"
    "- Give a technical presentation about our Adyen Ecommerce & IPP proposition that is tailored using the information you uncover\n"
    "- Close the meeting on time and with immediate next steps for the integration\n"
    "\n"
    "Your commercial colleague has informed you that the attendees are very detail oriented and will also have some minor questions on In-Person-Payments, Adyen Terminal Offering, and Terminal API amongst other topics, so be ready for some off-track questions.\n"
    "\n"
    "The [Merchant Name]  team has 1 hour available, so make sure you condense your talking points to the important topics you want to convey. They look forward to understanding how our solution works and what they can achieve with Adyen.\n"
    "\n"
    "Attached is the Roll out plan we have received from the SM [SM Name]"
)
PFS_SCENARIO = (
    "Hi [NAME],\n"
    "\n"
    "You’re almost at the end of your formal IE onboarding journey which ends in a Fit to Fly assessment on [DATE SCHEDULED]! We hope you’re proud of how far you’ve come!\n"
    "\n"
    "What to expect:\n"
    "\n"
    "- The Fit to Fly assessment is meant to demonstrate whether or not you are ready to take on projects on your own and it’s a space for you and your team lead to align on your readiness through a true-to-life role play scenario\n"
    "- In a 1 hour roleplay, you are the IE leading a technical kick off call with the merchant with a slide deck.\n"
    "- You are roleplaying with your team lead and other experienced IEs playing the merchant per the prompt below\n"
    "- There will be some questions posed during the merchant call that you will need to come back to the ‘merchant’ on via email, alongside a summary of the kick off call.\n"
    "\n"
    "Fit to Fly role play prompt:\n"
    "\n"
    "You are one of our talented IEs, intimately familiar with our Adyen for Platforms solution.\n"
    "\n"
    "You’ve been assigned to a project and will lead a technical kick off call with a merchant we’ve been trying to poach from our competitor for years:  [Merchant Name]\n"
    "\n"
    "They signed the contract last week and are ready to get started.\n"
    "\n"
    "You’ve aligned with the Adyen commercial sales manager [Insert SM name] on high level topics and now [Merchant Name]  has invited their CTO,  [IE Name], a technically gifted person who is slow to warm up to new partners, to learn about Adyen’s integration and integration process.\n"
    "\n"
    "Your commercial colleague has primed the team and has them excited about Adyen.\n"
    "\n"
    "We have just found out the CTO has invited members of their technical team to the meeting, including their developer, [IE Name], who will be in charge of integrating Adyen and the merchants Project manager [TL Name].\n"
    "\n"
    "Their developer is a highly technical and organised individual who has worked with the merchants previous PSP before and the Project Manager is an experienced PM who will be managing the project from the merchants side and has never done a PSP integration before,\n"
    "\n"
    "You’re expected to lead the call and:\n"
    "\n"
    "- Uncover the merchant’s unique business needs\n"
    "- Present yourself as a subject matter expert\n"
    "- Explain and set expectations for Adyen’s way of implementing and what can be achieved in the timeline\n"
    "- Give a technical presentation about our Adyen for Platforms proposition tailored using the information you uncover\n"
    "- Close the meeting on time and with immediate next steps for the integration\n"
    "\n"
    "Your commercial colleague has informed you that the attendees are very detail oriented so be ready for some off-track questions.\n"
    "\n"
    "The [Merchant Name]  team has 1 hour available, so make sure you condense your talking points to the important topics you want to convey. They look forward to understanding how our solution works and what they can achieve with Adyen.\n"
    "\n"
    "Attached is the Roll out plan we have received from the SM [SM Name]"
)
PLACEHOLDER_SCENARIO = (
    "Scenario for the {pillar} F2F. Edit this text in the template editor. Use [Placeholders] such as "
    "[Merchant Name] and [SM Name] for values that change per F2F."
)


def _cells(xml: str, shared: list[str]) -> dict[str, str]:
    cells: dict[str, str] = {}
    for m in re.finditer(r'<c r="([A-Z]+\d+)"([^>]*?)(?:/>|>(.*?)</c>)', xml, re.S):
        ref, attr, body = m.groups()
        if not body:
            continue
        v = re.search(r"<v>(.*?)</v>", body, re.S)
        if not v:
            continue
        val = v.group(1)
        val = shared[int(val)] if 't="s"' in attr else html.unescape(val)
        cells[ref] = val.strip()
    return cells


def _section_title(header: str) -> str:
    special = {"P&FS": "P&FS", "UC": "UC", "DIGITAL": "Digital"}
    if header in special:
        return special[header]
    return " ".join(w if w == "&" else w.capitalize() for w in header.lower().split())


def parse(path: Path) -> list[dict[str, object]]:
    z = zipfile.ZipFile(path)
    raw = re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S)
    shared = [html.unescape(re.sub(r"<[^>]+>", "", s)) for s in raw]
    pillars: list[dict[str, object]] = []
    for sheet, pillar in SHEETS.items():
        cells = _cells(z.read(sheet).decode(), shared)
        max_row = max(int(re.sub(r"[A-Z]+", "", k)) for k in cells)
        section = ""
        questions: list[dict[str, object]] = []
        for row in range(1, max_row + 1):
            a, b = cells.get(f"A{row}", ""), cells.get(f"B{row}", "")
            if a and not b and a.upper() == a and a not in ("RATING", "NAME", "DESCRIPTION"):
                section = _section_title(a)
                continue
            if a and b and cells.get(f"G{row}") == "FINAL SCORE":
                weight = float(cells.get(f"H{row + 1}", "0") or 0)
                tag = cells.get(f"J{row + 1}", "All")
                # The row label is authoritative; header rows are sometimes placed below their first question.
                section = pillar if tag == pillar else _section_title(a.upper())
                desc_row = row + 3
                questions.append(
                    {
                        "id": f"q{len(questions) + 1}",
                        "section": section,
                        "text": b,
                        "priority": int(weight),
                        "tag": tag,
                        "desc1": cells.get(f"B{desc_row}", "").rstrip(" /"),
                        "desc3": cells.get(f"D{desc_row}", "").rstrip(" /"),
                        "desc5": cells.get(f"F{desc_row}", "").rstrip(" /"),
                    }
                )
        scenario = {"Digital": DIGITAL_SCENARIO, "UC": UC_SCENARIO, "P&FS": PFS_SCENARIO}.get(
            pillar
        ) or PLACEHOLDER_SCENARIO.format(pillar=pillar)
        pillars.append(
            {"key": pillar, "scenario": scenario, "questions": questions, "thresholds": THRESHOLDS[pillar]}
        )
    return pillars


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    pillars = parse(Path(sys.argv[1]))
    for p in pillars:
        qs = p["questions"]
        assert isinstance(qs, list)
        print(p["key"], len(qs), "questions, max", sum(int(q["priority"]) * 5 for q in qs))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"pillars": pillars}, indent=2, ensure_ascii=False) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
