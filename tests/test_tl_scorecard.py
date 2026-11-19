from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from f2f.pdf import PdfRenderer
from tests.conftest import RecordingSender, create_f2f, drain, score_form, svc


def test_tl_is_a_panelist_listed_last(client: TestClient) -> None:
    f = svc(client).store.get(create_f2f(client))
    assert f
    tl = f.panelists[-1]
    assert tl.is_tl and tl.name == "Tara Lead" and tl.email == "tara@example.com" and tl.role == "TL"
    assert [p.name for p in f.invitees] == ["Pat One", "Dev Two"]
    assert sum(p.is_tl for p in f.panelists) == 1


def test_dashboard_offers_tl_scorecard_without_copy_link(client: TestClient) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    tl = f.panelists[-1]
    page = client.get(f"/admin/f2f/{f2f_id}").text
    assert "(you)" in page and f'href="/panel/{tl.token}"' in page and "Open my scorecard" in page
    assert page.count("Copy link") == len(f.invitees)
    assert f"0/{len(f.panelists)} submitted" in page


def test_no_invite_emails_for_tl_but_calendar_invite_includes_tl(
    client: TestClient, sender: RecordingSender
) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    client.post(f"/admin/f2f/{f2f_id}/invite")
    drain(client)
    assert "tara@example.com" in sender.invites[0].attendees
    labels = [j.label for j in svc(client).jobs.for_f2f(f2f_id)]
    assert not any("Panel link to Tara" in label for label in labels)
    assert sum(label.startswith("Panel link to") for label in labels) == len(f.invitees)
    assert not any(e.to == ["tara@example.com"] and "panel" in e.subject.lower() for e in sender.emails)


def test_tl_scorecard_page_and_autosave(client: TestClient) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    tl = f.panelists[-1]
    client.cookies.clear()  # the token alone opens the scorecard, as for any panelist
    page = client.get(f"/panel/{tl.token}").text
    assert "Tara Lead" in page and f"/admin/f2f/{f2f_id}" in page and "Back to dashboard" in page
    other = client.get(f"/panel/{f.invitees[0].token}").text
    assert "Back to dashboard" not in other
    r = client.post(f"/panel/{tl.token}/save", data=score_form(client, f2f_id, 4))
    assert r.status_code == 200 and tl.assessment.scores
    assert not f.invitees[0].assessment.scores


def test_tl_submit_counts_in_collation_and_sends_no_email(
    client: TestClient, sender: RecordingSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_render(self: PdfRenderer, html: str) -> bytes:
        return b"%PDF-fake" + html.encode()

    monkeypatch.setattr(PdfRenderer, "render", fake_render)
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    for p, s in zip(f.panelists, (2, 4, 3), strict=True):
        form = score_form(client, f2f_id, s, notes=f"observed by {p.name}")
        r = client.post(f"/panel/{p.token}/submit", data=form, follow_redirects=False)
        assert r.status_code == 303, r.text
    drain(client)
    tl = f.panelists[-1]
    assert tl.assessment.submitted and tl.pdf
    assert f.status.value == "Collating"  # needs the TL's scorecard too
    # only the two invited panelists get their PDF by email
    assert [e.to for e in sender.emails if e.subject.startswith("Your F2F assessment")] == [
        ["pat@example.com"],
        ["dev@example.com"],
    ]
    # the TL's score is part of the average and is listed, with a PDF, on the TL views
    collate = client.get(f"/admin/f2f/{f2f_id}/collate").text
    assert "3 of 3 panelists submitted" in collate and "Tara Lead" in collate
    assert collate.count("Download PDF") == 3
    q = f.template.questions[0]
    assert f"{(2 + 4 + 3) / 3:.1f}" in collate and q.id
    dash = client.get(f"/admin/f2f/{f2f_id}").text
    assert "View my scorecard" in dash and "3/3 submitted" in dash
    assert client.get(f"/admin/f2f/{f2f_id}/panelist/{tl.id}/pdf").content.startswith(b"%PDF")
    assert client.get(f"/panel/{tl.token}/pdf").content.startswith(b"%PDF")
