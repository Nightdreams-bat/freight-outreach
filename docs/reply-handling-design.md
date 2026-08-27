# Reply handling + auto-scheduling — design & contract

**STATUS: shipped 2026-08-27.** Built in 4 waves; ~120 unit tests (network-free,
fakes for Gmail/Calendar/Anthropic). `anthropic` bundled into the `.exe`. Two
manual steps to switch it on: re-connect Gmail for the new scopes, and add an
Anthropic API key in Settings. This doc is kept as the interface reference.

_Feature added 2026-08-27. This doc is the interface contract every module below
must honour so the pieces fit together. Read `STATUS.md` and `README.md` first
for how the existing tool works._

## Goal

After a cold email goes out, the tool should:

1. **Read the lead's reply** from Gmail.
2. **Classify it** with Claude (yes / no / maybe / question) and pull out any
   proposed meeting time.
3. On a **yes**: check the client's Google Calendar and **draft** a calendar
   invite + a confirmation email. If the lead's time is taken (or none was
   given), draft an email proposing 2–3 open slots instead.
4. Put every drafted action in an **approval queue** shown on a new dashboard
   page. Nothing is sent or booked until the client clicks **Approve**.
5. When the client approves a booking, write `MeetingDateTime` back to the lead's
   Excel row — the **existing reminder scan then sends the 24h reminder with no
   new code**.

Human-in-the-loop is deliberate: this is cold outreach to real businesses, one
bad auto-reply burns a lead or the sending reputation.

## Where it runs

- New batch entry point `outreach/process_replies.py` (mirrors
  `send_reminders.py`): scan → classify → draft → enqueue. Never sends/books.
- Wired into `outreach/__main__.py` as `--replies`.
- Its own scheduled task `FreightOutreach_ReplyCheck` (hourly), registered
  alongside the reminder task from the dashboard Automation section.
- Approvals execute synchronously in the Flask request when the client clicks
  Approve (same pattern as the existing "Send Now").

## New OAuth scopes (requires re-running "Connect Gmail")

`outreach/gmail_oauth.py` `SCOPES` becomes (confirmed by research):

```
https://www.googleapis.com/auth/gmail.send
https://www.googleapis.com/auth/gmail.readonly         # NEW - read replies
https://www.googleapis.com/auth/calendar.events        # NEW - events.insert
https://www.googleapis.com/auth/calendar.freebusy      # NEW - freebusy.query (events scope does NOT cover this)
https://www.googleapis.com/auth/userinfo.email
openid
```

The Settings page must tell the user that adding reply-handling means clicking
"Connect Gmail" again to grant the new permissions. These are Google
"sensitive/restricted" scopes — fine under the consent screen's Testing mode with
whitelisted test users (which is how this project is already set up).

## New Excel columns

Append to `LOGICAL_COLUMNS` in `outreach/excel_store.py` (order matters — append,
don't insert):

| Column | Values | Written by |
|---|---|---|
| `ReplyStatus` | `""`, `awaiting`, `yes`, `no`, `maybe`, `question`, `scheduling`, `booked` | `process_replies` / approval |
| `LastReplyAt` | `YYYY-MM-DD HH:MM:SS` | `process_replies` |
| `MeetingEventId` | Google Calendar event id | approval of a booking |

`MeetingDateTime` is **reused** — set it when a booking is approved so the
reminder scan picks it up. `Notes` gets Claude's one-line read of the reply
appended.

## New config keys (`config.json`, all optional with defaults)

```jsonc
{
  "reply_scan_enabled": false,          // gates the scheduled task
  "llm_model": "claude-haiku-4-5-20251001",
  "meeting_duration_minutes": 30,
  "business_hours": { "start": 9, "end": 17 },   // client's local time
  "business_days": [0,1,2,3,4],         // Mon-Fri, Python weekday()
  "scheduling_window_days": 10,         // how far out to propose slots
  "min_notice_hours": 24,              // don't propose slots sooner than this
  "calendar_id": "primary",
  "reply_lookback_days": 30            // ignore threads older than this
}
```

`outreach/config.py` `load_config` must not break on an old config that lacks
these — callers use `cfg.get(key, default)`. Add the defaults to
`outreach/setup.py`'s generated config and (optionally) prompt for
duration/business hours.

## Credentials

`outreach/credentials.py` gains an Anthropic key pair, same keyring pattern:

```python
ANTHROPIC_SERVICE = "freight-outreach-anthropic"
def set_anthropic_key(key): _keyring().set_password(ANTHROPIC_SERVICE, "api_key", key)
def get_anthropic_key():     # returns None if unset (NOT an exception - LLM is optional)
```

Dashboard Settings gets a field to paste/save the Anthropic key (write-only —
show "configured" / "not set", never the value).

---

## Confirmed API details (from research — implement to these exactly)

### Anthropic (`anthropic` SDK)

- Model: `claude-haiku-4-5-20251001`. Pricing $1/$5 per 1M tok in/out.
- Key: `anthropic.Anthropic(api_key=credentials.get_anthropic_key())` — do NOT
  rely on the env var (we store in keyring).
- Per-call options: `client.with_options(timeout=20.0, max_retries=2)`. Defaults
  are 10-min timeout / 2 retries; set the 20s timeout explicitly.
- **Structured output = forced tool use** (portable across models, unlike
  `messages.parse`). One tool with an `input_schema`, `tool_choice={"type":
  "tool", "name": "<tool>"}`. Read the result from the first `tool_use` block's
  `.input` (already a dict). Example schema — intent enum
  `["yes","no","maybe","question"]`, `proposed_start`/`proposed_end` as
  `["string","null"]` ISO8601, `notes` string; all `required`,
  `additionalProperties: false`. System prompt: classifier role, "call the tool
  exactly once", "naive ISO 8601 unless the sender states a timezone", "null when
  no specific time given", be conservative (ambiguous → `maybe`).

### Google Calendar (`build("calendar","v3",credentials=creds)`)

- **freebusy**: `service.freebusy().query(body={"timeMin": rfc3339,
  "timeMax": rfc3339, "timeZone": iana, "items": [{"id": calendar_id}]}).execute()`.
  Busy list: `resp["calendars"][calendar_id]["busy"]` → `[{"start","end"}]`
  RFC3339, start inclusive / end exclusive. Check
  `resp["calendars"][calendar_id].get("errors")`.
- **create event**: `service.events().insert(calendarId=calendar_id,
  body={"summary","description","start":{"dateTime": local_iso, "timeZone": iana},
  "end":{...},"attendees":[{"email": lead_email}]}, sendUpdates="all").execute()`
  → returns dict; use `["id"]` and `["htmlLink"]`. `sendUpdates="all"` sends the
  real invite email with Accept/Decline and puts it on the attendee's calendar.
- Timezone: IANA name. Helper `local_tz_name()` — from
  `datetime.now().astimezone().tzinfo` / `tzlocal` if needed; fall back to config.

### Gmail read (`build("gmail","v1",credentials=creds)`)

- `gmail.users().threads().list(userId="me", q=f"from:{addr} newer_than:{N}d",
  maxResults=...)` — newest first.
- `threads().get(userId="me", id=tid, format="full")` → `["messages"]`
  chronological. Inbound msg = a `From` header containing the lead's address.
- Body: recurse `payload` for `mimeType == "text/plain"` with `body.data`;
  `base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")`.
  If only `text/html` exists, strip tags as a fallback. If `body.attachmentId`
  instead of `body.data`, fetch via `messages().attachments().get()` (rare —
  best-effort, skip if missing).

## Module contracts

### `outreach/llm.py`

```python
class LLMNotConfigured(RuntimeError): ...

def classify_reply(reply_text: str, *, sender_company: str, now_iso: str,
                   model: str) -> dict:
    """Returns:
      {
        "intent": "yes" | "no" | "maybe" | "question",
        "proposed_start": str | None,   # ISO8601 local, no tz suffix
        "proposed_end":   str | None,   # ISO8601 or None (caller applies duration)
        "summary": str,                 # <= 120 chars, plain English
      }
    Raises LLMNotConfigured if no Anthropic key in keyring.
    """
```

- Key from `credentials.get_anthropic_key()`; raise `LLMNotConfigured` if `None`.
- Use the `anthropic` SDK, forced tool-use for structured output (research agent
  provides the exact pattern). Model id from the `model` arg.
- Be conservative: if the text is ambiguous, return `maybe`, not `yes`.
- 2 retries, ~20s timeout. On API failure raise the SDK error (caller logs & skips).
- Unit-testable: accept an optional `client=None` arg so tests inject a fake.

### `outreach/gmail_read.py`

```python
def fetch_new_replies(gmail_address: str, lookback_days: int,
                      lead_emails: list[str]) -> list[dict]:
    """For each address in lead_emails, find the most recent INBOUND message in a
    thread with that address, newer than lookback_days, not already processed.
    Returns [{ "email": str, "thread_id": str, "message_id": str,
               "received_at": "YYYY-MM-DD HH:MM:SS", "text": str }].
    """

def mark_processed(message_ids: list[str]) -> None: ...
def is_processed(message_id: str) -> bool: ...
```

- Scope `gmail.readonly`. `service = build("gmail","v1",...)` via
  `outreach.gmail_oauth.get_credentials(gmail_address)`.
- Processed-message tracking: JSON file at
  `outreach.paths.data_dir() / "processed_replies.json"` (list of ids, capped at
  last ~2000). New `PROCESSED_REPLIES_PATH` constant in `paths.py`.
- `text`: decoded `text/plain` part of the message; strip quoted history below
  the first `On ... wrote:` / leading `>` block (best-effort helper `_strip_quoted`).
- Inbound = `From` is the lead, not `gmail_address`.

### `outreach/calendar_api.py`

```python
def busy_intervals(gmail_address: str, calendar_id: str,
                   start_iso: str, end_iso: str) -> list[tuple[str, str]]:
    """freebusy.query -> list of (busy_start_iso, busy_end_iso)."""

def find_open_slots(gmail_address: str, calendar_id: str, *,
                    duration_minutes: int, business_hours: dict,
                    business_days: list[int], window_days: int,
                    min_notice_hours: int, count: int = 3,
                    now: datetime | None = None) -> list[datetime]:
    """Return up to `count` slot-start datetimes that are inside business
    hours/days, >= now + min_notice_hours, and not overlapping any busy interval."""

def slot_is_free(gmail_address: str, calendar_id: str,
                 start: datetime, duration_minutes: int) -> bool: ...

def create_event(gmail_address: str, calendar_id: str, *, summary: str,
                 description: str, start: datetime, duration_minutes: int,
                 attendee_email: str, timezone: str,
                 send_updates: bool = True) -> str:
    """events.insert -> returns the created event id."""
```

- Scope from the Gmail OAuth (already granted). Timezone: use the machine's
  local tz name; helper `local_tz_name()` in this module.
- All datetimes naive-local in, ISO strings to the API with tz offset applied.

### `outreach/scheduling.py`

```python
def plan_action(classification: dict, lead: dict, cfg: dict,
                gmail_address: str) -> dict | None:
    """Turn a classification into a drafted action (or None = nothing to queue).
    Returns one of:
      {"kind": "book",       "start": datetime, "email_subject": str,
       "email_body": str, "event_summary": str, "event_description": str}
      {"kind": "propose",    "slots": [datetime,...], "email_subject": str,
       "email_body": str}
      {"kind": "decline_ack", "email_subject": str, "email_body": str}
      {"kind": "manual",     "reason": str}      # maybe / question -> no draft, just flag
    """
```

Rules:
- `no` → `decline_ack` (a short polite acknowledgement, still queued so client
  can choose to send or not).
- `maybe` / `question` → `manual`.
- `yes` + proposed_start present + `slot_is_free` → `book`.
- `yes` + proposed_start present + conflict → `propose` with `find_open_slots`.
- `yes` + no proposed_start → `propose`.
- If Calendar API errors, degrade to `manual` with the reason.

Email bodies rendered from new templates (below) via `outreach.templates.render`.

### `outreach/reply_queue.py`

```python
def enqueue(action: dict) -> str: ...        # returns queue id
def pending() -> list[dict]: ...              # newest first
def get(qid: str) -> dict | None: ...
def approve(qid: str, *, overrides: dict | None = None) -> dict:
    """Execute the action: send email and/or create event and/or write Excel.
    Marks the item done. Returns a result dict for the flash message."""
def reject(qid: str) -> None: ...
```

- Store: JSONL at `outreach.paths.data_dir() / "reply_queue.jsonl"` (new
  `REPLY_QUEUE_PATH` in `paths.py`). Each record:
  `{id, created_at, status: "pending"|"done"|"rejected", lead_row_idx, lead_email,
    lead_name, lead_company, thread_id, reply_summary, action: {...}}`.
- `approve` for `kind=book`: `calendar_api.create_event` → `mailer.send` the
  confirmation → `store.set_value(row_idx, "MeetingDateTime", ...)`,
  `"MeetingEventId"`, `"ReplyStatus"="booked"`. Reuses `outreach.core.build_mailer`.
- `approve` for `kind=propose`: `mailer.send` the proposal → `ReplyStatus="scheduling"`.
- `approve` for `decline_ack`: `mailer.send` → `ReplyStatus="no"`.
- Every send also goes through `send_tracker.record_sent(1)` +
  `record_send_history("reply", ...)` and respects the daily cap
  (`core.remaining_today`); if the cap is hit, `approve` returns a "deferred" result
  and leaves the item pending.

### `outreach/process_replies.py`

`main()` (argparse `--dry-run`):
1. `cfg = load_config()`; if `not cfg.get("reply_scan_enabled")` → log & return.
2. Build the lead list from `ExcelStore`: rows with `ColdEmailSentAt` set and
   `ReplyStatus` not in `{"booked","no"}`.
3. `replies = gmail_read.fetch_new_replies(...)`.
4. For each reply: `classify_reply` → `plan_action` → `reply_queue.enqueue`
   (skip `manual` kind? no — enqueue it too so it shows in the UI as "needs you").
   Update Excel `ReplyStatus` / `LastReplyAt` / append `summary` to `Notes`.
   `gmail_read.mark_processed([message_id])`.
5. Log a summary line. Never sends or books.

### Templates — add to `outreach/templates.py`

```
MEETING_CONFIRM_SUBJECT / MEETING_CONFIRM_BODY
    vars: name, company, sender_name, sender_company, sender_phone, meeting_time
PROPOSE_TIMES_SUBJECT / PROPOSE_TIMES_BODY
    vars: ... , slots (list of pre-formatted strings)
DECLINE_ACK_SUBJECT / DECLINE_ACK_BODY
    vars: name, company, sender_name, sender_company
```

Same voice as the existing cold/reminder templates — plain, human, no "unsubscribe"
boilerplate. Add them to the config that `setup.py` writes and expose them on the
Settings page like the others.

### Dashboard — `outreach/web/app.py` + `templates/replies.html`

- Nav link "Replies" (between Send and History). `active` key `"replies"`.
- `GET /replies`: list `reply_queue.pending()`. For each: lead name/company/email,
  their reply summary, and the drafted action — for `book` show the proposed time
  + the confirmation email; for `propose` show the slots + email; for `manual`
  show "needs manual scheduling: {reason}" with a link to open the Gmail thread.
- `POST /replies/<qid>/approve` → `reply_queue.approve`, flash the result.
- `POST /replies/<qid>/reject` → `reply_queue.reject`.
- (Nice-to-have, not required v1: an edit form to tweak the time/text before approving.)
- Dashboard home (`/`) stat: number of pending reply actions.
- Settings: Anthropic key field; reply-scan enable/disable toggle that
  registers/unregisters `FreightOutreach_ReplyCheck`.

### `outreach/schedule_task.py`

Generalise: `register_task(name, interval_hours, cli_flag)` /
`unregister_task(name)` / `task_status(name)`. Keep the reminder task working
(`FreightOutreach_ReminderCheck`, `--reminders`). Add helpers for the reply task
(`FreightOutreach_ReplyCheck`, `--replies`). The frozen-exe vs `python -m`
command logic already exists — just parametrise the flag.

### `outreach/__main__.py`

Add `--replies` → `from outreach.process_replies import main`. Extend
`_selfcheck` to also: import `anthropic`, report whether the Anthropic key and
`reply_scan_enabled` are set, and check the new templates render.

### `requirements.txt` / `requirements-build.txt` / `FreightOutreach.spec`

- Add `anthropic` to `requirements.txt`.
- Spec: `collect_submodules("anthropic")` if needed; add `anthropic` and its deps
  are pure-python + httpx (already pulled by google libs? verify). Rebuild & selfcheck.

### Docs

Update `README.md`, `STATUS.md`, `BUILD.md`, and `START_HERE.txt` for: the new
scopes (re-connect Gmail), the Anthropic key, the Replies page, the second
scheduled task, the new config keys and Excel columns.

## Testing

Each module ships with `tests/test_<module>.py` (pytest, add `pytest` to
`requirements-build.txt`). Fakes for the Gmail/Calendar/Anthropic clients — no
network in tests. Cover: classification routing in `scheduling.plan_action`
(every branch), `find_open_slots` (conflict at edges, business-hours boundary,
min-notice), `reply_queue` approve/reject state transitions, `_strip_quoted`.

## Build order

1. `paths.py` constants, `config.py` defaults, `credentials.py` keys,
   `excel_store.py` columns, `templates.py` additions — small, no deps.
2. `llm.py`, `gmail_read.py`, `calendar_api.py` — parallel, each against its contract.
3. `scheduling.py`, `reply_queue.py`, `process_replies.py`.
4. Dashboard page, `schedule_task.py`, `__main__.py`, requirements/spec.
5. Docs, rebuild exe, full selfcheck.
