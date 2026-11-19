from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from f2f.models import Attachment
from f2f.senders.base import CalendarInvite, EmailMessage, SendError
from f2f.senders.droid import CALENDAR_TOOL, GMAIL_TOOL, DroidSender, parse_result

FAKE = """#!{python}
import json, os, re, sys
args = sys.argv[1:]
prompt = args[-1]
path = re.search(r"JSON file at (\\S+) with", prompt).group(1)
job = json.load(open(path))
st = os.stat(os.path.dirname(path)).st_mode & 0o777
log = {{"args": args, "job": job, "dir_mode": st, "path": path}}
open(os.environ["FAKE_DROID_LOG"], "w").write(json.dumps(log))
mode = os.environ.get("FAKE_DROID_MODE", "ok")
if mode == "ok":
    print(json.dumps({{"type": "result", "is_error": False, "result": "SENT_ID: abc123"}}))
elif mode == "fail":
    print(json.dumps({{"type": "result", "is_error": False, "result": "SEND_FAILED: connector not connected"}}))
else:
    sys.exit(3)
"""


@pytest.fixture
def fake_droid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    binary = tmp_path / "droid"
    binary.write_text(FAKE.format(python=sys.executable))
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "log.json"
    monkeypatch.setenv("FAKE_DROID_LOG", str(log))
    return binary, log


def _email(attachments: bool = False) -> EmailMessage:
    atts = [Attachment(filename="a.pdf", content=b"%PDF", mime_type="application/pdf")] if attachments else []
    return EmailMessage(
        to=["x@example.com"], subject="S", body_html="<p>H</p>", body_text="H", attachments=atts
    )


def test_email_job_building(fake_droid: tuple[Path, Path]) -> None:
    binary, log = fake_droid
    sender = DroidSender(str(binary), "low", 30)
    result = asyncio.run(sender.send_email(_email(attachments=True)))
    assert result.external_id == "abc123"
    assert result.attachments_pending
    data = json.loads(log.read_text())
    args = data["args"]
    assert args[:3] == ["exec", "--auto", "low"]
    removed = args[args.index("--remove-tools") + 1].split(",")
    assert {"Execute", "ApplyPatch", "Task", "FetchUrl"} <= set(removed)
    assert "--only-tools" not in args
    assert args[args.index("-o") + 1] == "json"
    assert data["job"]["tool"] == GMAIL_TOOL
    assert data["job"]["input"]["to"] == ["x@example.com"]
    assert data["job"]["input"]["attachments"] is None
    assert data["dir_mode"] == 0o700
    assert not os.path.exists(data["path"])


def test_invite_job_has_zoom_conference(fake_droid: tuple[Path, Path]) -> None:
    binary, log = fake_droid
    inv = CalendarInvite(
        summary="F2F – C – Digital",
        description="d",
        location="https://zoom.us/j/1",
        start_local="2026-11-10T14:00:00",
        end_local="2026-11-10T15:00:00",
        time_zone="Europe/Amsterdam",
        attendees=["a@x.com"],
        zoom_link="https://zoom.us/j/1",
    )
    asyncio.run(DroidSender(str(binary), "low", 30).create_invite(inv))
    job = json.loads(log.read_text())["job"]
    assert job["tool"] == CALENDAR_TOOL
    cd = job["input"]["conference_data"]
    assert cd["conference_solution"] == {"name": "Zoom", "icon_uri": None, "solution_type": "addOn"}
    assert cd["entry_points"][0]["uri"] == "https://zoom.us/j/1"
    assert job["input"]["send_updates"] == "all"


def test_failure_reported(fake_droid: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    binary, _ = fake_droid
    monkeypatch.setenv("FAKE_DROID_MODE", "fail")
    with pytest.raises(SendError, match="connector not connected"):
        asyncio.run(DroidSender(str(binary), "low", 30).send_email(_email()))
    monkeypatch.setenv("FAKE_DROID_MODE", "crash")
    with pytest.raises(SendError, match="exit 3"):
        asyncio.run(DroidSender(str(binary), "low", 30).send_email(_email()))


def test_missing_binary() -> None:
    with pytest.raises(SendError, match="not found"):
        asyncio.run(DroidSender("/nonexistent/droid", "low", 30).send_email(_email()))


def test_parse_result_surfaces_droid_refusal() -> None:
    out = json.dumps({"is_error": True, "result": "Exec ended early: insufficient permission to proceed."})
    with pytest.raises(SendError, match="insufficient permission"):
        parse_result(1, out, "")


def test_parse_result_requires_confirmation() -> None:
    with pytest.raises(SendError):
        parse_result(0, json.dumps({"result": "I sent it, probably"}), "")
    assert parse_result(0, json.dumps({"result": "SENT_ID: `m-1`"}), "") == "m-1"
