from __future__ import annotations

from typing import Protocol
from urllib.parse import urlencode

from pydantic import BaseModel, Field

from f2f.models import Attachment


class EmailMessage(BaseModel):
    to: list[str]
    cc: list[str] = Field(default_factory=list)
    subject: str
    body_html: str
    body_text: str
    attachments: list[Attachment] = Field(default_factory=list)


class CalendarInvite(BaseModel):
    summary: str
    description: str
    location: str
    start_local: str  # ISO "YYYY-MM-DDTHH:MM:00", wall time in time_zone
    end_local: str
    time_zone: str
    attendees: list[str]
    zoom_link: str = ""


class SendResult(BaseModel):
    external_id: str | None = None
    attachments_pending: bool = False
    note: str = ""


class SendError(RuntimeError):
    pass


class ManualOnly(RuntimeError):
    """The backend does not send; the TL completes the action with the manual fallbacks."""


class Sender(Protocol):
    name: str

    async def send_email(self, message: EmailMessage) -> SendResult: ...

    async def create_invite(self, invite: CalendarInvite) -> SendResult: ...


def gmail_compose_url(message: EmailMessage) -> str:
    params = {
        "view": "cm",
        "fs": "1",
        "to": ",".join(message.to),
        "su": message.subject,
        "body": message.body_text,
    }
    if message.cc:
        params["cc"] = ",".join(message.cc)
    return "https://mail.google.com/mail/?" + urlencode(params)
