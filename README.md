# Freight Outreach Agent

Sends personalized cold-intro emails to leads and automatic reminders ~24h before a scheduled call, reading from a local Excel file (`clients.xlsx`).

It can also **read the replies**: Claude classifies each response (yes / no / maybe / question), and for a "yes" it drafts a Google Calendar invite plus a confirmation email — or, if the lead's time is taken, an email proposing open slots from the client's calendar. Nothing is sent or booked until the client approves it on the **Replies** page. See [Reply handling & auto-scheduling](#reply-handling--auto-scheduling).

## One-time setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
2. **Google Cloud OAuth Client** (one-time, done once by the developer - the client never touches this): a "Sign in with Google" button requires a registered OAuth Client ID, which is Google's requirement for any app showing their login screen. In Google Cloud Console:
   - Create a project, enable the **Gmail API** and the **Google Calendar API**.
   - Configure the **OAuth consent screen**: External, add every Gmail address that will ever click "Connect Gmail" (yours and the client's) as a **test user** - the app runs in Testing mode, which skips Google's weeks-long verification process and is the right fit for a single client's tool, but restricts sign-in to that test-user list.
   - Scopes requested by the app: `gmail.send`, `gmail.readonly` (read replies), `calendar.events` (create invites), `calendar.freebusy` (check the calendar for conflicts), plus `openid` / `userinfo.email`. All are Google "sensitive/restricted" scopes; Testing mode with whitelisted test users is fine for them.
   - Create an **OAuth Client ID** of type "Desktop app", download the JSON, and save it as `client_secret.json` in this project folder.

   > If you already set this up with only `gmail.send`: add the Calendar API + the new scopes above, then have each connected account click **Connect Gmail** again to re-consent. The old token doesn't carry the new permissions.
3. Start the dashboard:
   ```
   python -m outreach
   ```
   There is no setup wizard. `config.json` is created with defaults on first run;
   everything - business details, the path to `clients.xlsx`, column mapping,
   sending limits, the scheduled task - is configured on the **Settings** page.
   The dashboard shows a short checklist until the essentials are filled in.
4. In Settings, click **Connect Gmail** - this is the client's *entire* part of the setup: a normal Google sign-in page opens, they log in, click Allow, done. No passwords typed anywhere, no Google Cloud Console. The token is stored in the Windows Credential Manager via `keyring` and auto-refreshes, so this is a true one-time login.

## Excel file (`clients.xlsx`)

Default columns (created automatically if missing; the reply-handling columns are added to an existing sheet automatically on first run):

| Name | Company | Email | Phone | MeetingDateTime | Status | ColdEmailSentAt | ReminderSentAt | Suppressed | Notes | ReplyStatus | LastReplyAt | MeetingEventId |
|------|---------|-------|-------|------------------|--------|------------------|-----------------|------------|-------|-------------|-------------|----------------|

- `MeetingDateTime`: `YYYY-MM-DD HH:MM` (24h clock), e.g. `2026-08-27 14:00`. Set automatically when a booking is approved, which then feeds the normal 24h reminder.
- `ColdEmailSentAt` / `ReminderSentAt` fill in automatically - leave blank for leads not yet contacted.
- `ReplyStatus` (`awaiting` / `yes` / `no` / `maybe` / `question` / `scheduling` / `booked`), `LastReplyAt`, and `MeetingEventId` are maintained by the reply scan and the Replies page - leave them blank.
- `Suppressed`: set to `yes`/`1`/`true` to permanently exclude a lead from both flows (e.g. after a STOP reply). Checked automatically before every send.
- **Your sheet can use its own headers.** The app matches them automatically - `Surname`, `Organisation`, `E-mail Address`, a split first-name / last-name pair, etc. Settings → *Lead spreadsheet columns* shows what it detected and lets you correct any guess. The mapping is stored in `config.json` as `column_map`.
- **A row with only an email still works.** The greeting name is derived from the address (`j.doe@acme-freight.com` → "Doe"), and the company from the domain (→ "Acme Freight"). Real values in the sheet always take precedence.

## Dashboard

A local web UI, styled after a classic admin dashboard (dark sidebar, stat cards, data tables):
```
python -m outreach
```
Opens your browser to `http://127.0.0.1:5000` (bound to localhost only, no network exposure). Everything is driven from **Settings**, no terminal required:

- **Excel file** - a "Browse..." button opens a real Windows file picker (via `tkinter`) to point the tool at your `clients.xlsx` anywhere on disk.
- **Lead spreadsheet columns** - the auto-detected Name/Company/Email/Phone mapping, with a dropdown per field to override a wrong guess.
- **Gmail account** - a "Connect Gmail" button opens the real Google sign-in screen (OAuth) - see [One-time setup](#one-time-setup). Shows the connected address once done, with a "Reconnect" option.
- **Automation** - shows whether the 24h-before-meeting reminder scan is currently running in the background (Windows Task Scheduler) with an Enable/Disable button, plus a plain-language explanation of what it actually does.
- **Business details & email templates** - every field has its explanation right next to it (what it affects, what happens if left blank), plus a live From-line preview so the effect of the name/company fields is visible immediately.
- **Sending limits** - the four numeric caps, each with an explanation of what it protects against.

The Leads page shows every column from the sheet (including Phone and Notes) with per-lead Suppress/Unsuppress, and Send lets you trigger a batch on demand. All of it is backed by the same `clients.xlsx` and `outreach/core.py` logic the CLI and scheduled task use, so nothing behaves differently depending on which interface you used.

## Email templates

Cold-intro and reminder emails are fully custom, written as [Jinja2](https://jinja.palletsprojects.com/) text in Settings (or by editing `cold_subject_template` / `cold_body_template` / `reminder_subject_template` / `reminder_body_template` in `config.json` directly). Available variables:

- Cold intro: `name`, `company`, `phone`, `sender_name`, `sender_company`, `sender_phone`, `sender_pitch`
- Reminder: the same, plus `meeting_time`

Use `{{ variable }}` to insert a value. To skip a line cleanly when a field is empty (e.g. a lead with no `Phone`, or a business that leaves `sender_phone` blank) rather than leaving an awkward gap, wrap it in a conditional on one line:
```
{% if sender_phone %}{{ sender_phone }}{% endif %}
```
Before any real batch is sent, both templates are rendered once against dummy data as a pre-flight check - a typo (like an unmatched `{% if %}`) shows one clear error and sends **nothing**, instead of crashing partway through a batch of real leads.

## Reply handling & auto-scheduling

Optional. When enabled, a second background scan reads replies to the cold emails and prepares the follow-up, but **never sends or books anything itself** — every action waits for the client's approval on the dashboard's **Replies** page.

### What it does per reply

1. **Read** — finds the most recent inbound message in the Gmail thread with that lead (`gmail.readonly`), strips the quoted history.
2. **Classify** — Claude (`claude-haiku-4-5`) returns `intent` (`yes` / `no` / `maybe` / `question`), any proposed date/time, and a one-line summary. Conservative: anything ambiguous is `maybe`, not `yes`.
3. **Plan a drafted action**:
   - **yes + a time that's free** on the client's calendar → draft a calendar invite + a confirmation email.
   - **yes + that time is taken, or no time given** → draft an email proposing 2–3 open slots (pulled from `freebusy` within business hours/days, respecting a minimum notice).
   - **no** → draft a short polite acknowledgement (queued, not auto-sent).
   - **maybe / question / calendar error** → flag as "needs manual scheduling" with a link to the Gmail thread. No draft.
4. **Queue** — the drafted action lands on the Replies page.

### Approving

On **Replies**, each item shows the lead, Claude's read of their message, and the draft. **Approve** does the real work: creates the calendar event (`sendUpdates=all`, so the lead gets a normal invite), sends the email through the same Gmail account, and — for a booking — writes `MeetingDateTime` back to the sheet so the **existing 24h reminder fires with no extra setup**. **Reject** discards it. Approvals count against the same daily send cap; if the cap is hit the item stays pending.

### Turning it on

1. **Re-connect Gmail** (Settings → Connect Gmail) so the new Gmail/Calendar scopes are granted.
2. Paste an **Anthropic API key** into Settings → *Reply handling & auto-scheduling* (stored in the OS credential store, never written to a file). ~$0.001 per reply on Haiku.
3. Click **Enable** on the reply automation toggle — this registers a second Windows scheduled task, `FreightOutreach_ReplyCheck`, that runs the scan on the same interval as the reminder task.

Run the scan manually any time:
```
python -m outreach --replies            # or: FreightOutreach.exe --replies
python -m outreach.process_replies --dry-run
```

### Config keys (all optional, sensible defaults)

`reply_scan_enabled`, `llm_model`, `meeting_duration_minutes` (30), `business_hours` (`{"start":9,"end":17}`), `business_days` (`[0,1,2,3,4]`), `scheduling_window_days` (10), `min_notice_hours` (24), `calendar_id` (`"primary"`), `reply_lookback_days` (30). Plus the three new templates: `meeting_confirm_*`, `propose_times_*`, `decline_ack_*` (edit in Settings like the others).

## Usage

**Mode 1 - on demand**, whenever you decide to reach out to new leads in the sheet:
```
python -m outreach.send_cold --dry-run   # preview first
python -m outreach.send_cold             # sends after a y/n confirmation showing the count
python -m outreach.send_cold --yes       # skip the confirmation (e.g. for scripting)
```

**Mode 2 - scheduled**, runs automatically via the Windows Task Scheduler task created during setup (`FreightOutreach_ReminderCheck`), checking every N hours for leads whose `MeetingDateTime` is ~24h away and emailing a reminder. Can also be run manually:
```
python -m outreach.send_reminders --dry-run
python -m outreach.send_reminders
```
The check window equals the check interval, so consecutive runs always overlap and no meeting slips through the gap between two runs - this trades a little timing precision (reminder may go out anywhere from ~1-2x the interval before the meeting) for the guarantee that every lead gets exactly one reminder, which was the original point of automating this.

As a safety net, if a single run ever matches more reminders than the configured cap (default 25), it sends **none** of them and logs a critical warning instead - protects against a data-entry mistake (e.g. many rows sharing one date) turning into an accidental mass-email.

To re-create or change the scheduled task later:
```
python -m outreach.schedule_task
```

## Daily send cap and blocklist

Both flows share one **daily send cap** (default 150, well under Gmail's own ~500/day limit) so a burst of new leads can't accidentally blast the inbox's reputation in one go - `send_cold` defers the overflow to the next run, `send_reminders` prioritizes the soonest meetings and logs a critical warning for any reminder it couldn't send. Tracked in `send_log.json`.

There's also a **permanent blocklist**, separate from the per-lead `Suppressed` column, for blocking an entire domain or a specific address once and having it apply forever (e.g. after a bounce, or a company that asked never to be contacted again):
```
python -m outreach.manage_blocklist block-domain example.com
python -m outreach.manage_blocklist block-email person@example.com
python -m outreach.manage_blocklist list
```

## Reliability notes

- Every send is written back to `clients.xlsx` immediately, so a crash mid-batch never causes a duplicate send on the next run.
- If `clients.xlsx` is open in Excel when a script tries to save, it logs a clear error (`ExcelFileLocked`) instead of losing the write - close the file and re-run.
- Malformed rows (bad email format, unparsable `MeetingDateTime`) are skipped with a logged warning rather than silently dropped or crashing the whole batch.
- The scheduled task runs via `pythonw.exe` (no console window flashing every run) and logs are written to `outreach.log`, which auto-rotates at 1MB (keeps 3 backups) so it won't grow unbounded over months of unattended use.
- `config.json`, `client_secret.json`, `clients.xlsx`, and `send_log.json` are gitignored - if this folder is ever put under version control, credentials, lead data, settings, and send counts won't be committed.
- Every email's From line shows "Sender Name - Company \<gmail address\>" (via `email.utils.formataddr` in `outreach/mailer.py`), not a bare address - so recipients see who and what business it's from at a glance.
- Sending goes through the Gmail API (OAuth), not raw SMTP - no App Passwords involved anywhere in this version.

## Known limitations (by design, not oversights)

- Reply handling reads the inbox only when enabled and only for threads with known leads; a "not interested" still has to be turned into a `Suppressed` / blocklist entry by hand (the drafted acknowledgement is a convenience, not an unsubscribe system).
- Since data stays in a local Excel file, the scheduled reminder only runs while this PC is on. If that becomes a problem, migrating `excel_store.py`'s storage to Google Sheets and the scheduler to a cloud cron job is the natural upgrade path.
- No open/click tracking (the "which leads are actually engaging" view some cold-email tools have) - that requires a hosted server to serve a tracking pixel and receive webhooks, which is a different class of infrastructure than a local script. Worth adding later if this grows into something bigger.
