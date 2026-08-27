import re
import time
from datetime import datetime, timedelta

import jinja2

from outreach.excel_store import ExcelFileLocked
from outreach.logging_setup import get_logger
from outreach.mailer import Mailer
from outreach.send_tracker import record_send_history, record_sent, remaining_today
from outreach.templates import (
    COLD_INTRO_BODY,
    COLD_INTRO_SUBJECT,
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


def build_mailer(cfg):
    return Mailer(cfg["gmail_address"], cfg.get("sender_name"), cfg.get("sender_company"))


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
            "name": row.get("Name") or "there",
            "company": row.get("Company") or "your company",
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
            "name": row.get("Name") or "there",
            "company": row.get("Company") or "your company",
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
