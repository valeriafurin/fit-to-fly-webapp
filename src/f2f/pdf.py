from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment

from f2f.models import F2F, Page1, Question
from f2f.scoring import ScoreResult

FONT_FACES = [
    ("Adyen", "Adyen-Regular.otf", 400),
    ("Adyen", "Adyen-Medium.otf", 500),
    ("Adyen", "Adyen-Bold.otf", 700),
    ("Fakt", "Fakt-Normal.otf", 400),
    ("Fakt", "Fakt-SemiBold.otf", 600),
]


def font_css(fonts_dir: Path) -> str:
    """Inline the brand fonts as data URIs; they are licensed and never committed."""
    rules = []
    for family, filename, weight in FONT_FACES:
        path = fonts_dir / filename
        if path.exists():
            data = base64.b64encode(path.read_bytes()).decode()
            rules.append(
                f"@font-face{{font-family:'{family}';font-weight:{weight};"
                f"src:url(data:font/otf;base64,{data}) format('opentype');}}"
            )
    return "\n".join(rules)


@dataclass
class Row:
    question: Question
    rating: float | None
    points: float | None
    notes: str


def build_rows(f2f: F2F, ratings: dict[str, float], notes: dict[str, str]) -> list[Row]:
    rows = []
    for q in f2f.template.questions:
        r = ratings.get(q.id)
        rows.append(
            Row(q, r, round(q.priority * r, 1) if r is not None else None, notes.get(q.id, "").strip())
        )
    return rows


class PdfRenderer:
    def __init__(self, env: Environment, fonts_dir: Path) -> None:
        self.env = env
        self.fonts_dir = fonts_dir
        self._font_css: str | None = None

    def html(
        self,
        f2f: F2F,
        author: str,
        page1: Page1,
        rows: list[Row],
        result: ScoreResult,
        *,
        panel_scores: list[tuple[str, str, ScoreResult]] | None = None,
    ) -> str:
        """panel_scores (collated PDF only) lists each panelist's score."""
        if self._font_css is None:
            self._font_css = font_css(self.fonts_dir)
        attendees = [f2f.candidate_name, *(p.name for p in f2f.panelists), f2f.tl_name]
        return self.env.get_template("pdf/assessment.html").render(
            f=f2f,
            author=author,
            page1=page1,
            rows=rows,
            result=result,
            panel_scores=panel_scores or [],
            font_css=self._font_css,
            attendees=list(dict.fromkeys(attendees)),
        )

    async def render(self, html: str) -> bytes:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(html, wait_until="load")
                return await page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
                )
            finally:
                await browser.close()
