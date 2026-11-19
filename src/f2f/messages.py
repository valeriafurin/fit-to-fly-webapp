from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from jinja2 import Environment

from f2f.models import F2F, Attachment, Panelist
from f2f.scenario import fill
from f2f.scoring import ScoreResult, collated_score, score_assessment
from f2f.senders.base import CalendarInvite, EmailMessage


def brief(f2f: F2F) -> str:
    return fill(f2f.template.scenario, f2f.placeholders)


def time_window(f2f: F2F) -> tuple[str, str]:
    start = datetime.fromisoformat(f"{f2f.date}T{f2f.start_time}")
    end = start + timedelta(minutes=f2f.duration_minutes)
    return start.strftime("%Y-%m-%dT%H:%M:00"), end.strftime("%Y-%m-%dT%H:%M:00")


def when(f2f: F2F) -> str:
    start = datetime.fromisoformat(f"{f2f.date}T{f2f.start_time}")
    return f"{start:%A %d %B %Y, %H:%M} ({f2f.time_zone}, {f2f.duration_minutes} min)"


def invite(f2f: F2F) -> CalendarInvite:
    start, end = time_window(f2f)
    attendees = [f2f.candidate_email, *(p.email for p in f2f.panelists), f2f.tl_email]
    desc = f"Fit to Fly - {f2f.pillar}: {f2f.candidate_name}\n\n"
    if f2f.zoom_link:
        desc += f"Join Zoom: {f2f.zoom_link}\n\n"
    desc += f"Scenario brief\n\n{brief(f2f)}"
    return CalendarInvite(
        summary=f"F2F – {f2f.candidate_name} – {f2f.pillar}",
        description=desc,
        location=f2f.zoom_link,
        start_local=start,
        end_local=end,
        time_zone=f2f.time_zone,
        attendees=list(dict.fromkeys(a for a in attendees if a)),
        zoom_link=f2f.zoom_link,
    )


class Messages:
    def __init__(self, env: Environment, base_url: str) -> None:
        self.env = env
        self.text_env = Environment(loader=env.loader, autoescape=False, keep_trailing_newline=True)
        self.base_url = base_url.rstrip("/")

    def _render(self, name: str, **ctx: Any) -> tuple[str, str]:
        html = self.env.get_template(f"email/{name}.html").render(**ctx)
        text = self.text_env.get_template(f"email/{name}.txt").render(**ctx)
        return html, text

    def panel_link(self, p: Panelist) -> str:
        return f"{self.base_url}/panel/{p.token}"

    def candidate(self, f2f: F2F) -> EmailMessage:
        html, text = self._render("candidate", f=f2f, brief=brief(f2f), when=when(f2f))
        atts = [f2f.rollout_plan] if f2f.rollout_plan else []
        return EmailMessage(
            to=[f2f.candidate_email],
            cc=[f2f.tl_email],
            subject=f"Your F2F ({f2f.pillar}) – scenario brief",
            body_html=html,
            body_text=text,
            attachments=atts,
        )

    def panelist(self, f2f: F2F, p: Panelist) -> EmailMessage:
        html, text = self._render(
            "panelist", f=f2f, p=p, brief=brief(f2f), when=when(f2f), link=self.panel_link(p)
        )
        return EmailMessage(
            to=[p.email],
            subject=f"F2F panel – {f2f.candidate_name} – {f2f.pillar}",
            body_html=html,
            body_text=text,
        )

    def submitted(self, f2f: F2F, p: Panelist) -> EmailMessage:
        result = score_assessment(f2f, p.assessment)
        html, text = self._render("submitted", f=f2f, p=p, result=result, link=f"{self.panel_link(p)}/pdf")
        atts = [pdf_attachment(f2f, p.pdf, p.name)] if p.pdf else []
        return EmailMessage(
            to=[p.email],
            subject=f"Your F2F assessment – {f2f.candidate_name}",
            body_html=html,
            body_text=text,
            attachments=atts,
        )

    def tl_summary(self, f2f: F2F) -> EmailMessage:
        rows: list[tuple[Panelist, ScoreResult]] = [
            (p, score_assessment(f2f, p.assessment)) for p in f2f.panelists if p.assessment.submitted
        ]
        html, text = self._render("tl_summary", f=f2f, rows=rows, collated=collated_score(f2f))
        atts = [pdf_attachment(f2f, p.pdf, p.name) for p, _ in rows if p.pdf]
        if f2f.collation.pdf:
            atts.append(pdf_attachment(f2f, f2f.collation.pdf, "Collated"))
        return EmailMessage(
            to=[f2f.tl_email],
            subject=f"F2F results – {f2f.candidate_name} – {f2f.pillar}",
            body_html=html,
            body_text=text,
            attachments=atts,
        )


def pdf_filename(f2f: F2F, who: str) -> str:
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in f"{f2f.candidate_name} - {who}")
    return f"F2F Evaluation - {safe}.pdf"


def pdf_attachment(f2f: F2F, content: bytes, who: str) -> Attachment:
    return Attachment(filename=pdf_filename(f2f, who), content=content, mime_type="application/pdf")
