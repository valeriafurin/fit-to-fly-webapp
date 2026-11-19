from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from f2f.ics import google_calendar_url
from f2f.models import new_id, utcnow
from f2f.senders.base import CalendarInvite, EmailMessage, ManualOnly, Sender, SendError, gmail_compose_url

log = logging.getLogger(__name__)


class JobStatus(StrEnum):
    queued = "queued"
    sending = "sending"
    sent = "sent"
    failed = "failed"
    manual = "manual"


class Job(BaseModel):
    id: str = Field(default_factory=new_id)
    f2f_id: str
    label: str
    email: EmailMessage | None = None
    invite: CalendarInvite | None = None
    status: JobStatus = JobStatus.queued
    error: str = ""
    external_id: str | None = None
    attachments_pending: bool = False
    note: str = ""
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def kind(self) -> str:
        return "invite" if self.invite else "email"

    @property
    def compose_url(self) -> str | None:
        return gmail_compose_url(self.email) if self.email else None

    @property
    def calendar_url(self) -> str | None:
        return google_calendar_url(self.invite) if self.invite else None


class JobQueue:
    """Sequential background delivery. Logs carry job ids and statuses only, never content."""

    def __init__(self, sender: Sender) -> None:
        self.sender = sender
        self._jobs: dict[str, Job] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    def submit(self, job: Job) -> Job:
        self._jobs[job.id] = job
        self._queue.put_nowait(job.id)
        return job

    def retry(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job and job.status in (JobStatus.failed, JobStatus.manual):
            job.status, job.error, job.note = JobStatus.queued, "", ""
            self._queue.put_nowait(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def for_f2f(self, f2f_id: str) -> list[Job]:
        return sorted((j for j in self._jobs.values() if j.f2f_id == f2f_id), key=lambda j: j.created_at)

    def purge(self, f2f_id: str) -> None:
        for jid in [j.id for j in self._jobs.values() if j.f2f_id == f2f_id]:
            del self._jobs[jid]

    async def process(self, job: Job) -> None:
        job.status = JobStatus.sending
        try:
            if job.invite:
                result = await self.sender.create_invite(job.invite)
            elif job.email:
                result = await self.sender.send_email(job.email)
            else:
                raise SendError("Empty job")
        except ManualOnly as exc:
            job.status, job.note = JobStatus.manual, str(exc)
        except SendError as exc:
            job.status, job.error = JobStatus.failed, str(exc)
        except Exception as exc:
            log.exception("job %s crashed", job.id)
            job.status, job.error = JobStatus.failed, type(exc).__name__
        else:
            job.status = JobStatus.sent
            job.external_id = result.external_id
            job.attachments_pending = result.attachments_pending
            job.note = result.note
        log.info("job %s (%s) -> %s", job.id, job.kind, job.status.value)

    async def _run(self) -> None:
        while True:
            job_id = await self._queue.get()
            job = self._jobs.get(job_id)
            if job is not None and job.status == JobStatus.queued:
                await self.process(job)
            self._queue.task_done()

    async def drain(self) -> None:
        """Process everything queued now (used by tests and when no worker runs)."""
        while not self._queue.empty():
            job_id = self._queue.get_nowait()
            job = self._jobs.get(job_id)
            if job is not None and job.status == JobStatus.queued:
                await self.process(job)
            self._queue.task_done()
