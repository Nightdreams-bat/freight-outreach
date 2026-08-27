import re
import time
from datetime import datetime, timedelta

import jinja2

from outreach.excel_store import ExcelFileLocked
from outreach.lead_fields import lead_company, lead_name
from outreach.logging_setup import get_logger
from outreach.mailer import Mailer
from outreach.send_tracker import record_send_history, record_sent, remaining_today
from outreach.config import get as cfg_get
from outreach.scoring import score_lead
from outreach.templates import (
    COLD_INTRO_BODY,
    COLD_INTRO_SUBJECT,
    FOLLOWUP_BODY,
    FOLLOWUP_BREAKUP_BODY,
    FOLLOWUP_SUBJECT,
    REMINDER_BODY,
    REMINDER_SUBJECT,
    render,
)

log = get_logger("core")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SEND_DELAY_SECONDS = 3  # spread sends out a bit; avoids looking like a mail blast
MEETING_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M")

# dummy values used only to pre-flight-check a user's custom template before a real batch runs
_DUMMY_CONTEXT = {
    "name": "Sample Lead", "company": "Sample Co", "phone": "555-0100",
    "sender_name": "Sample Sender", "sender_company": "Sample Company",
    "sender_phone": "555-0100", "sender_pitch": "Sample pitch.",
    "meeting_time": "Monday, Jan 1 at 10:00 AM",
    "stage": 1, "is_last": False,
}


def parse_meeting_time(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    for fmt in MEETING_TIME_FORMATS:
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None  # caller decides: unparsable but non-empty is a data problem, not "no meeting"


def cold_candidates(store):
    return [(row_idx, row) for row_idx, row in store.rows() if not row.get("ColdEmailSentAt")]


def reminder_candidates(store, window_hours):
    """Rows whose MeetingDateTime falls within target(24h) +/- window_hours and haven't been reminded."""
    window = timedelta(hours=window_hours)
    target = timedelta(hours=24)
    now = datetime.now()

    candidates = []
    for row_idx, row in store.rows():
        if row.get("ReminderSentAt"):
            continue
        raw_meeting_time = row.get("MeetingDateTime")
        meeting_time = parse_meeting_time(raw_meeting_time)
        if meeting_time is None:
            if raw_meeting_time:
                log.warning(f"Row {row_idx}: couldn't parse MeetingDateTime '{raw_meeting_time}'")
            continue
        delta = meeting_time - now
        if target - window <= delta <= target + window:
            candidates.append((row_idx, row, meeting_time))
    return candidates


def followup_candidates(store, cfg, now=None):
    """Leads that got a cold intro, never replied, have no meeting booked, and are
    due for their next follow-up nudge.

    Returns a list of (row_idx, row, stage) where `stage` is the 0-based index of
    the follow-up about to be sent (0 = first nudge). The drip stops the moment a
    lead replies (any non-empty ReplyStatus) or a meeting is on the sheet.
    """
    now = now or datetime.now()
    offsets = list(cfg_get(cfg, "followup_offsets_days") or [])
    if not offsets:
        return []

    candidates = []
    for row_idx, row in store.rows():
        cold_at = parse_meeting_time(row.get("ColdEmailSentAt"))
        if cold_at is None:
            continue
        if str(row.get("ReplyStatus") or "").strip():
            continue
        if row.get("MeetingDateTime"):
            continue

        try:
            stage = int(float(str(row.get("FollowupStage")).strip())) if row.get("FollowupStage") not in (None, "") else 0
        except (TypeError, ValueError):
            stage = 0
        if stage < 0:
            stage = 0
        if stage >= len(offsets):
            continue

        last_touch = parse_meeting_time(row.get("FollowupSentAt")) or cold_at
        due_after = timedelta(days=float(offsets[stage]))
        if now - last_touch >= due_after:
            candidates.append((row_idx, row, stage))
    return candidates


def build_mailer(cfg):
    return Mailer(cfg["gmail_address"], cfg.get("sender_name"), cfg.get("sender_company"))


def priority_sort_key(cfg):
    """sort_key for apply_daily_cap that puts the highest-priority leads first.

    Works for both cold `(row_idx, row)` and follow-up `(row_idx, row, stage)`
    candidate tuples - the row dict is always element 1.
    """
    return lambda c: -score_lead(c[1], cfg)


def apply_daily_cap(candidates, daily_cap, sort_key=None):
    """Trims candidates to what's left of today's send quota.

    Returns (trimmed_candidates, remaining_before_trim, deferred_count).
    """
    remaining = remaining_today(daily_cap)
    if sort_key:
        candidates = sorted(candidates, key=sort_key)
    deferred = max(0, len(candidates) - remaining)
    return candidates[:remaining], remaining, deferred


def _check_template(subject_tmpl, body_tmpl):
    """Renders both templates against dummy data. Returns an error message, or None if OK."""
    try:
        render(subject_tmpl, **_DUMMY_CONTEXT)
        render(body_tmpl, **_DUMMY_CONTEXT)
        return None
    except jinja2.TemplateError as e:
        return f"Template error: {e}"


def send_cold_batch(cfg, store, mailer, candidates, dry_run=False):
    """Sends the cold-intro email to each candidate row. Returns a summary dict."""
    result = {"sent": 0, "skipped": [], "errors": [], "preview": []}

    subject_tmpl = cfg.get("cold_subject_template") or COLD_INTRO_SUBJECT
    body_tmpl = cfg.get("cold_body_template") or COLD_INTRO_BODY

    template_error = _check_template(subject_tmpl, body_tmpl)
    if template_error:
        log.critical(f"Cold intro template is broken, sent nothing: {template_error}")
        result["errors"].append(template_error)
        return result

    for row_idx, row in candidates:
        email = str(row["Email"]).strip()
        if not EMAIL_RE.match(email):
            log.warning(f"Skipping row {row_idx}: '{email}' doesn't look like a valid email address")
            result["skipped"].append(email)
            continue

        context = {
            "name": lead_name(row),
            "company": lead_company(row),
            "phone": row.get("Phone") or "",
            "sender_name": cfg["sender_name"],
            "sender_company": cfg["sender_company"],
            "sender_phone": cfg.get("sender_phone") or "",
            "sender_pitch": cfg.get("sender_pitch") or "",
        }
        subject = render(subject_tmpl, **context)
        body = render(body_tmpl, **context)

        if dry_run:
            result["preview"].append({"email": email, "subject": subject, "body": body})
            continue

        try:
            mailer.send(email, subject, body)
            store.mark_sent(row_idx, "ColdEmailSentAt")
            record_sent(1)
            record_send_history("cold", email, row.get("Name"), row.get("Company"), subject)
            log.info(f"Sent cold intro to {email} (row {row_idx})")
            result["sent"] += 1
            time.sleep(SEND_DELAY_SECONDS)
        except ExcelFileLocked as e:
            log.critical(f"Email to {email} was sent but could not be marked as sent: {e}")
            result["errors"].append(str(e))
        except Exception as e:
            log.error(f"Failed to send to {email} (row {row_idx}): {e}")
            result["errors"].append(str(e))

    return result


def send_reminder_batch(cfg, store, mailer, candidates, dry_run=False):
    """Sends the reminder email to each (row_idx, row, meeting_time) candidate. Returns a summary dict."""
    result = {"sent": 0, "skipped": [], "errors": [], "preview": []}

    subject_tmpl = cfg.get("reminder_subject_template") or REMINDER_SUBJECT
    body_tmpl = cfg.get("reminder_body_template") or REMINDER_BODY

    template_error = _check_template(subject_tmpl, body_tmpl)
    if template_error:
        log.critical(f"Reminder template is broken, sent nothing: {template_error}")
        result["errors"].append(template_error)
        return result

    for row_idx, row, meeting_time in candidates:
        email = str(row["Email"]).strip()
        if not EMAIL_RE.match(email):
            log.warning(f"Skipping row {row_idx}: '{email}' doesn't look like a valid email address")
            result["skipped"].append(email)
            continue

        context = {
            "name": lead_name(row),
            "company": lead_company(row),
            "phone": row.get("Phone") or "",
            "meeting_time": meeting_time.strftime("%A, %b %d at %I:%M %p"),
            "sender_name": cfg["sender_name"],
            "sender_company": cfg["sender_company"],
            "sender_phone": cfg.get("sender_phone") or "",
        }
        subject = render(subject_tmpl, **context)
        body = render(body_tmpl, **context)

        if dry_run:
            result["preview"].append({"email": email, "subject": subject, "body": body})
            continue

        try:
            mailer.send(email, subject, body)
            store.mark_sent(row_idx, "ReminderSentAt")
            record_sent(1)
            record_send_history("reminder", email, row.get("Name"), row.get("Company"), subject)
            log.info(f"Sent reminder to {email} (row {row_idx})")
            result["sent"] += 1
            time.sleep(SEND_DELAY_SECONDS)
        except ExcelFileLocked as e:
            log.critical(f"Reminder to {email} was sent but could not be marked as sent: {e}")
            result["errors"].append(str(e))
        except Exception as e:
            log.error(f"Failed to send reminder to {email} (row {row_idx}): {e}")
            result["errors"].append(str(e))

    return result


def send_followup_batch(cfg, store, mailer, candidates, dry_run=False):
    """Sends the next follow-up nudge to each (row_idx, row, stage) candidate.

    Bumps FollowupStage and stamps FollowupSentAt on success. The final touch
    (stage == len(offsets) - 1) uses the breakup body. Returns a summary dict.
    """
    result = {"sent": 0, "skipped": [], "errors": [], "preview": []}

    offsets = list(cfg_get(cfg, "followup_offsets_days") or [])
    last_stage = len(offsets) - 1

    subject_tmpl = cfg.get("followup_subject_template") or FOLLOWUP_SUBJECT
    body_tmpl = cfg.get("followup_body_template") or FOLLOWUP_BODY
    breakup_tmpl = cfg.get("followup_breakup_body_template") or FOLLOWUP_BREAKUP_BODY

    for tmpl in (body_tmpl, breakup_tmpl):
        template_error = _check_template(subject_tmpl, tmpl)
        if template_error:
            log.critical(f"Follow-up template is broken, sent nothing: {template_error}")
            result["errors"].append(template_error)
            return result

    for row_idx, row, stage in candidates:
        email = str(row["Email"]).strip()
        if not EMAIL_RE.match(email):
            log.warning(f"Skipping row {row_idx}: '{email}' doesn't look like a valid email address")
            result["skipped"].append(email)
            continue

        is_last = stage >= last_stage
        context = {
            "name": lead_name(row),
            "company": lead_company(row),
            "phone": row.get("Phone") or "",
            "sender_name": cfg["sender_name"],
            "sender_company": cfg["sender_company"],
            "sender_phone": cfg.get("sender_phone") or "",
            "sender_pitch": cfg.get("sender_pitch") or "",
            "stage": stage + 1,
            "is_last": is_last,
        }
        subject = render(subject_tmpl, **context)
        body = render(breakup_tmpl if is_last else body_tmpl, **context)

        if dry_run:
            result["preview"].append({"email": email, "subject": subject, "body": body})
            continue

        try:
            mailer.send(email, subject, body)
            store.set_value(row_idx, "FollowupStage", stage + 1)
            store.mark_sent(row_idx, "FollowupSentAt")
            record_sent(1)
            record_send_history("followup", email, row.get("Name"), row.get("Company"), subject)
            log.info(f"Sent follow-up #{stage + 1} to {email} (row {row_idx})")
            result["sent"] += 1
            time.sleep(SEND_DELAY_SECONDS)
        except ExcelFileLocked as e:
            log.critical(f"Follow-up to {email} was sent but could not be marked: {e}")
            result["errors"].append(str(e))
        except Exception as e:
            log.error(f"Failed to send follow-up to {email} (row {row_idx}): {e}")
            result["errors"].append(str(e))

    return result
