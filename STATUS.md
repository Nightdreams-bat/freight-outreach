# Freight Outreach - Project Status

_Last updated: 2026-08-27. Read this first before picking the project back up._

## What this is

A local, single-client tool for a freight brokerage. It cold-emails leads from an Excel
file, sends automatic ~24h call reminders, sends spaced follow-up nudges to leads who
don't reply, and (optionally) reads lead replies: Claude Haiku classifies each reply and
a "yes" produces a drafted Google Calendar invite + confirmation email that the client
approves on the **Replies** page. Nothing sends or books without approval. No database,
no server - everything lives in one folder: an Excel file for leads, a local dashboard,
and Gmail + Google Calendar via real Google sign-in.

Run it:
```
cd C:\Users\darga\freight-outreach
python -m outreach
```
Opens the dashboard **in a native desktop window** (pywebview + the WebView2 runtime
built into Windows 11 - nothing bundles Chromium). `python -m outreach --web` opens it
as a browser tab instead. The CLI (`--cold` / `--followup` / `--reminders` / `--replies`)
and the Windows scheduled tasks call the same `outreach/core.py` logic, so no interface
can behave differently. `config.json` is written with defaults on first run; everything
is configured on the **Settings** page.

## Where things stand (2026-08-27)

Everything below is **built, tested live against real Gmail / Google Calendar / Anthropic,
and pushed**. See `docs/TEST-RESULTS.md` for the full end-to-end test log and
`docs/SETUP.md` for the from-scratch setup walkthrough.

| | |
|---|---|
| Dashboard theme | ✅ dark "glow" — near-black + spring-green `#3ddc84`, glassy cards, glowing lamps/nav. **Dark-only** (no light mode). Space Grotesk headings, IBM Plex Sans body, Silkscreen wordmark — **all fonts vendored** under `static/fonts/`, so it renders right offline. |
| Native desktop app | ✅ pywebview window; `--web` fallback; Desktop + Start-Menu shortcut on first frozen run; app icon |
| Diagnostics speed | ✅ page renders instantly; the 7 checks run in parallel (`/diagnostics/run` JSON) and fill in ~3s (was ~7s serial) |
| Multi-touch follow-up drip | ✅ cadence measured **from the cold intro** (default days 3/7/14), 1-day floor between touches, breakup email last, auto-stops on any reply or booking |
| Lead priority score | ✅ optional `Priority` sheet column, else computed; orders the send queue under the daily cap |
| Run-now panel | ✅ dashboard buttons trigger cold/follow-up/reminder/reply-scan jobs in a background thread; shows a plain-English **activity feed** (not the raw log) that refreshes after a run |
| Confirmations | ✅ every "are you sure" is an in-app themed `<dialog>` glass modal (`window.confirmDialog`) — no raw browser `window.confirm` anywhere |
| Activity log | ✅ `/logs` page + `/activity` JSON: friendly sentences from send history grouped by day, with the raw log tucked into a collapsible "Technical log" |
| No console flash | ✅ scheduled tasks (frozen) launch via a hidden `run-hidden.vbs` wscript wrapper; `desktop.py` hides the console before the readiness poll |
| Code review | ✅ full-app review applied — 7 findings fixed (commit `8ae6192`) |
| Reply handling + auto-booking | ✅ verified live: reply → classify → draft → approve → real Calendar event + confirmation email |
| `.exe` build | rebuilt on 2026-08-27 with all of the above (`build.ps1`) |
| Tests | **199 passing**, network-free (`python -m pytest tests/`) |

## How it's built (`outreach/` package)

| File | What it does |
|---|---|
| `__main__.py` | Single entry point (`python -m outreach` / `FreightOutreach.exe`): no args → native window; `--web` → browser; `--cold` / `--followup` / `--reminders` / `--replies` / `--selfcheck`. |
| `desktop.py` | Runs the dashboard as a native window: Flask in a daemon thread, pywebview window on the main thread. Fallback chain: pywebview → chromeless Edge/Chrome `--app` → browser tab. Hides the console in GUI mode **immediately after the server thread starts** (before the readiness poll), so a slow cold start doesn't flash a black window. |
| `schedule_task.py` | Registers the hourly Windows scheduled tasks. Frozen build: writes `run-hidden.vbs` into the data dir and points the task's `/TR` at `wscript.exe //B run-hidden.vbs <flag>` so a `console=True` exe never flashes on fire. Source checkout: `pythonw -m outreach`. |
| `shortcut.py` | Best-effort Desktop + Start-Menu `.lnk` creation (pywin32), once, on first frozen run. |
| `web/` | The Flask dashboard - `app.py` (routes + the background "Run now" job runner + `/activity` feed builder `_activity_items` / `_relative_time`) + `templates/` (9 pages, incl. `logs.html`) + `static/style.css` (self-contained, no CDN; `.modal` + `.activity` components). |
| `core.py` | Shared logic: `cold_candidates` / `reminder_candidates` / `followup_candidates`, the daily-cap trim (`apply_daily_cap` + `priority_sort_key`), and the send loops (`send_cold_batch` / `send_reminder_batch` / `send_followup_batch`). CLI and dashboard both call this. |
| `scoring.py` | `score_lead()` - a numeric `Priority` cell wins; otherwise a small score from company/phone/notes-keyword rules in `config.json`. |
| `send_cold.py` / `send_reminders.py` / `send_followups.py` | The headless batch entry points. `--reminders` also runs the follow-up pass. |
| `diagnostics.py` | `run_checks(cfg)` - every external connection, each guarded so one failure can't break the page. Powers `/diagnostics` and `--selfcheck`. |
| `templates.py` | Email templates (Cold Intro, Follow-up + Breakup, Reminder, plus Meeting-Confirm / Propose-Times / Decline-Ack), Jinja2 so an empty field (e.g. Phone) is skipped cleanly. |
| `excel_store.py` | Reads/writes `clients.xlsx`. `DATA_COLUMNS` (Name/Company/Email/Phone/Priority) are the client's own, auto-detected; `STATE_COLUMNS` are app-owned and appended if missing (incl. `FollowupStage` / `FollowupSentAt` / `ReplyStatus` / `MeetingEventId`). Only STATE columns are ever written. |
| `column_map.py` | `detect()` - matches a sheet's own headers (`Surname`, `Organisation`, `E-mail Address`, split first/last, `priority`/`score`, ...) to the logical fields. |
| `lead_fields.py` | `lead_name()` / `lead_company()` - derive a name from the email local part and a company from the domain when a row is just an address. |
| `mailer.py` | Sends via the Gmail API - builds the MIME message, sets the From display name and real headers (Date / Message-ID / Reply-To). |
| `gmail_oauth.py` | The "Connect Gmail" OAuth flow + token refresh. Scopes: `gmail.send`, `gmail.readonly`, `calendar.events`, `calendar.freebusy`, `openid`, `userinfo.email`. |
| `credentials.py` | Thin `keyring` wrapper - OAuth token + Anthropic API key live in the Windows Credential Manager, never in a file. |
| `gmail_read.py` | Fetches the latest inbound message per lead thread (`gmail.readonly`), strips quoted history, tracks processed ids in `processed_replies.json`. |
| `llm.py` | `classify_reply()` - one Claude Haiku call (forced tool-use) → `{intent, proposed_start, proposed_end, summary}`. Missing key = "feature off", not an error. |
| `calendar_api.py` | `busy_intervals` (freebusy), `find_open_slots` / `slot_is_free` (business-hours-aware), `create_event`. |
| `scheduling.py` | `plan_action()` - a classification → a drafted action: `book` / `propose` / `decline_ack` / `manual`. Degrades to `manual` on any Calendar error. |
| `reply_queue.py` | The approval queue (`reply_queue.jsonl`). `approve()` is the only code that sends/books - creates the event, sends the email, writes `MeetingDateTime`/`MeetingEventId`/`ReplyStatus`, respects the daily cap, idempotent on the calendar event across retries. |
| `process_replies.py` | The headless reply scan (`--replies`): gated on `reply_scan_enabled`; scan → classify → plan → enqueue. Never sends or books. |
| `config.py` | Loads/saves `config.json`; `default_config()` + `_migrate()` back-fill new keys into older configs. No wizard. |
| `send_tracker.py` | Daily send counter (the cap) + `send_history.jsonl` (the History page). |
| `blocklist.py` / `manage_blocklist.py` | Permanent block by domain or address, separate from per-lead Suppress. |
| `schedule_task.py` | Windows Task Scheduler jobs: `FreightOutreach_ReminderCheck` (reminders + follow-ups) and `FreightOutreach_ReplyCheck` (`--replies`). |
| `paths.py` | The one place that resolves file locations, so the same code runs from source or frozen. |

## Safety rails

- **Daily send cap** (cold + follow-up + reminder combined) - default 150. Lower it while a new sending account warms up.
- **Per-run brakes** - reminders (25) and follow-ups (`max_followups_per_run`, 25): if a scan matches more than that it sends nothing and warns.
- **Follow-up drip stops on the first reply or a booked meeting** - no risk of nudging someone mid-conversation.
- **Permanent blocklist** by domain/address + **per-lead Suppress**.
- Every send is written to `clients.xlsx` immediately - a crash mid-batch can't duplicate.
- A broken email template is caught by a pre-flight render check - one clear error, zero sent.
- Nothing in reply handling sends or books without the client clicking **Approve**.

## Google + Anthropic setup

Full walkthrough: `docs/SETUP.md`. Summary of the current state on this machine:
- Google Cloud project (`client_secret.json`, gitignored): **Gmail API + Google Calendar API both enabled**; OAuth consent screen in Testing mode.
- **Connected as `goddgd5@gmail.com`** (the live-test sender).
- Anthropic: a valid API key is in keyring; reply classification tested live against Claude Haiku 4.5 (~$0.001/reply). An Anthropic **API key** is required - a Claude subscription does not work.

## Deliverability note

The live test (2026-08-27) sent cold intro, follow-up, reminder, and confirmation emails
from a fresh `goddgd5@gmail.com` - **all landed in Inbox, not spam**. The real headers
`mailer.py` sets (Date / Message-ID / Reply-To) and the 3s gap between sends are doing
their job. Still ramp sending volume up gradually on a new account; a Workspace domain
builds reputation faster if this becomes an ongoing campaign.

## Not started / out of scope

- **No open/click tracking** - needs a hosted server for a pixel; out of scope for a local-only tool.
- **A reschedule-by-email after a booking is manual** - if a lead emails a new time after the meeting is booked, the app leaves it alone (status is already terminal); reply in Gmail and update `MeetingDateTime`.
- The demo `clients.xlsx` / `config.json` hold sample data (Alex Carter / Carter Freight). Real client setup is the `docs/SETUP.md` walkthrough.

## Picking this back up

1. `cd C:\Users\darga\freight-outreach && python -m outreach`
2. `python -m outreach --selfcheck` - confirms every connection is green.
3. Settings → real business details, lower the daily cap while warming up, check the column mapping, turn on Automation (+ reply checking if wanted).
4. Leads → replace the demo rows with real data (or Settings → Browse to a different `.xlsx`).
5. `README.md` has full per-feature usage; `docs/SETUP.md` the setup; `docs/reply-handling-design.md` the reply-handling design; `docs/TEST-RESULTS.md` the last verification run.
