from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from f2f.genai import GenAIClient, GenAIError
from f2f.ics import build_ics
from f2f.scenario import fill, placeholders
from f2f.senders.base import CalendarInvite
from tests.conftest import login, make_settings


def test_placeholders_detected_once_in_order() -> None:
    text = "Hi [Merchant Name], meet [Sales Manager Name] and [Merchant Name] team. [ ]"
    assert placeholders(text) == ["Merchant Name", "Sales Manager Name"]
    assert fill(text, {"Merchant Name": "Acme"}) == "Hi Acme, meet [Sales Manager Name] and Acme team. [ ]"


def test_seeded_digital_scenario_placeholders(client: TestClient) -> None:
    login(client)
    page = client.get("/admin/f2f/new?pillar=Digital").text
    for tok in ["Merchant Name", "Sales Manager Name", "CTO Name", "Developer Name", "Project Manager Name"]:
        assert f"[{tok}]" in page


def test_template_edit_persists(client: TestClient, tmp_path: Path) -> None:
    login(client)
    page = client.get("/admin/templates/UC")
    assert page.status_code == 200
    data = {
        "scenario": "New [Thing] scenario",
        "count": "1",
        "q-0-id": "q1",
        "q-0-section": "S",
        "q-0-text": "Only question",
        "q-0-priority": "3",
        "q-0-desc1": "",
        "q-0-desc3": "ok",
        "q-0-desc5": "great",
        "threshold-IE1": "5",
        "threshold-IE2": "10",
        "threshold-Senior IE": "15",
    }
    r = client.post("/admin/templates/UC", data=data, follow_redirects=False)
    assert r.status_code == 303
    stored = json.loads((tmp_path / "templates.json").read_text())
    uc = next(p for p in stored["pillars"] if p["key"] == "UC")
    assert uc["scenario"] == "New [Thing] scenario"
    assert [q["priority"] for q in uc["questions"]] == [3]
    assert uc["thresholds"]["IE2"] == 10


def test_ics_has_zoom_and_attendees() -> None:
    inv = CalendarInvite(
        summary="F2F – C – Digital",
        description="line1\nline2",
        location="https://zoom.us/j/1",
        start_local="2026-11-10T14:00:00",
        end_local="2026-11-10T15:00:00",
        time_zone="Europe/Amsterdam",
        attendees=["a@x.com", "b@x.com"],
        zoom_link="https://zoom.us/j/1",
    )
    ics = build_ics(inv, "tl@x.com")
    assert "DTSTART:20261110T130000Z" in ics
    assert "ATTENDEE;ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:b@x.com" in ics
    assert "URL:https://zoom.us/j/1" in ics


def test_genai_client_success_and_errors(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer k"
        body = json.loads(request.content)
        if "fail" in body["messages"][1]["content"]:
            return httpx.Response(500)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '<think>x</think>{"summary": "ok"}'}}]}
        )

    ai = GenAIClient(
        make_settings(tmp_path, genai_platform_api_key="k"), transport=httpx.MockTransport(handler)
    )
    assert asyncio.run(ai.chat_json("s", "hello")) == {"summary": "ok"}
    with pytest.raises(GenAIError):
        asyncio.run(ai.chat("s", "fail"))
    no_key = GenAIClient(make_settings(tmp_path))
    assert not no_key.available
    with pytest.raises(GenAIError):
        asyncio.run(no_key.chat("s", "u"))


def test_priority_labels_and_legacy_weight() -> None:
    from f2f.models import Question

    assert (
        Question.model_validate({"id": "a", "section": "S", "text": "T", "weight": 3}).priority_label
        == "High"
    )
    assert Question(id="b", section="S", text="T", priority=1).priority_label == "Low"
    dumped = Question(id="c", section="S", text="T", priority=2).model_dump()
    assert dumped["priority"] == 2 and "weight" not in dumped


def _analysis_fixture(tmp_path: Path, reply: dict[str, object] | None) -> tuple[GenAIClient, object, object]:
    from f2f.models import F2F, Assessment, PillarTemplate, Question

    def handler(request: httpx.Request) -> httpx.Response:
        if reply is None:
            return httpx.Response(500)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    t = PillarTemplate(
        key="Digital",
        scenario="x",
        thresholds={"IE1": 1, "IE2": 2, "Senior IE": 3},
        questions=[
            Question(id="q1", section="Knowledge & Expertise", text="Tech", priority=3),
            Question(id="q2", section="Personal Skills", text="Comms", priority=2),
        ],
    )
    f = F2F(
        template=t, ie_level="IE1", candidate_name="C", candidate_email="c@x.com", date="2026-11-10",
        start_time="10:00", tl_name="T", tl_email="t@x.com",
    )  # fmt: skip
    a = Assessment(
        scores={"q1": 4, "q2": 2},
        notes={"q1": "Explained tokenisation well but missed refunds", "q2": "Rushed"},
    )
    ai = GenAIClient(
        make_settings(tmp_path, genai_platform_api_key="k"), transport=httpx.MockTransport(handler)
    )
    return ai, f, a


def test_ai_classifies_notes_per_scoring(tmp_path: Path) -> None:
    from f2f.drafting import analyse_notes

    reply = {
        "summary": "Strong grasp of payments, weaker pacing.",
        "questions": {
            "q1": {"strengths": ["Explained tokenisation clearly"], "developments": ["Missed refunds"]},
            # a 2 with no development point contradicts the score, so the score decides
            "q2": {"strengths": ["Calm"], "developments": []},
        },
    }
    ai, f, a = _analysis_fixture(tmp_path, reply)
    summary, fb = asyncio.run(analyse_notes(ai, f, a))  # type: ignore[arg-type]
    assert summary == "Strong grasp of payments, weaker pacing."
    assert fb["q1"].strengths == ["Explained tokenisation clearly"] and fb["q1"].developments == [
        "Missed refunds"
    ]
    assert fb["q2"].strengths == [] and fb["q2"].developments == ["Rushed."]


def test_ai_failure_falls_back_to_score(tmp_path: Path) -> None:
    from f2f.drafting import analyse_notes

    ai, f, a = _analysis_fixture(tmp_path, None)
    summary, fb = asyncio.run(analyse_notes(ai, f, a))  # type: ignore[arg-type]
    assert fb["q1"].strengths and not fb["q1"].developments
    assert fb["q2"].developments and not fb["q2"].strengths
    assert "pass mark" not in summary.lower() and " out of " not in summary


def test_seeded_uc_scenario_placeholders(client: TestClient) -> None:
    login(client)
    page = client.get("/admin/f2f/new?pillar=UC").text
    assert "Fit to Fly role play prompt" in page and "Terminal API" in page
    for tok in [
        "NAME",
        "DATE SCHEDULED",
        "Merchant Name",
        "Sales Manager Name",
        "CTO Name",
        "Developer Name",
        "Project Manager Name",
    ]:
        assert f"[{tok}]" in page


def test_seeded_pfs_scenario_placeholders(client: TestClient) -> None:
    login(client)
    page = client.get("/admin/f2f/new?pillar=P%26FS").text
    assert "Adyen for Platforms" in page and "signed the contract last week" in page
    for tok in [
        "NAME",
        "DATE SCHEDULED",
        "Merchant Name",
        "Sales Manager Name",
        "CTO Name",
        "Developer Name",
        "Project Manager Name",
    ]:
        assert f"[{tok}]" in page


def test_role_names_filled_from_panel(client: TestClient) -> None:
    from tests.conftest import create_f2f, svc

    login(client)
    page = client.get("/admin/f2f/new?pillar=Digital").text
    for tok in ("CTO Name", "Developer Name", "Project Manager Name"):
        assert f"[{tok}]</label>" not in page
    assert "[Sales Manager Name]</label>" in page
    f2f_id = create_f2f(
        client,
        **{
            "ph-1": "Sam Sales",
            "panel-2-name": "Paula PM",
            "panel-2-email": "pm@example.com",
            "panel-2-role": "PM",
        },
    )
    f = svc(client).store.get(f2f_id)
    assert f
    brief = fill(f.template.scenario, f.placeholders)
    assert "their CTO, Pat One," in brief
    assert "their developer, Dev Two," in brief
    assert "Project Manager Paula PM." in brief
    assert "Casey Candidate" not in brief and "Tara Lead" not in brief
    assert "from the Sales Manager Sam Sales." in brief
    assert "the merchant Acme Shoes, which we've been trying to poach" in brief
    assert "sales manager" not in brief and " PM " not in brief
    assert "from the merchants side." in brief and "never done a PSP" not in brief


def test_name_and_date_filled_for_uc_and_pfs(client: TestClient) -> None:
    from tests.conftest import F2F_FORM, create_f2f, svc

    login(client)
    for pillar in ("UC", "P&FS"):
        page = client.get(f"/admin/f2f/new?pillar={pillar}").text
        for tok in ("NAME", "DATE SCHEDULED", "CTO Name", "Developer Name", "Project Manager Name"):
            assert f"[{tok}]</label>" not in page
        f = svc(client).store.get(create_f2f(client, pillar=pillar))
        assert f and F2F_FORM["date"] == "2026-11-10"
        brief = fill(f.template.scenario, f.placeholders)
        assert "Hi Casey Candidate," in brief and "Tuesday 10 November 2026" in brief
        assert "[NAME]" not in brief and "[DATE SCHEDULED]" not in brief


def test_auto_placeholders_hidden_in_admin_views(client: TestClient) -> None:
    login(client)
    new = client.get("/admin/f2f/new?pillar=Digital").text
    assert "is filled from" not in new
    editor = client.get("/admin/templates/Digital").text
    assert "<code>[Merchant Name]</code>" in editor
    assert "<code>[CTO Name]</code>" not in editor and "<code>[Project Manager Name]</code>" not in editor
