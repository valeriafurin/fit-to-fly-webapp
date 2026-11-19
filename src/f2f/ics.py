from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from f2f.models import new_id
from f2f.senders.base import CalendarInvite


def to_utc(local_iso: str, tz: str) -> datetime:
    return datetime.fromisoformat(local_iso).replace(tzinfo=ZoneInfo(tz)).astimezone(UTC)


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    out, cur = [], line
    while len(cur.encode()) > 74:
        cut = 74
        while len(cur[:cut].encode()) > 74:
            cut -= 1
        out.append(cur[:cut])
        cur = " " + cur[cut:]
    out.append(cur)
    return "\r\n".join(out)


def google_calendar_url(invite: CalendarInvite) -> str:
    """Manual fallback: opens a pre-filled Google Calendar event for the TL to review and send."""
    fmt = "%Y%m%dT%H%M%SZ"
    start, end = to_utc(invite.start_local, invite.time_zone), to_utc(invite.end_local, invite.time_zone)
    details = invite.description
    if len(details) > 2500:  # keep the URL within browser limits
        details = details[:2500].rstrip() + "…"
    params = {
        "action": "TEMPLATE",
        "text": invite.summary,
        "dates": f"{start.strftime(fmt)}/{end.strftime(fmt)}",
        "details": details,
        "location": invite.location,
        "add": ",".join(invite.attendees),
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(params)


def build_ics(invite: CalendarInvite, organizer: str) -> str:
    fmt = "%Y%m%dT%H%M%SZ"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Adyen//F2F Assessment//EN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{new_id()}@f2f-assessment",
        f"DTSTAMP:{datetime.now(UTC).strftime(fmt)}",
        f"DTSTART:{to_utc(invite.start_local, invite.time_zone).strftime(fmt)}",
        f"DTEND:{to_utc(invite.end_local, invite.time_zone).strftime(fmt)}",
        f"SUMMARY:{_esc(invite.summary)}",
        f"LOCATION:{_esc(invite.location)}",
        f"DESCRIPTION:{_esc(invite.description)}",
        f"ORGANIZER:mailto:{organizer}",
    ]
    lines += [f"ATTENDEE;ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:{a}" for a in invite.attendees]
    if invite.zoom_link:
        lines.append(f"URL:{invite.zoom_link}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
