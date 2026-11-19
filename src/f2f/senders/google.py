from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from typing import Any

import httpx

from f2f.senders.base import CalendarInvite, EmailMessage, SendError, SendResult

log = logging.getLogger(__name__)

GMAIL_SEND = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
CALENDAR_INSERT = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
TOKEN_URL = "https://oauth2.googleapis.com/token"


@dataclass
class GoogleToken:
    email: str
    access_token: str
    refresh_token: str | None
    expires_at: float


class GoogleTokenStore:
    """Holds the signed-in TL's OAuth token in memory only."""

    def __init__(self, client_id: str | None, client_secret: str | None) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.current: GoogleToken | None = None

    async def access_token(self) -> str:
        tok = self.current
        if tok is None:
            raise SendError("No TL is signed in with Google")
        if tok.expires_at - 60 > time.time():
            return tok.access_token
        if not tok.refresh_token:
            raise SendError("Google session expired; sign in again")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": tok.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        if resp.status_code != 200:
            raise SendError("Could not refresh the Google token; sign in again")
        data = resp.json()
        tok.access_token = data["access_token"]
        tok.expires_at = time.time() + int(data.get("expires_in", 3600))
        return tok.access_token


def build_mime(message: EmailMessage) -> str:
    mime = MimeMessage()
    mime["To"] = ", ".join(message.to)
    if message.cc:
        mime["Cc"] = ", ".join(message.cc)
    mime["Subject"] = message.subject
    mime.set_content(message.body_text)
    mime.add_alternative(message.body_html, subtype="html")
    for att in message.attachments:
        maintype, _, subtype = att.mime_type.partition("/")
        mime.add_attachment(
            att.content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=att.filename,
        )
    return base64.urlsafe_b64encode(mime.as_bytes()).decode()


def event_body(invite: CalendarInvite, with_conference: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "summary": invite.summary,
        "description": invite.description,
        "location": invite.location,
        "start": {"dateTime": invite.start_local, "timeZone": invite.time_zone},
        "end": {"dateTime": invite.end_local, "timeZone": invite.time_zone},
        "attendees": [{"email": a} for a in invite.attendees],
    }
    if with_conference and invite.zoom_link:
        body["conferenceData"] = {
            "conferenceSolution": {"key": {"type": "addOn"}, "name": "Zoom"},
            "entryPoints": [{"entryPointType": "video", "uri": invite.zoom_link}],
        }
    return body


class GoogleSender:
    name = "google"

    def __init__(self, tokens: GoogleTokenStore, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.tokens = tokens
        self.transport = transport

    async def _post(self, url: str, json_body: dict[str, Any], params: dict[str, str] | None = None) -> Any:
        token = await self.tokens.access_token()
        async with httpx.AsyncClient(timeout=60, transport=self.transport) as client:
            resp = await client.post(
                url, json=json_body, params=params, headers={"Authorization": f"Bearer {token}"}
            )
        if resp.status_code >= 300:
            log.warning("Google API returned HTTP %s", resp.status_code)
            raise SendError(f"Google API returned HTTP {resp.status_code}")
        return resp.json()

    async def send_email(self, message: EmailMessage) -> SendResult:
        data = await self._post(GMAIL_SEND, {"raw": build_mime(message)})
        return SendResult(external_id=str(data.get("id")))

    async def create_invite(self, invite: CalendarInvite) -> SendResult:
        params = {"conferenceDataVersion": "1", "sendUpdates": "all"}
        try:
            data = await self._post(CALENDAR_INSERT, event_body(invite, True), params)
        except SendError:
            # Calendar rejects addOn conference data unless a Zoom add-on is installed for the domain;
            # the link is still in location and description.
            data = await self._post(CALENDAR_INSERT, event_body(invite, False), params)
        return SendResult(external_id=str(data.get("id")))
