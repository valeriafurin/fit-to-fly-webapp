from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from f2f.jobs import JobStatus
from tests.conftest import RecordingSender, create_f2f, drain, score_form, svc


def _chromium_available() -> bool:
    from pathlib import Path

    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    return (cache.exists() and any(cache.glob("chromium*"))) or bool(shutil.which("chromium"))


needs_chromium = pytest.mark.skipif(not _chromium_available(), reason="Playwright Chromium not installed")


def test_invites_and_emails(client: TestClient, sender: RecordingSender) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    client.post(f"/admin/f2f/{f2f_id}/invite")
    drain(client)
    assert len(sender.invites) == 1
    inv = sender.invites[0]
    assert inv.summary == "F2F – Casey Candidate – Digital"
    assert set(inv.attendees) == {
        "casey@example.com",
        "pat@example.com",
        "dev@example.com",
        "tara@example.com",
    }
    assert inv.zoom_link and inv.zoom_link in inv.description and inv.location == inv.zoom_link
    assert "Acme Shoes" in inv.description
    for p in f.panelists:
        assert p.token not in inv.description
    cand = next(e for e in sender.emails if e.to == ["casey@example.com"])
    assert cand.attachments[0].filename == "plan.pdf"
    for p in f.panelists:
        assert p.token not in cand.body_text
    for p in f.invitees:
        mail = next(e for e in sender.emails if e.to == [p.email])
        assert f"/panel/{p.token}" in mail.body_text
    # the TL scores from the dashboard: no panel link is emailed to them
    tl_token = next(p.token for p in f.panelists if p.is_tl)
    assert not any(tl_token in e.body_text or tl_token in e.body_html for e in sender.emails)
    assert not any(j.label.startswith("Panel link to Tara") for j in svc(client).jobs.for_f2f(f2f_id))
    jobs = svc(client).jobs.for_f2f(f2f_id)
    assert all(j.status == JobStatus.sent for j in jobs)
    page = client.get(f"/admin/f2f/{f2f_id}").text
    assert "Gmail compose" in page and "Download .ics" in page


def test_autosave_and_live_score(client: TestClient) -> None:
    f2f_id = create_f2f(client, ie_level="IE2")
    f = svc(client).store.get(f2f_id)
    assert f
    token = f.panelists[0].token
    r = client.post(f"/panel/{token}/save", data=score_form(client, f2f_id, 3))
    assert r.status_code == 200
    assert "117" in r.text and "Needs Development" not in r.text
    assert f.panelists[0].assessment.scores[f.template.questions[0].id] == 3
    r = client.post(f"/panel/{token}/save", data=score_form(client, f2f_id, 2))
    assert "Needs Development" in r.text


def test_panel_form_is_plain_notes_without_justification(client: TestClient) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    token = f.panelists[0].token
    page = client.get(f"/panel/{token}").text
    assert "Justification" not in page and "AI rewrite" not in page and "Use rubric text" not in page
    assert "weight" not in page.lower() and "High priority" in page
    assert "Expectations" not in page and "Next step" not in page
    assert client.post(f"/panel/{token}/justify/{f.template.questions[0].id}").status_code in (404, 405)


def test_draft_sorts_notes_by_score_and_section(client: TestClient) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    token = f.panelists[0].token
    form: dict[str, str] = {}
    for q in f.template.questions:
        form[f"score-{q.id}"] = "5" if q.section == "Meeting Management" else "2"
        form[f"notes-{q.id}"] = f"note for {q.id}"
    r = client.post(f"/panel/{token}/draft", data=form)
    assert r.status_code == 200
    page1 = f.panelists[0].assessment.page1
    assert "No notes" not in page1.summary and "scored" not in page1.summary.lower()
    meeting = [q.id for q in f.template.questions if q.section == "Meeting Management"]
    assert (
        all(f"note for {i}" in page1.discovery.strengths for i in meeting) and not page1.discovery.development
    )
    assert page1.technical.development and not page1.technical.strengths
    assert page1.communication.development and not page1.communication.strengths
    assert "Next step" not in r.text and "Strengths" in r.text


def test_calendar_invite_is_created_automatically_with_manual_fallback(
    client: TestClient, sender: RecordingSender
) -> None:
    f2f_id = create_f2f(client)
    drain(client)
    jobs = svc(client).jobs.for_f2f(f2f_id)
    assert len(jobs) == 1 and jobs[0].invite is not None
    assert jobs[0].status == JobStatus.sent and len(sender.invites) == 1  # created without clicking anything
    page = client.get(f"/admin/f2f/{f2f_id}").text
    assert "Download .ics" in page and "calendar.google.com/calendar/render" in page  # manual fallback
    client.post(f"/admin/f2f/{f2f_id}/invite")  # does not create a second invite
    drain(client)
    assert len(sender.invites) == 1
    assert sum(1 for j in svc(client).jobs.for_f2f(f2f_id) if j.invite) == 1


def test_tl_sees_every_panelist_pdf_and_score(client: TestClient) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    for p in f.panelists:
        p.pdf = b"%PDF-fake"
    page = client.get(f"/admin/f2f/{f2f_id}/collate").text
    assert page.count("Download PDF") == len(f.panelists)
    assert "Score per panelist" in page and "Expectations" not in page and "Next step" not in page
    dash = client.get(f"/admin/f2f/{f2f_id}").text
    assert dash.count("Download PDF") == len(f.panelists) and "collated.pdf" in dash
    for p in f.panelists:
        assert client.get(f"/admin/f2f/{f2f_id}/panelist/{p.id}/pdf").content == b"%PDF-fake"


def test_submit_requires_all_scores(client: TestClient) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    r = client.post(f"/panel/{f.panelists[0].token}/submit", data={})
    assert r.status_code == 400


@needs_chromium
def test_full_flow(client: TestClient, sender: RecordingSender) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    client.post(f"/admin/f2f/{f2f_id}/invite")
    drain(client)
    for p, s in zip(f.invitees, (3, 4), strict=True):
        form = score_form(client, f2f_id, s)
        r = client.post(f"/panel/{p.token}/draft", data=form)
        assert r.status_code == 200 and "p1-summary" in r.text
        r = client.post(f"/panel/{p.token}/submit", data=form, follow_redirects=False)
        assert r.status_code == 303, r.text
        assert p.pdf and p.pdf.startswith(b"%PDF")
        assert client.post(f"/panel/{p.token}/save", data=form).status_code == 409
        assert client.get(f"/panel/{p.token}/pdf").content.startswith(b"%PDF")
    drain(client)
    submitted_mails = [e for e in sender.emails if e.subject.startswith("Your F2F assessment")]
    assert len(submitted_mails) == 2 and all(len(e.attachments) == 1 for e in submitted_mails)
    assert f.status.value == "Collating"

    page = client.get(f"/admin/f2f/{f2f_id}/collate").text
    assert "3.5" in page
    q0 = f.template.questions[0]
    r = client.post(f"/admin/f2f/{f2f_id}/collate", data={f"override-{q0.id}": "5", "p1-summary": "x"})
    assert r.status_code == 200
    expected = round(sum(q.priority * 3.5 for q in f.template.questions) + q0.priority * 1.5, 1)
    assert f"{expected:.1f}" in r.text
    r = client.post(f"/admin/f2f/{f2f_id}/collate/draft")
    assert r.status_code == 200
    r = client.post(f"/admin/f2f/{f2f_id}/send-tl", follow_redirects=False)
    assert r.status_code == 303
    drain(client)
    tl = next(e for e in sender.emails if e.to == ["tara@example.com"])
    assert len(tl.attachments) == 3
    assert all(a.content.startswith(b"%PDF") for a in tl.attachments)
    assert f.status.value == "Sent"
    client.post(f"/admin/f2f/{f2f_id}/purge")
    assert svc(client).store.get(f2f_id) is None


def test_pdf_content_end_to_end_without_chromium(
    client: TestClient, sender: RecordingSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same flow as test_full_flow, with only the browser step stubbed so the PDF HTML can be checked."""
    from f2f.pdf import PdfRenderer

    async def fake_render(self: PdfRenderer, html: str) -> bytes:
        return b"%PDF-fake" + html.encode()

    monkeypatch.setattr(PdfRenderer, "render", fake_render)
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    for p, s in zip(f.invitees, (2, 4), strict=True):
        form = score_form(client, f2f_id, s, notes=f"observed by {p.name}")
        # no draft: submit fills the write-up from the notes
        assert client.post(f"/panel/{p.token}/submit", data=form, follow_redirects=False).status_code == 303
        html = (p.pdf or b"").decode()
        assert "Evaluation Summary" in html and "F2F Feedback" in html and "<h2>Score</h2>" in html
        assert "Strengths" in html and "Development areas" in html and f"observed by {p.name}" in html
        assert "Expectations" not in html and "Justification" not in html and "Weight" not in html
        assert "Priority" in html
    summary = f.panelists[0].assessment.page1.summary
    assert "score" not in summary.lower()
    drain(client)

    r = client.get(f"/admin/f2f/{f2f_id}/collated.pdf")
    assert r.status_code == 200
    html = r.content.decode()
    assert "Expectations" not in html and "Next Steps" not in html
    assert "Score per panelist" in html and "Pat One" in html and "Dev Two" in html
    assert "Justification" not in html
    assert client.post(f"/admin/f2f/{f2f_id}/send-tl", follow_redirects=False).status_code == 303
    drain(client)
    tl = next(e for e in sender.emails if e.to == ["tara@example.com"])
    assert len(tl.attachments) == 3
