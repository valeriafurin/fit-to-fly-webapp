from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from f2f.config import Settings
from f2f.senders.base import CalendarInvite, EmailMessage, SendResult
from f2f.web.app import Services, create_app

PASSCODE = "test-passcode"


class RecordingSender:
    name = "recording"

    def __init__(self) -> None:
        self.emails: list[EmailMessage] = []
        self.invites: list[CalendarInvite] = []

    async def send_email(self, message: EmailMessage) -> SendResult:
        self.emails.append(message)
        return SendResult(external_id=f"msg-{len(self.emails)}")

    async def create_invite(self, invite: CalendarInvite) -> SendResult:
        self.invites.append(invite)
        return SendResult(external_id=f"evt-{len(self.invites)}")


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "templates_path": tmp_path / "templates.json",
        "sender_backend": "manual",
        "admin_passcode": PASSCODE,
        "genai_platform_api_key": None,
        "public_base_url": "http://testserver",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture
def client(tmp_path: Path, sender: RecordingSender) -> Iterator[TestClient]:
    app = create_app(make_settings(tmp_path), sender=sender)
    yield TestClient(app)


def svc(client: TestClient) -> Services:
    s = client.app.state.svc  # type: ignore[attr-defined]
    assert isinstance(s, Services)
    return s


def drain(client: TestClient) -> None:
    asyncio.run(svc(client).jobs.drain())


def login(client: TestClient) -> None:
    r = client.post("/login", data={"passcode": PASSCODE}, follow_redirects=False)
    assert r.status_code == 303


F2F_FORM = {
    "pillar": "Digital",
    "ie_level": "IE1",
    "candidate_name": "Casey Candidate",
    "candidate_email": "casey@example.com",
    "date": "2026-11-10",
    "start_time": "14:00",
    "duration_minutes": "60",
    "time_zone": "Europe/Amsterdam",
    "zoom_link": "https://adyen.zoom.us/j/123456789",
    "tl_name": "Tara Lead",
    "tl_email": "tara@example.com",
    "panel_count": "3",
    "panel-0-name": "Pat One",
    "panel-0-email": "pat@example.com",
    "panel-0-role": "CTO",
    "panel-1-name": "Dev Two",
    "panel-1-email": "dev@example.com",
    "panel-1-role": "Developer",
    "panel-2-name": "",
    "panel-2-email": "",
    "ph-0": "Acme Shoes",
}


def create_f2f(client: TestClient, **overrides: str) -> str:
    login(client)
    data = {**F2F_FORM, **overrides}
    r = client.post(
        "/admin/f2f",
        data=data,
        files={"rollout_plan": ("plan.pdf", b"%PDF-1.4 plan", "application/pdf")},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    m = re.match(r"/admin/f2f/(\w+)$", r.headers["location"])
    assert m
    return m.group(1)


def score_form(client: TestClient, f2f_id: str, score: int, notes: str = "good") -> dict[str, str]:
    f = svc(client).store.get(f2f_id)
    assert f
    data: dict[str, str] = {}
    for q in f.template.questions:
        data[f"score-{q.id}"] = str(score)
        data[f"notes-{q.id}"] = notes
    return data
