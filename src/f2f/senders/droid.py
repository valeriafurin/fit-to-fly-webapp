from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from f2f.senders.base import CalendarInvite, EmailMessage, SendError, SendResult

log = logging.getLogger(__name__)

GMAIL_TOOL = "gmail__send_message"
CALENDAR_TOOL = "google_calendar__create_event"

PROMPT = (
    "You are a delivery relay. Read the JSON file at {path} with the Read tool. It has two keys: "
    '"tool" (the exact tool name) and "input" (the exact input object). Load that tool with ToolSearch '
    '(query "select:<tool>") and call it ONCE with the "input" object copied verbatim: do not change, '
    "summarise, translate or add any field, recipient or text. Use a short __summary such as "
    '"Send F2F assessment email". Do not call any other tool. When the call succeeds, reply with exactly '
    "one line: SENT_ID: <the message id or event id returned by the tool>. If it fails, reply with exactly "
    "one line: SEND_FAILED: <short error reason>."
)

REMOVED_TOOLS = (
    "Execute",
    "ApplyPatch",
    "Task",
    "Skill",
    "FetchUrl",
    "WebSearch",
    "Loop",
    "GenerateDroid",
    "CreateAutomation",
    "EditAutomation",
    "DeleteAutomation",
    "RunAutomation",
    "StageSettingsChanges",
    "ProposeMission",
    "StartMissionRun",
)

SENT_RE = re.compile(r"SENT_ID:\s*(\S+)")
FAILED_RE = re.compile(r"SEND_FAILED:\s*(.+)")


def gmail_input(message: EmailMessage) -> dict[str, Any]:
    return {
        "to": message.to,
        "cc": message.cc or None,
        "bcc": None,
        "subject": message.subject,
        "reply_to": None,
        "body_html": message.body_html,
        "body_text": message.body_text,
        "thread_id": None,
        "references": None,
        "attachments": None,
        "in_reply_to": None,
        "from_address": None,
        "file_reference": None,
        "file_reference_filename": None,
    }


def calendar_input(invite: CalendarInvite) -> dict[str, Any]:
    conference = None
    if invite.zoom_link:
        conference = {
            "notes": None,
            "signature": None,
            "conference_id": None,
            "create_request": None,
            "conference_solution": {"name": "Zoom", "icon_uri": None, "solution_type": "addOn"},
            "entry_points": [
                {
                    "uri": invite.zoom_link,
                    "entry_point_type": "video",
                    "label": None,
                    "pin": None,
                    "passcode": None,
                    "password": None,
                    "access_code": None,
                    "meeting_code": None,
                }
            ],
        }
    return {
        "summary": invite.summary,
        "description": invite.description,
        "location": invite.location,
        "start": {"date": None, "date_time": invite.start_local, "time_zone": invite.time_zone},
        "end": {"date": None, "date_time": invite.end_local, "time_zone": invite.time_zone},
        "attendees": [
            {
                "email": a,
                "comment": None,
                "optional": None,
                "resource": None,
                "display_name": None,
                "response_status": None,
                "additional_guests": None,
            }
            for a in invite.attendees
        ],
        "conference_data": conference,
        "send_updates": "all",
        "calendar_id": None,
        "status": None,
        "color_id": None,
        "event_id": None,
        "reminders": None,
        "event_type": None,
        "recurrence": None,
        "visibility": None,
        "transparency": None,
        "max_attendees": None,
        "guests_can_modify": None,
        "birthday_properties": None,
        "extended_properties": None,
        "supports_attachments": None,
        "focus_time_properties": None,
        "guests_can_invite_others": None,
        "out_of_office_properties": None,
        "guests_can_see_other_guests": None,
        "working_location_properties": None,
    }


class DroidSender:
    """Relays each send through `droid exec` and the user's Gmail/Calendar connectors.

    A headless droid session has no Script tool, so attachment bytes would have to be retyped by the
    model. Emails are therefore sent as text only and attachments are flagged for manual sending.
    """

    name = "droid"

    def __init__(self, droid_bin: str, auto: str, timeout: int, model: str | None = None) -> None:
        self.droid_bin = droid_bin
        self.auto = auto
        self.timeout = timeout
        self.model = model

    def command(self, job_path: Path) -> list[str]:
        # --only-tools hides ToolSearch and connector tools in headless sessions, so strip the
        # built-ins that could act on the machine or the web instead.
        cmd = [
            self.droid_bin,
            "exec",
            "--auto",
            self.auto,
            "--remove-tools",
            ",".join(REMOVED_TOOLS),
            "-o",
            "json",
        ]
        if self.model:
            cmd += ["-m", self.model]
        return [*cmd, PROMPT.format(path=job_path)]

    async def send_email(self, message: EmailMessage) -> SendResult:
        external_id = await self._run(GMAIL_TOOL, gmail_input(message))
        pending = bool(message.attachments)
        note = f"Attach {len(message.attachments)} file(s) manually" if pending else ""
        return SendResult(external_id=external_id, attachments_pending=pending, note=note)

    async def create_invite(self, invite: CalendarInvite) -> SendResult:
        return SendResult(external_id=await self._run(CALENDAR_TOOL, calendar_input(invite)))

    async def _run(self, tool: str, tool_input: dict[str, Any]) -> str:
        if shutil.which(self.droid_bin) is None and not Path(self.droid_bin).exists():
            raise SendError(f"droid CLI not found ({self.droid_bin})")
        workdir = Path(tempfile.mkdtemp(prefix="f2f-job-"))
        try:
            os.chmod(workdir, 0o700)
            job_path = workdir / "job.json"
            fd = os.open(job_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                json.dump({"tool": tool, "input": tool_input}, fh, ensure_ascii=False)
            proc = await asyncio.create_subprocess_exec(
                *self.command(job_path),
                cwd=workdir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
            except TimeoutError as exc:
                proc.kill()
                await proc.wait()
                raise SendError("droid exec timed out") from exc
            return parse_result(
                proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def parse_result(returncode: int | None, stdout: str, stderr: str) -> str:
    try:
        data = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else {}
    except json.JSONDecodeError:
        data = {}
    result = str(data.get("result", "")) if isinstance(data, dict) else ""
    if m := SENT_RE.search(result):
        return m.group(1).strip("`'\".,")
    if m := FAILED_RE.search(result):
        raise SendError(m.group(1).strip()[:200])
    if returncode != 0 or (isinstance(data, dict) and data.get("is_error")):
        log.warning("droid exec failed with exit code %s", returncode)
        # Droid's own status line (e.g. a permission refusal) is in "result"; it is shown to the TL, not logged.
        detail = result.strip() or stderr.strip()[-200:] or "no output"
        raise SendError(f"droid exec failed (exit {returncode}): {detail[:200]}")
    raise SendError("droid exec did not confirm the send")
