# F2F Assessment

A locally hosted web app for running Fit to Fly (F2F) assessments for new Implementation Managers.

- **TL view** (`/admin`): edit pillar templates, create an F2F, send invites, follow delivery, collate results, email the TL, close and purge.
- **Panelist view** (`/panel/{token}`): the F2F details, the scenario and the panelist's own assessment, with autosave, live scoring, an AI summary of their notes and submit.

F2F data (candidate, panel, notes, scores, PDFs, uploads) lives **in memory only**. Only the pillar templates are saved, to `templates.json`, which holds no candidate data.

## Setup

```bash
cd ~/coding-projects/f2f-assessment
make install      # uv sync
make browsers     # Playwright Chromium for PDF rendering (one-off)
cp .env.example .env   # optional; edit as needed
make run
```

Open <http://127.0.0.1:8000/login> and sign in with the **admin passcode printed in the terminal**. To fix the passcode, set `ADMIN_PASSCODE` in `.env`.

The Adyen and Fakt fonts are read from `/Library/Fonts` at runtime. They are licensed, so they are not committed.

Checks: `make check` runs format, lint (ruff), typecheck (mypy strict) and tests (pytest).

## How an F2F runs

1. **Templates** (`/admin/templates/Digital`, `UC`, `P&FS`): scenario text with `[Placeholders]`, minimum pass totals per IE level, and the rubric (section, question, priority Low/Medium/High, descriptions for 1, 3 and 5). The first run copies `src/f2f/data/templates.seed.json` to `templates.json`. To reseed from the xlsx: `make seed XLSX="/path/F2F Scoring Template.xlsx"`.
2. **Create F2F**: pillar, IE level, candidate, date and time, Zoom link, TL, panelists with their scenario role, one value per placeholder, and an optional Roll-out plan.
3. **Calendar invite**: created automatically as soon as the F2F is created. If the backend can't send it (the `manual` backend, or a failure), the dashboard shows **Download .ics** and **Add in Google Calendar** as the manual fallback, plus **Retry**. **Send invites** then queues the emails (and the invite, only if none exists yet):
   - one calendar invite, "F2F – {Candidate} – {Pillar}", to the candidate, panel and TL. The Zoom link goes in conference data, location and description, and the brief goes in the description.
   - the brief to the candidate, with the Roll-out plan
   - each panelist's personal link. Links never go in the invite, because the candidate can see it.
4. **Panelists** score each question from 1 to 5 and write plain-text **notes** (no justification, no buttons), and their work autosaves. The **Evaluation Summary** is an executive summary of the notes only, never the score. AI (or, without AI, the score) sorts each note into a **strength** or a **development area**, guided by the score and rubric, and files it under the matching feedback section: Technical Accuracy, Discovery & Curiosity, or Communication / Stakeholder Management. It is drafted with **Summarise my notes**, or automatically on submit if left empty, and stays editable. **Submit** locks the assessment, renders the PDF and emails it to the panelist. The score has its own section in the PDF.
5. **Collate (TL only)**: the TL sees each panelist's score, status and PDF, and the per-question ratings. Each question's rating is the average across submitted panelists, to one decimal place, and the TL can override any question; the total and rating update live. The collated write-up is prefilled from the panelists' write-ups, and **AI merge** consolidates them. **Download collated PDF** is on the dashboard and the collate page, every panelist's PDF is downloadable by the TL, and **Email all PDFs to TL** sends them all.
6. **Close & purge** deletes the F2F, its jobs and its PDFs from memory, and panel links stop working.

Scoring: total = Σ(priority × rating), where Low = 1, Medium = 2 and High = 3. Older `templates.json` files that say `weight` are read as priority. The result is **Pass** when the total reaches the minimum for the candidate's IE level, and **Needs Development** otherwise.

| Pillar | Max | IE1 | IE2 | Senior IE |
|---|---|---|---|---|
| Digital | 195 | 90 | 117 | 171 |
| UC | 210 | 99 | 126 | 192 |
| P&FS | 235 | 117 | 141 | 219 |

The Digital maximum is 195: the sheet's total formula counted one question twice, and the app counts each question once.

## Sending backends (`SENDER_BACKEND`)

Every email and invite is a job with a status (queued, sending, sent, failed or manual) and a **Retry** button. The dashboard always offers manual fallbacks: a `.ics` download for the invite, and for each email a Gmail compose link plus downloads of its attachments.

### `droid` (v1, not yet verified live)

Status: the job building and result handling are tested with a fake `droid` binary, but **no live send has succeeded yet**. That's why the default backend is `manual`. To try it, set `SENDER_BACKEND=droid`. What the live attempts showed:
- `--only-tools` can't be used: it rejects connector tool names, and it hides `ToolSearch`, so the session can't load Gmail. The app uses `--remove-tools` instead.
- `--auto low` is refused for connector sends ("insufficient permission"), so the default is `DROID_AUTO=medium`. Medium has not been confirmed to work yet. If it is refused as well, the job's error shows Droid's own message. Then try `DROID_AUTO=high`.

Each send runs `droid exec --auto <DROID_AUTO> --remove-tools <list> -o json` with a fixed prompt. The removed tools are Execute, ApplyPatch, Task, Skill, FetchUrl, WebSearch, Loop, the automation tools and the mission tools. The session can still load and call any Gmail or Calendar connector tool, so the fixed prompt is what limits it to one send. The app writes the exact tool input to a private temporary folder (`0700`, file `0600`). Droid reads it, loads the tool with `ToolSearch`, calls `gmail__send_message` or `google_calendar__create_event` once, and replies `SENT_ID: <id>`. The folder is deleted right after.

Requirements:
- The Droid CLI is installed and logged in on this machine. A Droid chat does not need to be open.
- The Gmail and Google Calendar connectors are connected in Factory.
- Mail and invites come from the Google account behind those connectors.

**Attachments are not sent by Droid.** A headless `droid exec` session has no Script tool, so the model would have to retype the PDF bytes. Instead, Droid sends the email text, and the job is flagged **attach manually**. Use the Gmail compose link and the attachment downloads next to it. This applies to the Roll-out plan, the panelist PDFs and the TL email.

### `manual` (default)

Nothing is sent automatically. Every job shows as *manual*, with the `.ics` file, the Gmail compose link and the attachment downloads.

### `google` (final, no Droid)

The TL signs in with Google, and the app calls the Gmail and Calendar APIs as that TL, with attachments included. The OAuth token is kept in memory only.

1. Ask Adyen IT for an **Internal** OAuth client (type "Web application") in a Google Cloud project on the adyen.com Workspace, with these scopes: `openid`, `email`, `https://www.googleapis.com/auth/gmail.send` and `https://www.googleapis.com/auth/calendar.events`.
2. Set the redirect URI to `{PUBLIC_BASE_URL}/auth/google/callback`. This must be HTTPS when the app is hosted.
3. Configure:
   ```
   SENDER_BACKEND=google
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   TL_ALLOWED_EMAILS=tl.one@adyen.com,tl.two@adyen.com
   PUBLIC_BASE_URL=https://f2f.example.adyen.com
   SECURE_COOKIES=true
   ```
Only emails in `TL_ALLOWED_EMAILS` get admin access. The Calendar API rejects a Zoom `addOn` conference unless a Zoom add-on is installed for the domain. In that case the app retries without it, and the link is still in the location and description.

## AI drafts (GenAI Platform)

`GENAI_PLATFORM_API_KEY` (the one Adyentic provisions) enables the notes summary and strength/development sorting, and the collated merge. These go through `GENAI_BASE_URL` (default `https://genai-platform.is.adyen.com/v1`) with `GENAI_MODEL` (default `gemma4-31b`). `make run` uses the macOS trust store, because Adyen endpoints chain to an internal CA. Without a key, or if a call fails, the app falls back to score-based sorting (3 and above counts as a strength, below 3 as a development area) and a short score-free summary. Everything stays editable.

## Access separation

- Every `/admin/*` route requires a TL session (an HttpOnly, SameSite=Strict cookie, held in memory). Without one it returns 403.
- Panelists use an unguessable 256-bit token link. A panel page shows only that panelist's assessment, and a token never grants admin access.
- The access log is off, so panel tokens in URLs are not logged. App logs carry job IDs and statuses only, never notes, scores or email content.

## Data handling

F2F data is purged when the TL clicks **Close & purge**, after `SESSION_TTL_HOURS` (default 12, checked every 5 minutes and on access), or when the server restarts. Run a single worker only, because the store is per process.

**v1 caveats (`droid` backend):**
- Each email or invite exists briefly as a temporary file (`0600`, in a `0700` folder) and is deleted after the send.
- Each send runs as a `droid exec` session, so its recipients and text appear in that session's history on Factory.
- The `google` backend removes both caveats.

## Known gaps

- The sheet's colour-based minimums (for example "all green questions rated min 3") are not enforced. Pass or Needs Development uses the total only, as the sheet's formulas do.
- Panel links only open on this machine until the app is hosted. Set `PUBLIC_BASE_URL` when it is.
- Zoom meetings are not created automatically. The TL pastes the link.
- The UC and P&FS scenarios are placeholders, and the P&FS pillar questions have no rubric descriptions yet. Edit them in the template editor.
- `[CTO Name]`, `[Developer Name]` and `[Project Manager Name]` are filled from the panelists with the CTO, Developer and PM roles. `[NAME]` and `[DATE SCHEDULED]` come from the candidate name and date. If no panelist has a role, its placeholder stays in brackets.
