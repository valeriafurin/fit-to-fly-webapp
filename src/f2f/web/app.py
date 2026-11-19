from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData, UploadFile

from f2f import scenario as scen
from f2f.auth import ADMIN_COOKIE, AdminSessions
from f2f.config import Settings, get_settings
from f2f.consistency import mismatch_warning
from f2f.drafting import draft_collated_page1, draft_page1, fallback_collated_page1
from f2f.genai import GenAIClient
from f2f.ics import build_ics
from f2f.jobs import Job, JobQueue, JobStatus
from f2f.messages import Messages, date_label, invite, pdf_filename, when
from f2f.models import (
    F2F,
    FEEDBACK_BLOCKS,
    IE_LEVELS,
    OUTCOMES,
    PANEL_ROLES,
    PRIORITY_LABELS,
    Assessment,
    Attachment,
    F2FStatus,
    FeedbackBlock,
    Page1,
    Panelist,
    PanelStatus,
    PillarTemplate,
    Question,
    utcnow,
)
from f2f.pdf import PdfRenderer, build_rows
from f2f.scoring import averages, collated_ratings, collated_score, score_assessment
from f2f.senders.base import Sender
from f2f.senders.droid import DroidSender
from f2f.senders.google import GoogleSender, GoogleToken, GoogleTokenStore
from f2f.senders.manual import ManualSender
from f2f.store import Store
from f2f.templates_repo import TemplateRepo

log = logging.getLogger("f2f")
WEB_DIR = Path(__file__).resolve().parent
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_FONTS = {
    "Adyen-Regular.otf",
    "Adyen-Medium.otf",
    "Adyen-Bold.otf",
    "Fakt-Normal.otf",
    "Fakt-SemiBold.otf",
    "Fakt-Blond.otf",
}
GOOGLE_SCOPES = (
    "openid email https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/calendar.events"
)


class Services:
    def __init__(self, settings: Settings, sender: Sender | None = None) -> None:
        self.settings = settings
        self.templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
        self.store = Store(settings.session_ttl_hours)
        self.repo = TemplateRepo(settings.templates_path)
        self.google_tokens = GoogleTokenStore(settings.google_client_id, settings.google_client_secret)
        self.sender: Sender = sender or self._make_sender()
        self.jobs = JobQueue(self.sender)
        self.ai = GenAIClient(settings)
        self.pdf = PdfRenderer(self.templates.env, settings.fonts_dir)
        self.messages = Messages(self.templates.env, settings.public_base_url)
        self.sessions = AdminSessions(settings.admin_passcode, settings.session_ttl_hours)
        self.store.on_purge.append(self.jobs.purge)

    def _make_sender(self) -> Sender:
        s = self.settings
        if s.sender_backend == "google":
            return GoogleSender(self.google_tokens)
        if s.sender_backend == "manual":
            return ManualSender()
        return DroidSender(s.droid_bin, s.droid_auto, s.droid_timeout_seconds, s.droid_model)


def require_admin(request: Request) -> str:
    svc: Services = request.app.state.svc
    who = svc.sessions.identity(request.cookies.get(ADMIN_COOKIE))
    if who is None:
        raise HTTPException(403, "TL sign-in required")
    return who


Admin = Annotated[str, Depends(require_admin)]


def create_app(settings: Settings | None = None, sender: Sender | None = None) -> FastAPI:
    settings = settings or get_settings()
    svc = Services(settings, sender)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        svc.jobs.start()

        async def purge_loop() -> None:
            while True:
                await asyncio.sleep(300)
                svc.store.purge_expired()

        purger = asyncio.create_task(purge_loop())
        if settings.sender_backend != "google":
            print(
                f"\n  F2F admin passcode: {svc.sessions.passcode}\n  Sign in at {settings.public_base_url}/login\n",
                flush=True,
            )
        yield
        purger.cancel()
        await svc.jobs.stop()

    app = FastAPI(title="F2F Assessment", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.svc = svc
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    tpl = svc.templates
    tpl.env.globals.update(
        # changes on every restart so browsers fetch fresh CSS/JS instead of a cached copy
        asset_version=str(int(time.time())),
        IE_LEVELS=IE_LEVELS,
        AUTO_PLACEHOLDERS=scen.AUTO_PLACEHOLDERS,
        OUTCOMES=OUTCOMES,
        PANEL_ROLES=PANEL_ROLES,
        FEEDBACK_BLOCKS=FEEDBACK_BLOCKS,
        PRIORITY_LABELS=PRIORITY_LABELS,
        backend=settings.sender_backend,
        ai_available=svc.ai.available,
    )

    def render(request: Request, name: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
        return tpl.TemplateResponse(request, name, ctx, status_code=status_code)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> Response:
        if request.headers.get("HX-Request"):
            return HTMLResponse(f'<div class="flash error">{exc.detail}</div>', status_code=exc.status_code)
        return render(
            request,
            "error.html",
            status_code=exc.status_code,
            code=exc.status_code,
            detail=exc.detail,
            show_login=exc.status_code == 403,
        )

    # ---------- auth ----------

    def set_admin_cookie(resp: Response, identity: str) -> None:
        resp.set_cookie(
            ADMIN_COOKIE,
            svc.sessions.create(identity),
            httponly=True,
            samesite="strict",
            secure=settings.secure_cookies,
            max_age=int(settings.session_ttl_hours * 3600),
        )

    @app.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse("/admin", 303)

    @app.get("/login")
    async def login_page(request: Request) -> HTMLResponse:
        return render(request, "login.html", google=settings.sender_backend == "google", error=None)

    @app.post("/login")
    async def login(request: Request, passcode: Annotated[str, Form()]) -> Response:
        if settings.sender_backend == "google":
            raise HTTPException(403, "Sign in with Google")
        if not svc.sessions.check_passcode(passcode):
            await asyncio.sleep(1)
            return render(request, "login.html", status_code=401, google=False, error="Wrong passcode")
        resp = RedirectResponse("/admin", 303)
        set_admin_cookie(resp, "tl")
        return resp

    @app.post("/logout")
    async def logout(request: Request) -> RedirectResponse:
        svc.sessions.destroy(request.cookies.get(ADMIN_COOKIE))
        resp = RedirectResponse("/login", 303)
        resp.delete_cookie(ADMIN_COOKIE)
        return resp

    @app.get("/auth/google/login")
    async def google_login() -> RedirectResponse:
        if not settings.google_client_id:
            raise HTTPException(404, "Google sign-in is not configured")
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": f"{settings.public_base_url}/auth/google/callback",
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": svc.sessions.new_state(),
        }
        return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params), 303)

    @app.get("/auth/google/callback")
    async def google_callback(code: str = "", state: str = "") -> RedirectResponse:
        if not code or not svc.sessions.consume_state(state):
            raise HTTPException(403, "Invalid sign-in state")
        async with httpx.AsyncClient(timeout=30) as client:
            tok = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": f"{settings.public_base_url}/auth/google/callback",
                    "grant_type": "authorization_code",
                },
            )
            if tok.status_code != 200:
                raise HTTPException(403, "Google sign-in failed")
            data = tok.json()
            info = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {data['access_token']}"},
            )
        email = str(info.json().get("email", "")).lower() if info.status_code == 200 else ""
        if not email or email not in settings.allowed_tl_emails:
            raise HTTPException(403, "This Google account is not an allowed TL")
        svc.google_tokens.current = GoogleToken(
            email,
            data["access_token"],
            data.get("refresh_token"),
            time.time() + int(data.get("expires_in", 3600)),
        )
        resp = RedirectResponse("/admin", 303)
        set_admin_cookie(resp, email)
        return resp

    @app.get("/fonts/{name}")
    async def font(name: str) -> Response:
        path = settings.fonts_dir / name
        if name not in ALLOWED_FONTS or not path.exists():
            raise HTTPException(404, "Font not found")
        return Response(path.read_bytes(), media_type="font/otf", headers={"Cache-Control": "max-age=86400"})

    # ---------- helpers ----------

    def get_f2f(f2f_id: str) -> F2F:
        f = svc.store.get(f2f_id)
        if f is None:
            raise HTTPException(404, "F2F not found (it may have been purged)")
        return f

    def get_template(key: str) -> PillarTemplate:
        t = svc.repo.get(key)
        if t is None:
            raise HTTPException(404, "Unknown pillar")
        return t

    def submit_job(f: F2F, label: str, **payload: Any) -> Job:
        return svc.jobs.submit(Job(f2f_id=f.id, label=label, **payload))

    def page1_from_form(form: FormData, prefix: str = "p1-") -> Page1:
        def g(k: str) -> str:
            return str(form.get(prefix + k, "") or "")

        blocks = {
            key: FeedbackBlock(strengths=g(f"{key}-strengths"), development=g(f"{key}-development"))
            for key, _ in FEEDBACK_BLOCKS
        }
        return Page1(
            overall_evaluation=g("overall"),
            outcome=g("outcome"),
            summary=g("summary"),
            technical=blocks["technical"],
            discovery=blocks["discovery"],
            communication=blocks["communication"],
        )

    # ---------- TL: home + templates ----------

    @app.get("/admin")
    async def admin_home(request: Request, _: Admin) -> HTMLResponse:
        return render(request, "admin/home.html", f2fs=svc.store.all(), pillars=svc.repo.all(), jobs=svc.jobs)

    @app.get("/admin/templates/{key}")
    async def template_edit(request: Request, key: str, _: Admin, saved: int = 0) -> HTMLResponse:
        t = get_template(key)
        return render(
            request, "admin/template_edit.html", t=t, saved=saved, tokens=scen.placeholders(t.scenario)
        )

    @app.post("/admin/templates/{key}")
    async def template_save(request: Request, key: str, _: Admin) -> Response:
        t = get_template(key)
        form = await request.form()
        questions: list[Question] = []
        count = int(str(form.get("count", "0")))
        for i in range(count):
            if form.get(f"q-{i}-delete"):
                continue
            text = str(form.get(f"q-{i}-text", "")).strip()
            if not text:
                continue
            try:
                priority = min(
                    max(PRIORITY_LABELS),
                    max(min(PRIORITY_LABELS), int(str(form.get(f"q-{i}-priority", "2")))),
                )
            except ValueError:
                priority = 2
            questions.append(
                Question(
                    id=str(form.get(f"q-{i}-id") or f"q{secrets.token_hex(3)}"),
                    section=str(form.get(f"q-{i}-section", "")).strip() or "General",
                    text=text,
                    priority=priority,
                    tag=str(form.get(f"q-{i}-tag", "All")).strip() or "All",
                    desc1=str(form.get(f"q-{i}-desc1", "")).strip(),
                    desc3=str(form.get(f"q-{i}-desc3", "")).strip(),
                    desc5=str(form.get(f"q-{i}-desc5", "")).strip(),
                )
            )
        if form.get("add"):
            questions.append(
                Question(
                    id=f"q{secrets.token_hex(3)}", section="New section", text="New question", priority=2
                )
            )
        thresholds = {}
        for lvl in IE_LEVELS:
            try:
                thresholds[lvl] = int(str(form.get(f"threshold-{lvl}", t.thresholds.get(lvl, 0))))
            except ValueError:
                thresholds[lvl] = t.thresholds.get(lvl, 0)
        svc.repo.save(
            PillarTemplate(
                key=t.key,
                scenario=str(form.get("scenario", t.scenario)),
                questions=questions,
                thresholds=thresholds,
            )
        )
        return RedirectResponse(f"/admin/templates/{request.path_params['key']}?saved=1", 303)

    # ---------- TL: create F2F ----------

    @app.get("/admin/f2f/new")
    async def f2f_new(request: Request, _: Admin, pillar: str = "Digital") -> HTMLResponse:
        t = get_template(pillar)
        return render(
            request,
            "admin/f2f_new.html",
            t=t,
            pillars=svc.repo.all(),
            tokens=scen.placeholders(t.scenario),
            error=None,
        )

    @app.post("/admin/f2f")
    async def f2f_create(request: Request, _: Admin) -> Response:
        form = await request.form()
        t = get_template(str(form.get("pillar", "")))

        def g(k: str) -> str:
            return str(form.get(k, "") or "").strip()

        panel = []
        for i in range(int(g("panel_count") or 0)):
            name, email = g(f"panel-{i}-name"), g(f"panel-{i}-email")
            if name and email:
                role = g(f"panel-{i}-role")
                panel.append(
                    Panelist(name=name, email=email, role=role if role in PANEL_ROLES else "Observer")
                )
        required = {
            "candidate_name": "Candidate name",
            "candidate_email": "Candidate email",
            "date": "Date",
            "start_time": "Start time",
            "tl_name": "TL name",
            "tl_email": "TL email",
        }
        missing = [label for k, label in required.items() if not g(k)]
        if g("ie_level") not in IE_LEVELS:
            missing.append("IE level")
        if not panel:
            missing.append("at least one panelist")
        if missing:
            return render(
                request,
                "admin/f2f_new.html",
                status_code=400,
                t=t,
                pillars=svc.repo.all(),
                tokens=scen.placeholders(t.scenario),
                error="Missing: " + ", ".join(missing),
            )
        rollout: Attachment | None = None
        upload = form.get("rollout_plan")
        if isinstance(upload, UploadFile) and upload.filename:
            content = await upload.read(MAX_UPLOAD_BYTES + 1)
            if len(content) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "Roll-out plan is larger than 15 MB")
            if content:
                rollout = Attachment(
                    filename=upload.filename,
                    content=content,
                    mime_type=upload.content_type or "application/octet-stream",
                )
        try:
            duration = int(g("duration_minutes") or 60)
        except ValueError:
            duration = 60

        def played_by(role: str) -> str:
            return " and ".join(p.name for p in panel if p.role == role)

        auto = {
            "CTO Name": played_by("CTO"),
            "Developer Name": played_by("Developer"),
            "Project Manager Name": played_by("PM"),
            "TL Name": g("tl_name"),
            "IE Name": g("candidate_name"),
            "NAME": g("candidate_name"),
            "DATE SCHEDULED": date_label(g("date")),
        }
        f = F2F(
            template=t,
            ie_level=g("ie_level"),
            candidate_name=g("candidate_name"),
            candidate_email=g("candidate_email"),
            date=g("date"),
            start_time=g("start_time"),
            duration_minutes=duration,
            time_zone=g("time_zone") or "Europe/Amsterdam",
            zoom_link=g("zoom_link"),
            tl_name=g("tl_name"),
            tl_email=g("tl_email"),
            panelists=panel,
            placeholders={
                tok: auto[tok] if tok in auto else g(f"ph-{i}")
                for i, tok in enumerate(scen.placeholders(t.scenario))
            },
            rollout_plan=rollout,
        )
        svc.store.add(f)
        # The calendar invite is created automatically. If the backend can't send it (manual backend,
        # or a failure), the dashboard offers the .ics and Google Calendar link as the manual fallback.
        submit_job(f, "Calendar invite (candidate, panel, TL)", invite=invite(f))
        return RedirectResponse(f"/admin/f2f/{f.id}", 303)

    # ---------- TL: dashboard ----------

    @app.get("/admin/f2f/{f2f_id}")
    async def dashboard(request: Request, f2f_id: str, _: Admin) -> HTMLResponse:
        f = get_f2f(f2f_id)
        return render(
            request,
            "admin/dashboard.html",
            f=f,
            brief=scen.fill(f.template.scenario, f.placeholders),
            when=when(f),
            jobs=svc.jobs.for_f2f(f.id),
            links={p.id: svc.messages.panel_link(p) for p in f.panelists},
            scores={p.id: score_assessment(f, p.assessment) for p in f.panelists},
            checked_at=utcnow().strftime("%H:%M:%S"),
        )

    @app.get("/admin/f2f/{f2f_id}/panel")
    async def panel_partial(request: Request, f2f_id: str, _: Admin) -> HTMLResponse:
        """Fetched by the dashboard's "Check for updates" button to show new scores without a reload."""
        f = get_f2f(f2f_id)
        return render(
            request,
            "partials/panel_status.html",
            f=f,
            links={p.id: svc.messages.panel_link(p) for p in f.panelists},
            scores={p.id: score_assessment(f, p.assessment) for p in f.panelists},
            checked_at=utcnow().strftime("%H:%M:%S"),
        )

    @app.get("/admin/f2f/{f2f_id}/jobs")
    async def jobs_partial(request: Request, f2f_id: str, _: Admin) -> HTMLResponse:
        f = get_f2f(f2f_id)
        return render(request, "partials/jobs.html", f=f, jobs=svc.jobs.for_f2f(f.id))

    @app.post("/admin/f2f/{f2f_id}/invite")
    async def send_invites(f2f_id: str, _: Admin) -> RedirectResponse:
        f = get_f2f(f2f_id)
        if not any(j.invite for j in svc.jobs.for_f2f(f.id)):
            submit_job(f, "Calendar invite (candidate, panel, TL)", invite=invite(f))
        submit_job(f, f"Brief to candidate {f.candidate_name}", email=svc.messages.candidate(f))
        for p in f.panelists:
            submit_job(f, f"Panel link to {p.name}", email=svc.messages.panelist(f, p))
        if f.status == F2FStatus.draft:
            f.status = F2FStatus.invited
        return RedirectResponse(f"/admin/f2f/{f.id}", 303)

    @app.post("/admin/f2f/{f2f_id}/jobs/{job_id}/retry")
    async def retry_job(request: Request, f2f_id: str, job_id: str, _: Admin) -> HTMLResponse:
        f = get_f2f(f2f_id)
        job = svc.jobs.get(job_id)
        if job is None or job.f2f_id != f.id:
            raise HTTPException(404, "Job not found")
        svc.jobs.retry(job_id)
        return render(request, "partials/jobs.html", f=f, jobs=svc.jobs.for_f2f(f.id))

    @app.get("/admin/f2f/{f2f_id}/jobs/{job_id}/invite.ics")
    async def job_ics(f2f_id: str, job_id: str, _: Admin) -> Response:
        f = get_f2f(f2f_id)
        job = svc.jobs.get(job_id)
        if job is None or job.f2f_id != f.id or job.invite is None:
            raise HTTPException(404, "Invite not found")
        return Response(
            build_ics(job.invite, f.tl_email),
            media_type="text/calendar",
            headers={"Content-Disposition": 'attachment; filename="f2f-invite.ics"'},
        )

    @app.get("/admin/f2f/{f2f_id}/jobs/{job_id}/attachment/{idx}")
    async def job_attachment(f2f_id: str, job_id: str, idx: int, _: Admin) -> Response:
        f = get_f2f(f2f_id)
        job = svc.jobs.get(job_id)
        if (
            job is None
            or job.f2f_id != f.id
            or job.email is None
            or not 0 <= idx < len(job.email.attachments)
        ):
            raise HTTPException(404, "Attachment not found")
        att = job.email.attachments[idx]
        return attachment_response(att.content, att.filename, att.mime_type)

    @app.get("/admin/f2f/{f2f_id}/panelist/{pid}/pdf")
    async def admin_panel_pdf(f2f_id: str, pid: str, _: Admin) -> Response:
        f = get_f2f(f2f_id)
        p = f.panelist(pid)
        if p is None or p.pdf is None:
            raise HTTPException(404, "PDF not available")
        return attachment_response(p.pdf, pdf_filename(f, p.name), "application/pdf")

    @app.get("/admin/f2f/{f2f_id}/rollout")
    async def rollout(f2f_id: str, _: Admin) -> Response:
        f = get_f2f(f2f_id)
        if f.rollout_plan is None:
            raise HTTPException(404, "No roll-out plan uploaded")
        return attachment_response(f.rollout_plan.content, f.rollout_plan.filename, f.rollout_plan.mime_type)

    @app.post("/admin/f2f/{f2f_id}/purge")
    async def purge(f2f_id: str, _: Admin) -> RedirectResponse:
        svc.store.purge(f2f_id)
        log.info("f2f %s purged by TL", f2f_id)
        return RedirectResponse("/admin", 303)

    # ---------- TL: collation ----------

    def ensure_collated_page1(f: F2F) -> None:
        if f.collation.page1 == Page1():
            pages = [(p.name, p.assessment.page1) for p in f.panelists if p.assessment.submitted]
            if pages:
                f.collation.page1 = fallback_collated_page1(f, pages, collated_score(f))

    def collation_ctx(f: F2F) -> dict[str, Any]:
        submitted = [p for p in f.panelists if p.assessment.submitted]
        return {
            "f": f,
            "submitted": submitted,
            "avg": averages(f),
            "ratings": collated_ratings(f),
            "result": collated_score(f),
            "page1": f.collation.page1,
            "tl": True,
            "locked": False,
            "panel_scores": [(p, score_assessment(f, p.assessment)) for p in f.panelists],
        }

    @app.get("/admin/f2f/{f2f_id}/collate")
    async def collate(request: Request, f2f_id: str, _: Admin) -> HTMLResponse:
        f = get_f2f(f2f_id)
        if f.status in (F2FStatus.invited, F2FStatus.in_progress, F2FStatus.draft):
            f.status = F2FStatus.collating
        ensure_collated_page1(f)
        return render(request, "admin/collate.html", **collation_ctx(f))

    def apply_collation_form(f: F2F, form: FormData) -> None:
        overrides: dict[str, float] = {}
        for q in f.template.questions:
            raw = str(form.get(f"override-{q.id}", "") or "").strip()
            if raw:
                with contextlib.suppress(ValueError):
                    overrides[q.id] = min(5.0, max(1.0, round(float(raw), 1)))
        f.collation.overrides = overrides
        f.collation.page1 = page1_from_form(form)
        f.collation.pdf = None

    @app.post("/admin/f2f/{f2f_id}/collate")
    async def collate_save(request: Request, f2f_id: str, _: Admin) -> HTMLResponse:
        f = get_f2f(f2f_id)
        apply_collation_form(f, await request.form())
        return render(request, "partials/collate_summary.html", **collation_ctx(f))

    @app.post("/admin/f2f/{f2f_id}/collate/draft")
    async def collate_draft(request: Request, f2f_id: str, _: Admin) -> HTMLResponse:
        f = get_f2f(f2f_id)
        pages = [(p.name, p.assessment.page1) for p in f.panelists if p.assessment.submitted]
        f.collation.page1 = await draft_collated_page1(svc.ai, f, pages, collated_score(f))
        f.collation.pdf = None
        return render(
            request,
            "partials/page1_form.html",
            page1=f.collation.page1,
            locked=False,
            tl=True,
        )

    async def build_collated_pdf(f: F2F) -> bytes:
        ensure_collated_page1(f)
        notes = {}
        for q in f.template.questions:
            notes[q.id] = "\n".join(
                f"{p.name}: {p.assessment.notes[q.id].strip()}"
                for p in f.panelists
                if p.assessment.submitted and p.assessment.notes.get(q.id, "").strip()
            )
        rows = build_rows(f, collated_ratings(f), notes)
        panel_scores = [
            (p.name, p.role, score_assessment(f, p.assessment)) for p in f.panelists if p.assessment.submitted
        ]
        html = svc.pdf.html(
            f,
            "Collated panel assessment",
            f.collation.page1,
            rows,
            collated_score(f),
            panel_scores=panel_scores,
        )
        return await svc.pdf.render(html)

    @app.get("/admin/f2f/{f2f_id}/collated.pdf")
    async def collated_pdf(f2f_id: str, _: Admin) -> Response:
        f = get_f2f(f2f_id)
        if f.collation.pdf is None:
            f.collation.pdf = await build_collated_pdf(f)
        return attachment_response(f.collation.pdf, pdf_filename(f, "Collated"), "application/pdf")

    @app.post("/admin/f2f/{f2f_id}/send-tl")
    async def send_tl(request: Request, f2f_id: str, _: Admin) -> RedirectResponse:
        f = get_f2f(f2f_id)
        form = await request.form()
        if "p1-summary" in form:
            apply_collation_form(f, form)
        if not any(p.assessment.submitted for p in f.panelists):
            raise HTTPException(400, "No panelist has submitted yet")
        if f.collation.pdf is None:
            f.collation.pdf = await build_collated_pdf(f)
        submit_job(f, f"Results to TL {f.tl_name}", email=svc.messages.tl_summary(f))
        f.status = F2FStatus.sent
        return RedirectResponse(f"/admin/f2f/{f.id}", 303)

    # ---------- Panelist ----------

    def get_panel(token: str) -> tuple[F2F, Panelist]:
        found = svc.store.by_token(token)
        if found is None:
            raise HTTPException(404, "This assessment link is not valid or the F2F has been closed")
        return found

    def panel_ctx(f: F2F, p: Panelist) -> dict[str, Any]:
        return {
            "f": f,
            "p": p,
            "a": p.assessment,
            "result": score_assessment(f, p.assessment),
            "brief": scen.fill(f.template.scenario, f.placeholders),
            "when": when(f),
            "locked": p.assessment.submitted,
            "page1": p.assessment.page1,
            "tl": False,
            "warnings": note_warnings(f, p.assessment),
            "missing": set(),
        }

    def apply_panel_form(f: F2F, p: Panelist, form: FormData) -> None:
        a = p.assessment
        for q in f.template.questions:
            raw = str(form.get(f"score-{q.id}", "") or "")
            if raw.isdigit() and 1 <= int(raw) <= 5:
                a.scores[q.id] = int(raw)
            elif raw == "":
                a.scores.pop(q.id, None)
            if f"notes-{q.id}" in form:
                a.notes[q.id] = str(form.get(f"notes-{q.id}", ""))
        if "p1-summary" in form:
            a.page1 = page1_from_form(form)

    def mark_opened(f: F2F, p: Panelist) -> None:
        if p.status == PanelStatus.invited:
            p.status = PanelStatus.opened
        if f.status in (F2FStatus.draft, F2FStatus.invited):
            f.status = F2FStatus.in_progress

    @app.get("/panel/{token}")
    async def panel(request: Request, token: str) -> HTMLResponse:
        f, p = get_panel(token)
        mark_opened(f, p)
        return render(request, "panel/assess.html", **panel_ctx(f, p))

    @app.post("/panel/{token}/save")
    async def panel_save(request: Request, token: str) -> HTMLResponse:
        f, p = get_panel(token)
        if p.assessment.submitted:
            raise HTTPException(409, "This assessment is submitted and locked")
        apply_panel_form(f, p, await request.form())
        return render(request, "partials/panel_save.html", **panel_ctx(f, p))

    @app.post("/panel/{token}/draft")
    async def panel_draft(request: Request, token: str) -> HTMLResponse:
        f, p = get_panel(token)
        if p.assessment.submitted:
            raise HTTPException(409, "This assessment is submitted and locked")
        apply_panel_form(f, p, await request.form())
        a = p.assessment
        a.page1 = await draft_page1(svc.ai, f, a, score_assessment(f, a))
        return render(request, "partials/page1_form.html", page1=a.page1, locked=False, tl=False)

    @app.post("/panel/{token}/submit")
    async def panel_submit(request: Request, token: str) -> Response:
        f, p = get_panel(token)
        if p.assessment.submitted:
            return RedirectResponse(f"/panel/{token}", 303)
        apply_panel_form(f, p, await request.form())
        a = p.assessment
        result = score_assessment(f, a)
        if not result.complete:
            # Normally caught in the browser before submitting; this covers it without JavaScript.
            ctx = panel_ctx(f, p)
            ctx["missing"] = {q.id for q in f.template.questions if q.id not in a.scores}
            return render(request, "panel/assess.html", status_code=400, **ctx)
        if a.page1 == Page1():
            # Nothing written yet: AI summarises the notes and sorts them into strengths and development areas.
            a.page1 = await draft_page1(svc.ai, f, a, result)
        a.page1.outcome = a.page1.overall_evaluation = result.rating
        rows = build_rows(f, {k: float(v) for k, v in a.scores.items()}, a.notes)
        p.pdf = await svc.pdf.render(svc.pdf.html(f, p.name, a.page1, rows, result))
        a.submitted_at = utcnow()
        p.status = PanelStatus.submitted
        submit_job(f, f"Assessment PDF to {p.name}", email=svc.messages.submitted(f, p))
        if all(x.assessment.submitted for x in f.panelists) and f.status != F2FStatus.sent:
            f.status = F2FStatus.collating
        return RedirectResponse(f"/panel/{token}", 303)

    @app.get("/panel/{token}/pdf")
    async def panel_pdf(token: str) -> Response:
        f, p = get_panel(token)
        if p.pdf is None:
            raise HTTPException(404, "Submit the assessment first")
        return attachment_response(p.pdf, pdf_filename(f, p.name), "application/pdf")

    return app


def note_warnings(f: F2F, a: Assessment) -> dict[str, str]:
    """Per question: a warning when the note and the score disagree (shown only, never blocks submit)."""
    return {q.id: mismatch_warning(a.scores.get(q.id), a.notes.get(q.id, "")) for q in f.template.questions}


def attachment_response(content: bytes, filename: str, mime: str) -> Response:
    safe = filename.replace('"', "")
    return Response(
        content,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{safe}"', "Cache-Control": "no-store"},
    )


def main() -> None:
    import truststore
    import uvicorn

    # Adyen endpoints chain to an internal CA that lives in the macOS keychain, not in certifi.
    truststore.inject_into_ssl()
    s = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(create_app(s), host=s.host, port=s.port, workers=1, log_level="info", access_log=False)


__all__ = ["JobStatus", "create_app", "main"]
