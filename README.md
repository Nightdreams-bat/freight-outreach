<div align="center">

<img src="assets/banner.jpg" alt="Kairo — AI-powered outreach platform" width="100%">

<br>

**A local, single-operator cold-email, follow-up and reply-handling platform.
Leads live in one Excel file. Nothing is hosted, and nothing sends or books
without your approval.**

[![tests](https://github.com/Nightdreams-bat/kairo/actions/workflows/tests.yml/badge.svg)](https://github.com/Nightdreams-bat/kairo/actions/workflows/tests.yml)
[![latest release](https://img.shields.io/github/v/release/Nightdreams-bat/kairo?style=flat-square&color=3ddc84)](https://github.com/Nightdreams-bat/kairo/releases/latest)
![Tests](https://img.shields.io/badge/tests-424%20passing-2E7D32?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-10%2F11-0078D6?style=flat-square&logo=windows&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)

</div>

---

## Engineering highlights

- **Real Google integration, no shortcuts.** Sending is the Gmail API under a full
  OAuth sign-in (not SMTP or app passwords); scheduling reads Google Calendar
  free/busy and books real events. Tokens live in the Windows Credential Manager
  and auto-refresh.
- **LLM as a typed component.** Reply classification is a single forced-tool-use
  Claude Haiku call with a strict schema, a monthly spend counter, and a
  no-API-key keyword fallback — the model never has authority to send or book.
- **381 tests, fully network-free.** Gmail, Calendar and Anthropic are all faked
  in the suite; CI runs it on every push. `python -m pytest` finishes in ~8s.
- **One core, many front-ends.** The dashboard, the CLI, and the Windows
  scheduled tasks all call the same `kairo/core.py` functions, so they can never
  drift apart.
- **Ships as a desktop app.** PyInstaller build (`build.ps1` + `Kairo.spec`) with
  a self-check step produces a single folder a non-technical client runs with no
  Python installed; the UI is a native pywebview window on Windows' built-in
  WebView2.
- **Deliverability treated as a real problem.** Per-send postal address and
  `List-Unsubscribe` headers, always-on EN/RO opt-out scanning, per-lead
  suppression, a permanent blocklist, jittered timing, and a daily cap with a
  warm-up ramp.
- **Deliberately no database and no CDN.** The `.xlsx` *is* the store and the
  dashboard assets are all local — one portable folder, no server to run, and no
  lead data ever leaves the operator's machine except the email itself.

---

## What it is

Kairo is a desktop app for one operator to run their own outbound email. It reads
leads from an Excel spreadsheet on the PC, sends personalised cold-intro emails,
chases non-responders with a multi-touch follow-up drip, and emails a reminder
about 24 hours before any scheduled call. Optionally it also **reads the replies**:
Claude Haiku classifies each response (yes / no / maybe / question) and, for a
"yes", drafts a Google Calendar invite plus a confirmation email that you approve
on a **Replies** page. Nothing is ever sent or booked automatically — every
outbound action waits for a click.

There is no database, no server, and no hosting. Everything — the leads file, the
settings, the logs, the OAuth token — lives in one folder on the operator's
machine. Email goes out through the operator's own Gmail account over a real
Google sign-in (OAuth), not SMTP or app passwords.

---

## Features

| | Feature | What it does |
|---|---|---|
| ✉️ | **AI reply handling** | Claude Haiku classifies each inbound reply (yes / no / maybe / question) and drafts the follow-up — a calendar invite + confirmation for a "yes", an open-times email otherwise, a polite acknowledgement for a "no". Draft-and-approve only. |
| 📨 | **Multi-touch drip** | Up to three spaced follow-ups to cold leads who never replied (default 3 / 7 / 14 days), with a soft "breakup" email on the last touch. Stops the instant a lead replies or books. |
| 📅 | **Auto-scheduling** | For a "yes", Kairo finds an open slot against your Google Calendar free/busy, drafts the invite and a confirmation email, and books both on approval. |
| ⏰ | **24h call reminders** | A background scan finds leads whose meeting is ~24 hours away and sends one reminder each. The scan window overlaps between runs so no meeting slips through. |
| 🔍 | **Find leads** | Keyless web search + email scraping to pull new prospects straight into the sheet (beta). |
| 📊 | **Excel-backed CRM** | No database — your `.xlsx` *is* the store. Kairo auto-detects your headers (`Surname`, `Organisation`, `E-mail Address`, split first/last…) and lets you override each mapping. A row with only an email still works. |
| 🛡️ | **Compliance & safety** | Postal address + one-line opt-out and `List-Unsubscribe` headers on every send, an always-on keyword opt-out scan (EN/RO, no API key needed), per-lead suppression, a permanent blocklist, jittered send timing, and a daily send cap with warm-up ramp. |
| 🚦 | **Priority scoring** | When the daily cap can't fit every queued lead, the highest-priority ones send first — a numeric `Priority` column if present, otherwise a small rules score. No AI, nothing written back. |
| 📈 | **Dashboard & logs** | Ten offline pages — stat tiles, a background "Run now" panel with a live log tail, the full send history, diagnostics, and a plain-English activity feed. |
| 🔒 | **Privacy first** | No telemetry, no analytics, no third-party hosting, no open/click tracking. The only data that leaves the machine is the email you send and (if reply handling is on) the reply text sent to Anthropic. |

---

## Install (Windows)

Grab **`KairoSetup-<version>.exe`** from the
**[latest release](https://github.com/Nightdreams-bat/kairo/releases/latest)** and
run it. It installs per-user into `%LocalAppData%\Programs\Kairo` (no admin prompt,
pick another folder if you like), offers a Desktop shortcut, and can launch the app
straight away. Your settings and credentials live in `%APPDATA%\Kairo` and survive
upgrades and uninstalls.

The installer is unsigned, so Windows SmartScreen shows a blue *"Windows protected
your PC"* prompt on first run — click **More info → Run anyway**. Verify the download
against the `.sha256` published beside it if you want.

Releases are built by [`.github/workflows/release.yml`](.github/workflows/release.yml)
on every `v*` tag push (PyInstaller → Inno Setup → GitHub Release).

## Quick start (from source)

```bash
git clone https://github.com/Nightdreams-bat/kairo.git
cd kairo
pip install -r requirements.txt
python -m kairo
```

`python -m kairo` opens the dashboard in a native desktop window (pywebview + the
WebView2 runtime already in Windows 11 — no bundled Chromium). `--web` forces a
browser tab. `config.json` is created with defaults on first run; everything is
configured on the **Settings** page.

Before real sending works you need a one-time Google Cloud OAuth client (Gmail +
Calendar APIs, with your sending addresses as test users) and — only for reply
handling — a pay-as-you-go Anthropic API key (roughly $0.001 per reply on Haiku;
**not** a Claude.ai subscription). Full walkthrough:
**[`docs/SETUP.md`](docs/SETUP.md)**.

### Packaged build (client gets no Python)

```powershell
.\packaging\build.ps1
```

Runs PyInstaller against `packaging\Kairo.spec`, self-checks the result, and
assembles `release\Kairo\` — one folder the client copies anywhere.
`.\packaging\build-installer.ps1` goes one step further and compiles the
`KairoSetup-<version>.exe` installer locally (needs Inno Setup 6). See
**[`docs/BUILD.md`](docs/BUILD.md)**.

---

## How it works

```
                 clients.xlsx  (the entire lead store)
                        |
                        v
                  kairo/core.py         candidate selection, daily-cap trim, send loop
                  kairo/excel_store.py · scoring.py · templates.py · ...
                        |
        +---------------+----------------+------------------------+
        |               |                |                        |
  Flask dashboard   CLI flags     Windows scheduled tasks    Reply approval queue
  (native window)  (--cold ...)  (--reminders / --replies)   (reply_queue.jsonl)
```

Every interface calls the same `kairo/core.py` functions, so the dashboard, the
CLI, and the scheduled tasks can never behave differently. Email is sent through
the Gmail API and invites through the Google Calendar API, both under one real
OAuth sign-in; the token is stored in the Windows Credential Manager via `keyring`
and auto-refreshes. Reply text is the only thing sent to Claude, and only when
reply handling is switched on.

Design notes: **[`docs/reply-handling-design.md`](docs/reply-handling-design.md)**.

---

## CLI reference

Run `python -m kairo <flag>` from source, or `Kairo.exe <flag>` from the build.

| Flag | Effect |
|---|---|
| _(none)_ | Open the dashboard in a native desktop window. |
| `--web` | Open the dashboard in the default browser instead. |
| `--cold` | Send the cold-intro batch now, headless. |
| `--followup` | Send any due follow-up nudges now, headless (opt-in via config). |
| `--reminders` | Run the reminder + follow-up scan now (the `Kairo_ReminderCheck` task). |
| `--replies` | Scan for lead replies and draft actions (the `Kairo_ReplyCheck` task). Never sends or books. |
| `--selfcheck` | Verify a freshly built `.exe` has everything it needs. |

---

## Compliance & data processing

Cold email is regulated (CAN-SPAM in the US, GDPR/PECR in the EU). **The operator,
not this tool, is responsible for compliance.** Kairo adds a postal address, a
one-line opt-out and unsubscribe headers to every send, and permanently
blocklists anyone who replies "stop / unsubscribe / remove me". You still must:
use a **Google Workspace domain** (never a consumer `@gmail.com`) with SPF, DKIM
and DMARC; keep the daily cap low and warm up over 2–3 weeks; and have a lawful
basis for contacting each lead.

If reply handling is enabled, the **full text of each inbound reply** is sent to
**Anthropic** for classification. Anthropic is a data processor here — review
their [DPA](https://www.anthropic.com/legal/commercial-terms) and
[zero-retention](https://privacy.anthropic.com/) options, and disclose the
processing in your own privacy notice. The keyword opt-out scan calls no LLM.

---

## Development

```bash
python -m pytest        # 361 tests, fully network-free (Gmail / Calendar / Anthropic are faked)
```

### Repository layout

| Path | Contents |
|---|---|
| `kairo/` | The application package — see the module table below. |
| `kairo/web/` | The Flask dashboard: routes, the page templates, the offline stylesheet. |
| `tests/` | The pytest suite. No network — every external service is faked. |
| `docs/` | Setup guide, build guide, reply-handling design. |
| `packaging/` | PyInstaller spec, `build.ps1`, and the client's `START HERE.txt`. |
| `assets/` | App icon (`kairo.ico`), icon source, banner, and `make_icon.py`. |
| `.claude/agents/` | The `email-copywriter` subagent used to draft template copy. |

### `kairo/` modules

| Module | Responsibility |
|---|---|
| `__main__.py` | Single entry point; dispatches the CLI flags or opens the dashboard. |
| `desktop.py` | Runs the dashboard in a native pywebview window, with browser fallbacks. |
| `web/app.py` | The Flask dashboard — all routes and the background "Run now" job runner. |
| `core.py` | Shared sending logic: candidate selection, daily-cap trim, the send loops. |
| `config.py` | Load / save / migrate `config.json`. |
| `excel_store.py` | Read and write `clients.xlsx` — the whole lead store. |
| `column_map.py` | Detect which sheet headers map to Name / Company / Email / Phone / Priority. |
| `lead_fields.py` | Derive a greeting name and company for email-only rows. |
| `lead_sourcing.py` | The keyless "Find leads" web search + scrape. |
| `templates.py` | The default Jinja2 email templates and the render helper. |
| `scoring.py` · `segment.py` | Rules-based lead priority score and carrier/shipper classification. |
| `mailer.py` | Build and send the MIME message through the Gmail API. |
| `gmail_oauth.py` · `credentials.py` | The Connect Gmail OAuth flow and the `keyring` token store. |
| `gmail_read.py` | Fetch the latest inbound message per lead thread, strip quoted history. |
| `llm.py` · `llm_tracker.py` | `classify_reply()` — one forced-tool-use Haiku call — and the monthly spend counter. |
| `calendar_api.py` | Google Calendar free/busy, open-slot search, event creation. |
| `scheduling.py` | Turn a classification into a drafted action (`book` / `propose` / `decline_ack` / `manual`). |
| `reply_queue.py` | The approval queue; `approve()` is the only code that sends or books. |
| `process_replies.py` | The headless reply scan (`--replies`). |
| `send_cold.py` · `send_reminders.py` · `send_followups.py` | The headless send entry points. |
| `blocklist.py` · `manage_blocklist.py` · `suppression.py` | Block-by-domain-or-address and the shared retire-a-lead helper. |
| `optout_scan.py` · `bounce_scan.py` | Always-on keyword opt-out scan (no LLM) and bounce detection. |
| `send_tracker.py` | Daily send counter, warm-up ramp, and the History log. |
| `schedule_task.py` | Create / remove / query the Windows Task Scheduler jobs. |
| `diagnostics.py` · `dns_check.py` | The active connection checks behind the Diagnostics page. |
| `paths.py` · `locking.py` · `logging_setup.py` · `errors.py` | File locations, the data lock, logging, shared error types. |

---

## License

[MIT](LICENSE).
