# Freight Outreach - Project Status

_Last updated: 2026-08-27. Read this first before picking the project back up._

## What this is

A local tool for cold-emailing freight brokerage leads, automatically reminding them
~24h before a scheduled call, and (optionally) reading their replies to auto-draft the
follow-up: Claude classifies each reply, and a "yes" produces a drafted Google Calendar
invite + confirmation email that the client approves on the **Replies** page. No database,
no hosting - everything lives in this folder: an Excel file for leads, a local web
dashboard, and Gmail + Google Calendar (via real Google sign-in).

Run it with:
```
cd C:\Users\darga\freight-outreach
python -m outreach.dashboard
```
Opens the dashboard at **http://127.0.0.1:5000**. That's the main way to use this - Settings,
Leads, Send, History, Blocklist are all there. The CLI (`send_cold.py`, `send_reminders.py`,
`setup.py`) still works too; the dashboard is a UI on top of the same underlying logic.

## How it's built (`outreach/` package)

| File | What it does |
|---|---|
| `excel_store.py` | Reads/writes `clients.xlsx` - the entire lead database. |
| `core.py` | The shared logic: who's a candidate to email, the daily-cap trim, the actual send loop. Both the CLI and the dashboard call into this, so they can never behave differently. |
| `templates.py` | The email templates (Cold Intro, Reminder, plus Meeting-Confirm / Propose-Times / Decline-Ack for reply handling), Jinja2 so a field like Phone can be skipped cleanly when empty. |
| `mailer.py` | Actually sends via the Gmail API - builds the MIME message, sets the From display name and proper headers (Date/Message-ID/Reply-To). |
| `gmail_oauth.py` | The "Connect Gmail" OAuth flow (real Google sign-in) and token refresh. |
| `credentials.py` | Thin wrapper around `keyring` - stores the OAuth token in the Windows Credential Manager, never in a file. |
| `blocklist.py` / `manage_blocklist.py` | Permanent block-by-domain-or-address, separate from per-lead suppression. |
| `send_tracker.py` | Daily send counter (for the cap) + a JSON log of every email actually sent (powers the History page). |
| `schedule_task.py` | Creates/removes/queries the Windows Task Scheduler jobs - the reminder scan (`FreightOutreach_ReminderCheck`) and the reply scan (`FreightOutreach_ReplyCheck`). |
| `llm.py` | `classify_reply()` - one Claude Haiku call (forced tool-use) returning `{intent, proposed_start, proposed_end, summary}`. API key from keyring; a missing key is a normal "feature off" state, not an error. |
| `gmail_read.py` | Fetches the latest inbound message per lead thread (`gmail.readonly`), strips quoted history, and tracks processed message ids in `processed_replies.json`. |
| `calendar_api.py` | Google Calendar - `busy_intervals` (freebusy), `find_open_slots` / `slot_is_free` (business-hours-aware), `create_event`. |
| `scheduling.py` | `plan_action()` - turns a classification into a drafted action: `book` / `propose` / `decline_ack` / `manual`. Renders the emails from templates; degrades to `manual` on any Calendar error. |
| `reply_queue.py` | The approval queue (`reply_queue.jsonl`). `approve()` is the only code here that sends/books - creates the event, sends the email, writes `MeetingDateTime`/`MeetingEventId`/`ReplyStatus`, respects the daily cap, and is idempotent on the calendar event if a retry happens. |
| `process_replies.py` | The headless reply scan (`--replies`): gated on `reply_scan_enabled`, scans -> classifies -> plans -> enqueues. Never sends or books. |
| `setup.py` | First-time CLI wizard - business details, Excel path, limits. Gmail is connected separately via the dashboard. |
| `web/` | The Flask dashboard - `app.py` (routes) + `templates/` (pages) + `static/style.css`. |
| `paths.py` | The one place that resolves file locations, so the same code works run from source or as the frozen `.exe`. |
| `__main__.py` | Single entry point (`python -m outreach` / `FreightOutreach.exe`): no args -> dashboard, `--setup` / `--cold` / `--reminders` / `--replies` / `--selfcheck`. |

## The two sending modes

1. **On demand** - Send page, "Send Now" button (or `python -m outreach.send_cold`). Emails every lead that doesn't have a `ColdEmailSentAt` yet.
2. **Automatic** - a Windows Task Scheduler job runs `send_reminders.py` every N hours, checking for any lead whose `MeetingDateTime` is ~24h away and hasn't been reminded yet. Toggle in Settings > Automation. **Currently enabled**, checking every 2 hours.

## Safety rails already in place

- **Daily send cap** (cold + reminders combined) - currently **150**, see the note below about lowering it.
- **Per-run safety cap on reminders** (25) - if a scan ever matches more than that, it sends nothing and warns, in case of a data problem.
- **Permanent blocklist** by domain or address (Blocklist page / `manage_blocklist.py`).
- **Per-lead Suppress** toggle on the Leads page.
- Every send is written back to `clients.xlsx` immediately - a crash mid-batch can't cause a duplicate send.
- A broken email template is caught by a pre-flight render check before any batch goes out - one clear error, zero emails sent, instead of a partial/broken batch.

## Gmail connection (OAuth, not an app password)

Fully set up already:
- Google Cloud project `freight-outreach`, Gmail API enabled.
- OAuth consent screen in **Testing** mode (skips Google's weeks-long verification - fine for one client's tool). Test users allowed to sign in: `goddgd5@gmail.com` and `mateitodirel430@gmail.com`.
- Desktop OAuth Client created; its credentials are in `client_secret.json` in this folder (gitignored - don't lose it, it's needed for anyone to ever click "Connect Gmail" again).
- **Currently connected as `goddgd5@gmail.com`** (Settings > Gmail account shows this).
- To let a different account sign in, it has to be added as a test user first: Google Cloud Console -> APIs & Services -> Google Auth Platform -> Audience -> Add users.

## Today's fix: emails landing in spam

Two real causes, both addressed:
1. Outgoing emails were missing `Date`, `Message-ID`, and `Reply-To` headers - every real mail client sets these; their absence is itself a spam signal. Fixed in `mailer.py`.
2. The default templates read like generic bulk cold-email software ("Reply STOP to be removed", a formulaic subject line). Reworded to sound like a person wrote them, and applied to the live config.

**Not fixed by code, and won't be**: `goddgd5@gmail.com` was connected today with zero sending history. A brand-new sending identity gets filtered hard by Gmail regardless of wording - that's account reputation, which only builds through time and real engagement. Concrete next steps, not yet done:
- **Lower `daily_send_cap` from 150 to ~10-15** while warming up (Settings > Sending limits).
- Manually send/reply to a handful of test emails first, mark anything that lands in spam as "Not Spam" - the single strongest reputation signal.
- If this becomes an ongoing real campaign, a Google Workspace domain will build reputation faster and look more legitimate than a personal Gmail address.

## Standalone executable (done)

The client no longer needs Python. `build.ps1` runs PyInstaller against
`FreightOutreach.spec`, self-checks the result, and assembles `release\FreightOutreach\` -
the folder you hand the client. It contains, at the top level: `START HERE.txt`,
`Setup.exe` (run first), `FreightOutreach.exe` (the app), `client_secret.json`, and two
subfolders - `_internal\` (frozen runtime) and `Source code\` (a copy of the source).

`Setup.exe` and `FreightOutreach.exe` are the same binary; the app runs the setup wizard
when it's launched under the name `Setup.exe`. `config.json` and the logs are created
next to the `.exe` files. See `BUILD.md`.

Path handling was reworked so the same code runs from source and frozen:
`outreach/paths.py` is the one place that decides where user data lives (project root
when run from source, the `.exe`'s own folder when frozen) and where bundled resources
are (project tree vs. PyInstaller's temp dir). `outreach/__main__.py` is the single
entry point both modes share.

## Reply handling & auto-scheduling (done)

Reads replies to the cold emails and drafts the follow-up. **Draft-and-approve only** -
nothing is sent or booked without the client clicking Approve on the new **Replies** page.

Flow: `process_replies.py` (hourly task, or `--replies`) → `gmail_read.fetch_new_replies`
→ `llm.classify_reply` (Claude Haiku) → `scheduling.plan_action` → `reply_queue.enqueue`.
The client reviews on Replies; `reply_queue.approve` creates the Calendar event, sends the
email, and writes `MeetingDateTime` back to the sheet — so the **existing 24h reminder
picks the meeting up with no new code**.

Design/contract doc: `docs/reply-handling-design.md`. Built in 4 waves, ~120 unit tests
(fakes for Gmail/Calendar/Anthropic — no network). `anthropic` is bundled into the `.exe`.

**Two manual steps to actually switch it on:**
1. **Re-connect Gmail** — the OAuth scopes grew (`gmail.readonly`, `calendar.events`,
   `calendar.freebusy`). The Google Cloud project also needs the **Calendar API** enabled.
   Settings → Connect Gmail, re-consent.
2. **Anthropic API key** — paste into Settings → *Reply handling & auto-scheduling*
   (stored in keyring). Then click **Enable** on the reply automation toggle.

New config keys (defaults in `outreach/config.DEFAULTS`): `reply_scan_enabled`,
`llm_model`, `meeting_duration_minutes`, `business_hours`, `business_days`,
`scheduling_window_days`, `min_notice_hours`, `calendar_id`, `reply_lookback_days`.
New Excel columns (auto-added): `ReplyStatus`, `LastReplyAt`, `MeetingEventId`.

## Still placeholder / not started

- **Business details in Settings are still demo data** (`Alex Carter` / `Carter Freight Solutions` / a placeholder pitch) - replace with the real client's info before sending anything real.
- **`clients.xlsx` currently has one test row** (`Jamie Lin`, actually the client's own test address, meeting set for 2026-08-28 00:17) - the automatic reminder scan will email that address a reminder tomorrow since automation is enabled; that's expected/harmless (it's your own test data), just don't be surprised by it. Replace with real leads before relying on this.
- **No open/click tracking** - would need a hosted server for a tracking pixel, out of scope for this local-only tool.

## Picking this back up

1. `cd C:\Users\darga\freight-outreach && python -m outreach.dashboard`
2. Settings -> fill in the real business details, lower the daily send cap.
3. Leads -> replace the test row with real lead data (or Settings > Browse to point at a different `.xlsx`).
4. Send -> review what's queued before clicking Send Now on anything real.
5. See `README.md` in this folder for full usage details on every feature; this file is just the "what happened and where things stand" snapshot.
