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
- `.venv` is macOS-only. A Linux shell cannot run it; use a separate Python 3.11 venv with `PYTHONPATH=src` (e.g. `UV_PROJECT_ENVIRONMENT=<path> uv sync --frozen`). From Linux run mypy with its own `--cache-dir`: the macOS `.mypy_cache` makes it crash with an INTERNAL ERROR.
- Restart the app (`make run`) after code changes; the in-memory F2F data is lost on restart.

## Product decisions (agreed with the owner)
- **Notes only.** Panelists score 1-5 and write plain-text notes per question. There is no justification field and no buttons in the notes section.
- **Evaluation Summary = executive summary of the notes, never the score.** The **Score is its own section** (PDF and TL views).
- **AI sorts each note into strength or development area** using the score and rubric, then files it under a feedback section: Technical Accuracy, Discovery & Curiosity, Communication / Stakeholder Management (`models.FEEDBACK_BLOCKS`; "Meeting Management" -> Discovery, "Personal Skills" -> Communication, everything else -> Technical). The score overrides a contradicting AI answer (4-5 keeps a strength, 1-2 keeps a development area). Without AI: score >= 3 is a strength, otherwise a development area. It runs from "Summarise my notes" or automatically on submit if the write-up is empty. Logic is in `drafting.py`.
- **Development areas are full sentences.** The AI rewrites terse notes ("pricing unclear") into complete third-person sentences without adding facts; the collated write-up follows the same rule. Without AI the note is only tidied (capital letter, full stop).
- **Note vs score warning.** If a note reads positive but is scored 1-2 (e.g. "Yes amazing" scored 1), or negative but scored 4-5, a yellow warning shows under it (`consistency.py`, word-based, handles simple negations like "not clear", no AI). It updates on every autosave via htmx out-of-band swaps (`partials/panel_save.html`, `partials/note_warning.html`) and clears when the score or note changes. A 3 is never flagged. It is a warning only and never blocks submit; the submit confirm mentions how many notes are flagged.
- **"AI: summarise my notes" shows a spinner** and "Summarising…" only after it is clicked and while the request runs (button disabled meanwhile). The spinner and busy label carry the `hidden` attribute in the HTML, so they stay hidden even with a stale stylesheet. Static assets carry `?v=<startup time>` so browsers fetch fresh CSS/JS after a restart.
- **Missing scores on submit:** clicking Submit with unscored questions stops before the confirm and before any redirect. Each unscored question gets a red outline and "Please give this question a score before you submit.", the page jumps to the first one (clear of the sticky score bar) and focuses its score buttons, and a red box **directly above the Submit button** links to every skipped question ("Section: question text…"); each link jumps to that question and flashes its outline (`app.js`). Outlines and links clear as scores are picked. Without JS the server returns the same page with status 400 (notes kept) and jumps to the first skipped question on load.
- **Priority replaces weight** (Low=1, Medium=2, High=3). It is still the multiplier in the score, so pass marks are unchanged. Old `templates.json` files that say `weight` are read as priority.
- **Expectations & Next Steps was removed completely.** Do not bring it back unless asked.
- **TL view:** the dashboard Panel table (`partials/panel_status.html`) has a "Check for updates" button (`GET /admin/f2f/{id}/panel`, TL only) that refreshes just that table, so newly submitted scores, ratings, submit times and PDF buttons show without a page reload. It shows "X/Y submitted · checked HH:MM:SS UTC". No automatic polling: a 5s auto-refresh was tried and the owner replaced it with the button. Score per panelist, every panelist's PDF downloadable, collated PDF downloadable (dashboard and collate page). Panelists only ever see their own assessment and PDF.
- **TL scorecard:** the TL is also a panelist (`Panelist.is_tl`, role "TL", appended last in `POST /admin/f2f`). They score at `/panel/{token}` via "Open my scorecard" in the dashboard Panel table; the page has a Back to dashboard link. They get no panel-link or "your PDF" email (`F2F.invitees` = panelists minus the TL; use it for anything emailed), but they stay on the calendar invite, count in the average and collation, and have a downloadable PDF. Tests that pair scores with emailed panelists iterate `f.invitees`.
- **Calendar invite is created automatically** when the F2F is created (`POST /admin/f2f`). With a backend that can't send (default `manual`) or on failure, the dashboard offers Download .ics, Add in Google Calendar, and Retry. "Send invites" queues the emails and only adds an invite if none exists.

## Working with the owner
- `master` is the main branch; `panelists-view-wip` and `wording-changes-in-template` are merged into it. For new work, create a feature branch from `master` when asked (branch names cannot contain spaces; use hyphens). Commit only when asked, never push unless asked.
- Commit messages end with the Claude co-author line. The device shell has no git identity: commit with `git -c user.name=... -c user.email=...` taken from `git log -1 --format='%an %ae'`.
- Check UI changes in a real browser (Playwright/Chromium), not only with pytest, and add tests in `tests/` for each change.
- Write PR descriptions as a pasteable Markdown block: Summary by area, Testing, attribution footer.

## Templates
- The app reads `templates.json`; on first run it copies `src/f2f/data/templates.seed.json`. `scripts/seed_templates.py` builds the seed from the scoring xlsx and holds the hard-coded scenarios and pass marks.
- Scenarios for **Digital, UC and P&FS are hard-coded** (seed JSON, the seed script and `templates.json` must stay in sync). The role-play prompt text is the owner's wording; change it only when asked.
- **Placeholders** in the scenarios: `[NAME]`, `[DATE SCHEDULED]`, `[Merchant Name]`, `[Sales Manager Name]`, `[CTO Name]`, `[Developer Name]`, `[Project Manager Name]`. `[Insert SM name]`/`[SM Name]` were merged into `[Sales Manager Name]`; `[IE Name]` (CTO and developer) and `[TL Name]` (the merchant's Project Manager) were replaced because they filled in the wrong people.
- **Auto-filled placeholders** (`scenario.AUTO_PLACEHOLDERS`, values set in `POST /admin/f2f`): `[CTO Name]`, `[Developer Name]`, `[Project Manager Name]` come from the panelists with the CTO, Developer and PM roles (several with one role are joined with "and"; no panelist leaves the bracket); `[NAME]` from the candidate name; `[DATE SCHEDULED]` from the date, written like "Tuesday 10 November 2026". `[TL Name]` and `[IE Name]` still map to the TL and candidate name for custom templates. Auto-filled placeholders are hidden from Scenario values on the create page and from "Placeholders found" in the template editor. The TL only types Merchant Name and Sales Manager Name.
- **Wording rules (owner):** write "Sales Manager" and "Project Manager" in full and capitalised (never "SM", "PM", "sales manager", "Project manager") in scenario text. The merchant sentence is "…lead a technical kick off call with the merchant [Merchant Name], which we've been trying to poach from our competitor for years." The Project Manager sentence ends "…managing the project from the merchants side." (the "never done a PSP integration" clause was removed as contradictory). The panel role dropdown still says "PM"; that is a form label, not template text.
- Syncing templates from Drive was discussed and dropped for now. It would need a Drive scope approved by Adyen IT, or a manual xlsx import.

## Gotchas
- Sender backends: `manual` (default), `droid` (not verified live), `google` (needs Adyen IT OAuth client and `TL_ALLOWED_EMAILS`). See README.
- AI needs `GENAI_PLATFORM_API_KEY`; without it everything falls back to score-based text and stays editable.
- Panel links only open on the machine running the app until it is hosted (`PUBLIC_BASE_URL`).
- Deleting files through the device shell needs an explicit permission prompt; the owner has asked not to delete things unnecessarily. `git commit` from the device shell also needs it (git removes its own `.lock` files).
- Playwright cannot download Chromium in the device shell (network blocked); browser checks run elsewhere.
- VSCodium's Source Control panel lists only uncommitted changes; committed work shows under Graph/Timeline or `git log`.
