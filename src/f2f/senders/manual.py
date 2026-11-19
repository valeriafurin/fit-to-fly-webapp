from __future__ import annotations

from f2f.senders.base import CalendarInvite, EmailMessage, ManualOnly, SendResult


class ManualSender:
    name = "manual"

    async def send_email(self, message: EmailMessage) -> SendResult:
        raise ManualOnly("Use the Gmail compose link and attach the files")

    async def create_invite(self, invite: CalendarInvite) -> SendResult:
        raise ManualOnly("Download the .ics file and send it from your calendar")
