from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from f2f.consistency import mismatch_warning
from f2f.drafting import as_sentence, score_based_feedback
from f2f.models import utcnow
from tests.conftest import create_f2f, score_form, svc


@pytest.mark.parametrize(
    ("rating", "note", "warn"),
    [
        (1, "Yes amazing", True),
        (2, "Great discovery, very clear", True),
        (5, "Did not explain pricing, struggled with refunds", True),
        (4, "Unclear and vague on webhooks", True),
        (5, "Great discovery, very clear", False),
        (1, "Not clear at all, missed refunds", False),
        (3, "Yes amazing", False),  # a 3 is never flagged
        (1, "", False),
        (None, "Yes amazing", False),
    ],
)
def test_mismatch_warning(rating: int | None, note: str, warn: bool) -> None:
    assert bool(mismatch_warning(rating, note)) is warn


def test_mismatch_shows_on_autosave_but_never_blocks(client: TestClient) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    token = f.panelists[0].token
    q = f.template.questions[0]
    r = client.post(f"/panel/{token}/save", data=score_form(client, f2f_id, 1, notes="Yes amazing"))
    assert r.status_code == 200
    assert f'id="warn-{q.id}"' in r.text and 'hx-swap-oob="true"' in r.text
    assert "reads positive, but you scored 1" in r.text
    page = client.get(f"/panel/{token}").text
    assert "reads positive, but you scored 1" in page and "data-submit-confirm" in page
    r = client.post(f"/panel/{token}/save", data=score_form(client, f2f_id, 5, notes="Yes amazing"))
    assert "reads positive" not in r.text


def test_summarise_button_has_spinner(client: TestClient) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    page = client.get(f"/panel/{f.panelists[0].token}").text
    assert 'hx-disabled-elt="this"' in page
    # only shown while the request runs: hidden by default, even if the stylesheet is stale
    assert '<span class="spinner" aria-hidden="true" hidden>' in page
    assert '<span class="busy-label" hidden>Summarising' in page
    assert "/static/app.css?v=" in page


def test_dashboard_reflects_submitted_scores_live(client: TestClient) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    first = f.panelists[0]
    client.post(f"/panel/{first.token}/save", data=score_form(client, f2f_id, 4))
    r = client.get(f"/admin/f2f/{f2f_id}/panel")
    assert r.status_code == 200 and 'hx-trigger="every 5s"' in r.text and "0/" in r.text
    first.assessment.submitted_at = utcnow()  # what submit does, minus the PDF step
    r = client.get(f"/admin/f2f/{f2f_id}/panel")
    assert f"1/{len(f.panelists)} submitted" in r.text and "Submitted " in r.text
    for p in f.panelists:
        p.assessment.submitted_at = utcnow()
    r = client.get(f"/admin/f2f/{f2f_id}/panel")
    assert "every 5s" not in r.text  # stops polling once everyone has submitted
    assert 'id="panel-status"' in client.get(f"/admin/f2f/{f2f_id}").text


def test_panel_partial_requires_tl(client: TestClient) -> None:
    f2f_id = create_f2f(client)
    client.cookies.clear()
    assert client.get(f"/admin/f2f/{f2f_id}/panel", follow_redirects=False).status_code in (
        302,
        303,
        401,
        403,
    )


def test_development_areas_are_full_sentences_without_ai() -> None:
    assert as_sentence("missed refunds") == "Missed refunds."
    assert as_sentence("Unclear?") == "Unclear?"
    assert score_based_feedback(2, "pricing unclear").developments == ["Pricing unclear."]
    assert score_based_feedback(4, "nailed it").strengths == ["nailed it"]
