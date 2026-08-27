"""The approval queue: drafted actions waiting for the client to click Approve.

Stored as JSONL at `paths.REPLY_QUEUE_PATH`, one record per line:

    {id, created_at, status, lead_row_idx, lead_email, lead_name, lead_company,
     thread_id, reply_summary, action: {...}}

status is "pending", "done", or "rejected".

`approve()` is the only place in the whole reply-handling feature that actually
reaches out - it creates the calendar event, sends the email, and writes the
lead's Excel row back. It respects the same daily send cap as the cold/reminder
batches: if the cap is spent, the item stays pending and approve() returns
`{"status": "deferred", ...}`.
"""

import json
import uuid
from datetime import datetime

from outreach import calendar_api
from outreach.config import get as cfg_get
from outreach.config import load_config
from outreach.core import build_mailer
from outreach.excel_store import ExcelStore
from outreach.logging_setup import get_logger
from outreach.paths import REPLY_QUEUE_PATH
from outreach.send_tracker import record_send_history, record_sent, remaining_today

log = get_logger("reply_queue")

_TS = "%Y-%m-%d %H:%M:%S"
_HUMAN = "%A, %b %d at %I:%M %p"


# --- persistence -----------------------------------------------------------

def _read_all():
    if not REPLY_QUEUE_PATH.exists():
        return []
    records = []
    for line in REPLY_QUEUE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            log.warning("Skipping an unreadable line in reply_queue.jsonl")
    return records


def _write_all(records):
    body = "\n".join(json.dumps(r) for r in records)
    REPLY_QUEUE_PATH.write_text(body + ("\n" if body else ""), encoding="utf-8")


def _jsonable_action(action):
    """Serialise an action dict: datetimes -> ISO strings, plus display helpers."""
    out = {}
    for key, value in action.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        elif isinstance(value, list):
            out[key] = [v.isoformat() if isinstance(v, datetime) else v for v in value]
        else:
            out[key] = value
    if isinstance(action.get("start"), datetime):
        out["start_display"] = action["start"].strftime(_HUMAN)
    slots = action.get("slots")
    if slots and isinstance(slots[0], datetime):
        out["slots_display"] = [s.strftime(_HUMAN) for s in slots]
    return out


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


# --- public API ----------------------------------------------------------

def enqueue(action, *, lead_row_idx=None, lead_email="", lead_name="",
            lead_company="", thread_id="", reply_summary=""):
    """Add a drafted action to the queue. Returns the new queue id.

    The action dict comes from `scheduling.plan_action`; the lead/thread metadata
    is passed as keywords by `process_replies`.
    """
    qid = uuid.uuid4().hex[:12]
    record = {
        "id": qid,
        "created_at": datetime.now().strftime(_TS),
        "status": "pending",
        "lead_row_idx": lead_row_idx,
        "lead_email": lead_email,
        "lead_name": lead_name,
        "lead_company": lead_company,
        "thread_id": thread_id,
        "reply_summary": reply_summary,
        "action": _jsonable_action(action),
    }
    records = _read_all()
    records.append(record)
    _write_all(records)
    return qid


def all_items():
    return list(reversed(_read_all()))


def pending():
    """Pending items, newest first."""
    return [r for r in reversed(_read_all()) if r.get("status") == "pending"]


def get(qid):
    for record in _read_all():
        if record.get("id") == qid:
            return record
    return None


def reject(qid):
    records = _read_all()
    hit = False
    for record in records:
        if record.get("id") == qid and record.get("status") == "pending":
            record["status"] = "rejected"
            record["resolved_at"] = datetime.now().strftime(_TS)
            hit = True
    if hit:
        _write_all(records)
    return hit


def _record_send(record):
    action = record.get("action", {})
    record_sent(1)
    record_send_history(
        "reply",
        record.get("lead_email"),
        record.get("lead_name"),
        record.get("lead_company"),
        action.get("email_subject") or action.get("kind") or "reply",
    )


def approve(qid, *, overrides=None, cfg=None, store=None, mailer=None):
    """Execute a pending item: create the event (if any), send the email, write
    the sheet. Returns a result dict with a "status" of:
        "done"     - executed; item marked done
        "deferred" - daily send cap reached; item left pending
        "error"    - nothing happened; "message" explains why

    `cfg` / `store` / `mailer` are injectable for tests; production builds them.
    """
    records = _read_all()
    record = next((r for r in records if r.get("id") == qid), None)
    if record is None:
        return {"status": "error", "message": f"Queue item {qid} not found."}
    if record.get("status") != "pending":
        return {"status": "error", "message": f"Item is already {record['status']}."}

    action = dict(record.get("action", {}))
    if overrides:
        action.update(overrides)
    kind = action.get("kind")

    if kind == "manual":
        return {
            "status": "error",
            "message": "This one needs manual scheduling - reply in Gmail, then reject it here.",
        }
    if kind not in ("book", "propose", "decline_ack"):
        return {"status": "error", "message": f"Unknown action kind '{kind}'."}

    cfg = cfg or load_config()
    daily_cap = cfg.get("daily_send_cap", 150)
    if remaining_today(daily_cap) <= 0:
        return {
            "status": "deferred",
            "message": f"Daily send cap ({daily_cap}) reached - approve this again tomorrow.",
        }

    to_addr = record.get("lead_email")
    row_idx = record.get("lead_row_idx")
    gmail_address = cfg.get("gmail_address")
    mailer = mailer or build_mailer(cfg)

    if store is None and row_idx is not None:
        try:
            store = ExcelStore(
                cfg["excel_path"],
                column_aliases=cfg.get("column_aliases"),
                disallowed_emails=cfg.get("disallowed_emails"),
                disallowed_domains=cfg.get("disallowed_domains"),
            )
        except Exception as e:  # noqa: BLE001 - a locked sheet shouldn't block the send
            log.warning("Could not open the sheet to record the outcome: %s", e)
            store = None

    event_id = None
    try:
        if kind == "book":
            start = _parse_dt(action["start"])
            duration = int(cfg_get(cfg, "meeting_duration_minutes"))
            event_id = calendar_api.create_event(
                gmail_address,
                cfg_get(cfg, "calendar_id"),
                summary=action.get("event_summary") or "Intro call",
                description=action.get("event_description") or "",
                start=start,
                duration_minutes=duration,
                attendee_email=to_addr,
                timezone=calendar_api.local_tz_name(),
                send_updates=True,
            )
            mailer.send(to_addr, action["email_subject"], action["email_body"])
            _record_send(record)
            if store is not None:
                store.set_value(row_idx, "MeetingDateTime", start.strftime(_TS))
                store.set_value(row_idx, "MeetingEventId", event_id)
                store.set_value(row_idx, "ReplyStatus", "booked")
            message = f"Booked {start.strftime('%b %d, %H:%M')} and emailed {to_addr}."

        elif kind == "propose":
            mailer.send(to_addr, action["email_subject"], action["email_body"])
            _record_send(record)
            if store is not None:
                store.set_value(row_idx, "ReplyStatus", "scheduling")
            message = f"Sent proposed times to {to_addr}."

        else:  # decline_ack
            mailer.send(to_addr, action["email_subject"], action["email_body"])
            _record_send(record)
            if store is not None:
                store.set_value(row_idx, "ReplyStatus", "no")
            message = f"Sent an acknowledgement to {to_addr}."

    except Exception as e:  # noqa: BLE001 - report the failure, leave the item pending
        log.error("approve(%s) failed: %s", qid, e)
        return {"status": "error", "message": f"Failed: {e}"}

    record["status"] = "done"
    record["resolved_at"] = datetime.now().strftime(_TS)
    if event_id:
        record["event_id"] = event_id
    _write_all(records)
    return {"status": "done", "message": message, "event_id": event_id}
