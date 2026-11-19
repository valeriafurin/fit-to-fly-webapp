from __future__ import annotations

import asyncio
import base64
import email
import json
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from f2f.models import Attachment
from f2f.senders.base import CalendarInvite, EmailMessage
from f2f.senders.google import GoogleSender, GoogleToken, GoogleTokenStore
from f2f.web.app import create_app
from tests.conftest import make_settings


def _tokens() -> GoogleTokenStore:
    store = GoogleTokenStore("cid", "secret")
    store.current = GoogleToken("tl@adyen.com", "access", None, time.time() + 3600)
    return store


def test_gmail_mime_includes_attachment() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["raw"] = json.loads(request.content)["raw"]
        return httpx.Response(200, json={"id": "m1"})

    sender = GoogleSender(_tokens(), transport=httpx.MockTransport(handler))
    msg = EmailMessage(
        to=["a@x.com"],
        cc=["tl@x.com"],
        subject="Results",
        body_html="<p>Hi</p>",
        body_text="Hi",
        attachments=[Attachment(filename="r.pdf", content=b"%PDF-1.7 data", mime_type="application/pdf")],
    )
    result = asyncio.run(sender.send_email(msg))
    assert result.external_id == "m1" and not result.attachments_pending
    assert seen["auth"] == "Bearer access"
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(str(seen["raw"])))
    assert parsed["To"] == "a@x.com" and parsed["Cc"] == "tl@x.com"
    parts = {p.get_filename(): p.get_payload(decode=True) for p in parsed.walk() if p.get_filename()}
    assert parts == {"r.pdf": b"%PDF-1.7 data"}


def test_calendar_retries_without_zoom_addon() -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append({"params": dict(request.url.params), "body": body})
        if "conferenceData" in body:
            return httpx.Response(400, json={"error": "invalid conference"})
        return httpx.Response(200, json={"id": "evt1"})

    inv = CalendarInvite(
        summary="F2F – C – UC",
        description="d",
        location="https://zoom.us/j/1",
        start_local="2026-11-10T14:00:00",
        end_local="2026-11-10T15:00:00",
        time_zone="Europe/Amsterdam",
        attendees=["a@x.com"],
        zoom_link="https://zoom.us/j/1",
    )
    result = asyncio.run(GoogleSender(_tokens(), transport=httpx.MockTransport(handler)).create_invite(inv))
    assert result.external_id == "evt1"
    assert len(calls) == 2
    first = calls[0]["body"]
    assert isinstance(first, dict)
    assert first["conferenceData"]["entryPoints"][0]["uri"] == "https://zoom.us/j/1"
    assert calls[1]["params"] == {"conferenceDataVersion": "1", "sendUpdates": "all"}


def test_google_mode_login(tmp_path: Path) -> None:
    app = create_app(
        make_settings(
            tmp_path,
            sender_backend="google",
            google_client_id="cid",
            google_client_secret="s",
            tl_allowed_emails="tl@adyen.com",
        )
    )
    client = TestClient(app)
    assert client.post("/login", data={"passcode": "test-passcode"}).status_code == 403
    r = client.get("/auth/google/login", follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/") and "gmail.send" in loc and "calendar.events" in loc
    assert client.get("/auth/google/callback?code=x&state=forged", follow_redirects=False).status_code == 403
    assert client.get("/admin").status_code == 403
