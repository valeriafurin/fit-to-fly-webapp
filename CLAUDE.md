# F2F Assessment (Fit to Fly) - project context

Local FastAPI + Jinja + htmx webapp that helps Adyen team leads (TL) schedule and assess Fit to Fly (F2F) assessments for new Implementation Engineers/Managers. Part of the Claude project "F2F Automation". The app code is everything under `src/f2f` (there is no `webapp/` folder).

## Hard rules
- **Never change the Google Drive documents** (scoring sheet, evaluation/feedback templates, TL user guide). The app never reads or writes Drive; changes are made in this repo only.
- Never commit or print secrets: `.env` holds the admin passcode and GenAI API key. `templates.json` is the working copy of the templates and is git-ignored.
- F2F data (candidates, notes, scores, PDFs) lives in memory only and must never be written to disk or logs. Templates are the only persisted data.
- Run a single worker (the store is per process).

## How to run and check
- `make install`, `make browsers` (once, Chromium for PDFs), `make run`, then open http://127.0.0.1:8000/login. The admin passcode is printed at startup (or set `ADMIN_PASSCODE` in `.env`).
- Port in use (`Errno 48`): an older copy is still running. Find it with `lsof -nP -iTCP:8000 -sTCP:LISTEN`, or set `PORT` and `PUBLIC_BASE_URL` (they must match, panel links use the latter) in `.env`.
- `make check` = ruff format + lint, mypy (strict), pytest. `tests/test_flow.py::test_full_flow` needs Playwright Chromium and is skipped without it; `test_pdf_content_end_to_end_without_chromium` covers PDF content with the browser step stubbed.
- `.venv` is macOS-only. A Linux shell cannot run it; use a separate Python 3.11 venv with `PYTHONPATH=src`.

## Product decisions (agreed with the owner)
- **Notes only.** Panelists score 1-5 and write plain-text notes per question. There is no justification field and no buttons in the notes section.
- **Evaluation Summary = executive summary of the notes, never the score.** The **Score is its own section** (PDF and TL views).
- **AI sorts each note into strength or development area** using the score and rubric, then files it under a feedback section: Technical Accuracy, Discovery & Curiosity, Communication / Stakeholder Management (`models.FEEDBACK_BLOCKS`; "Meeting Management" -> Discovery, "Personal Skills" -> Communication, everything else -> Technical). The score overrides a contradicting AI answer (4-5 keeps a strength, 1-2 keeps a development area). Without AI: score >= 3 is a strength, otherwise a development area. It runs from "Summarise my notes" or automatically on submit if the write-up is empty. Logic is in `drafting.py`.
- **Development areas are full sentences.** The AI rewrites terse notes ("pricing unclear") into complete third-person sentences without adding facts; the collated write-up follows the same rule. Without AI the note is only tidied (capital letter, full stop).
- **Note vs score warning.** If a note reads positive but is scored 1-2, or negative but scored 4-5, a yellow warning shows under it (`consistency.py`, word-based, no AI, runs on autosave). A 3 is never flagged. It is a warning only and never blocks submit; the submit confirm mentions how many notes are flagged.
- **"AI: summarise my notes" shows a spinner** and "Summarising…" only while the request runs (button disabled meanwhile). Static assets carry `?v=<startup time>` so browsers never use a stale CSS/JS after a restart.
- **Priority replaces weight** (Low=1, Medium=2, High=3). It is still the multiplier in the score, so pass marks are unchanged. Old `templates.json` files that say `weight` are read as priority.
- **Expectations & Next Steps was removed completely.** Do not bring it back unless asked.
- **TL view:** the dashboard Panel table refreshes every 5s (`/admin/f2f/{id}/panel`) until everyone has submitted, so submitted scores appear without a reload. Score per panelist, every panelist's PDF downloadable, collated PDF downloadable (dashboard and collate page). Panelists only ever see their own assessment and PDF.
- **Calendar invite is created automatically** when the F2F is created (`POST /admin/f2f`). With a backend that can't send (default `manual`) or on failure, the dashboard offers Download .ics, Add in Google Calendar, and Retry. "Send invites" queues the emails and only adds an invite if none exists.

## Templates
- The app reads `templates.json`; on first run it copies `src/f2f/data/templates.seed.json`. `scripts/seed_templates.py` builds the seed from the scoring xlsx and holds the hard-coded scenarios and pass marks.
- Scenarios for **Digital, UC and P&FS are hard-coded** (seed JSON, the seed script and `templates.json` must stay in sync). The role-play prompt text is the owner's wording; placeholders are `[NAME]`, `[DATE SCHEDULED]`, `[Merchant Name]`, `[Insert SM name]`, `[IE Name]`, `[TL Name]`, `[SM Name]`.
- Syncing templates from Drive was discussed and dropped for now. It would need a Drive scope approved by Adyen IT, or a manual xlsx import.

## Gotchas
- Sender backends: `manual` (default), `droid` (not verified live), `google` (needs Adyen IT OAuth client and `TL_ALLOWED_EMAILS`). See README.
- AI needs `GENAI_PLATFORM_API_KEY`; without it everything falls back to score-based text and stays editable.
- Panel links only open on the machine running the app until it is hosted (`PUBLIC_BASE_URL`).
- Deleting files through the device shell needs an explicit permission prompt; the owner has asked not to delete things unnecessarily.
