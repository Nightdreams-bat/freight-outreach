import random
import time
from datetime import datetime, timedelta

import jinja2

from outreach.errors import GmailNeedsReconnect
from outreach.excel_store import ExcelFileLocked
from outreach.lead_fields import lead_company, lead_name, valid_email
from outreach.locking import data_lock
from outreach.logging_setup import get_logger
from outreach.mailer import Mailer
from outreach.send_tracker import record_send_history, record_sent, remaining_today
from outreach.config import get as cfg_get
from outreach.scoring import score_lead
from outreach import templates
from outreach.templates import render

log = get_logger("core")

MEETING_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M")


def _send_delay_seconds(cfg, kind):
    """Seconds to pause after a send. Cold/follow-up use a random gap in the
    configured range (a fixed interval is a blast fingerprint); reminders use a
    short fixed delay. Tests patch `core.time.sleep`, so the value is only ever
    real in production."""
    if kind == "reminder":
        return cfg_get(cfg, "reminder_send_delay_seconds")
    lo = cfg_get(cfg, "send_delay_min_seconds")
    hi = cfg_get(cfg, "send_delay_max_seconds")
    if hi < lo:
        lo, hi = hi, lo
    return random.uniform(lo, hi)

# dummy values used only to pre-flight-check a user's custom template before a real batch runs
_DUMMY_CONTEXT = {
    "name": "Sample Lead", "company": "Sample Co", "phone": "555-0100",
    "sender_name": "Sample Sender", "sender_company": "Sample Company",
    "sender_phone": "555-0100", "sender_pitch": "Sample pitch.",
    "sender_address": "1 Sample St, Sample City, Country",
    "unsubscribe_line": "Reply STOP to this email and I won't contact you again.",
    "meeting_time": "Monday, Jan 1 at 10:00 AM",
    "stage": 1, "is_last": False,
    "slots": ["Mon 10:00 AM", "Tue 2:00 PM"],
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
    """Rows whose meeting is now inside the 24h reminder horizon and that haven't
    been reminded yet.

    The rule is "meeting is in (now, now + 24h + window] AND ReminderSentAt is
    empty AND the meeting is still in the future" - so a reminder goes out as soon
    as we're within a day of the meeting, catching up any scan window the machine
    slept through. ReminderSentAt stays the idempotency guard.
    """
    horizon = timedelta(hours=24) + timedelta(hours=window_hours)
    now = datetime.now()

    candidates = []
    for row_idx, row in store.rows():
        if row.get("ReminderSentAt"):
            continue
        # A lead who just opted out or declined this same run is already a
        # candidate row - skip those so the opt-out scan that ran moments ago
        # actually suppresses the reminder. "booked" is NOT skipped: an approved
        # booking is exactly what a 24h reminder is for.
        if str(row.get("ReplyStatus") or "").strip().lower() in {"no", "optout"}:
            continue
        raw_meeting_time = row.get("MeetingDateTime")
        meeting_time = parse_meeting_time(raw_meeting_time)
        if meeting_time is None:
            if raw_meeting_time:
                log.warning(f"Row {row_idx}: couldn't parse MeetingDateTime '{raw_meeting_time}'")
            continue
        delta = meeting_time - now
        if timedelta(0) < delta <= horizon:
            candidates.append((row_idx, row, meeting_time))
    return candidates


def cap_reminders_per_run(candidates, max_per_run, abort_multiple=3):
    """Apply the per-run reminder brake. Returns (trimmed, overflow, aborted).

    Normally: never go silent on a busy day - sort by soonest meeting, send the
    first `max_per_run`, let the caller log the overflow.

    But if the match count is way over the cap (> max_per_run * abort_multiple),
    that's almost certainly a data problem (one datetime pasted into hundreds of
    rows), not a busy day - send ZERO and let the caller log loudly.
    """
    if len(candidates) > max_per_run * abort_multiple:
        return [], len(candidates), True
    if len(candidates) <= max_per_run:
        return candidates, 0, False
    ordered = sorted(candidates, key=lambda c: c[2])  # soonest meeting first
    return ordered[:max_per_run], len(candidates) - max_per_run, False


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

        # The cadence is measured from the cold intro: touch N goes out once
        # `offsets[N]` days have passed since ColdEmailSentAt (so [3, 7, 14] means
        # days 3, 7, 14 - not 3, 10, 24).
        if now - cold_at < timedelta(days=float(offsets[stage])):
            continue

        # Floor: never send two touches less than a day apart. Guards against a
        # drip that was switched on after weeks of silence firing every stage at
        # once, and against a re-send if a mid-batch sheet lock skipped the stage bump.
        last_sent = parse_meeting_time(row.get("FollowupSentAt"))
        if last_sent is not None and now - last_sent < timedelta(days=1):
            continue

        candidates.append((row_idx, row, stage))
    return candidates


def build_mailer(cfg):
    return Mailer(
        cfg["gmail_address"],
        cfg.get("sender_name"),
        cfg.get("sender_company"),
        reply_to=cfg.get("reply_to"),
    )


def _thread_send_kwargs(row):
    """send() kwargs that thread a message onto the row's cold intro, or {}."""
    msg_id = str(row.get("ColdMessageId") or "").strip()
    thread_id = str(row.get("ColdThreadId") or "").strip()
    kwargs = {}
    if msg_id:
        kwargs["in_reply_to"] = msg_id
        kwargs["references"] = msg_id
    if thread_id:
        kwargs["thread_id"] = thread_id
    return kwargs


def _cold_subject(cfg, row):
    """Re-render the cold-intro subject for this row, so a threaded follow-up /
    reminder can reuse it as `Re: <cold subject>`."""
    tmpl = _tmpl_defaults(cfg)
    subject_tmpl = cfg.get("cold_subject_template") or tmpl["cold_subject_template"]
    ctx = {
        "name": lead_name(row),
        "company": lead_company(row),
        "phone": row.get("Phone") or "",
        "sender_name": cfg.get("sender_name") or "",
        "sender_company": cfg.get("sender_company") or "",
        "sender_phone": cfg.get("sender_phone") or "",
        "sender_pitch": cfg.get("sender_pitch") or "",
        "sender_address": cfg.get("sender_address") or "",
        "unsubscribe_line": templates.unsubscribe_line(cfg_get(cfg, "template_language")),
    }
    return render(subject_tmpl, **ctx)


def _threaded_subject(cfg, row, fallback_subject):
    """`Re: <cold subject>` when this row's cold intro is on a Gmail thread,
    otherwise the templated subject as-is."""
    if not str(row.get("ColdThreadId") or "").strip():
        return fallback_subject
    try:
        base = _cold_subject(cfg, row)
    except Exception:  # noqa: BLE001 - a broken cold template shouldn't block the nudge
        return fallback_subject
    base = base.strip()
    if base.lower().startswith("re:"):
        return base
    return f"Re: {base}" if base else fallback_subject


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
    except Exception as e:  # noqa: BLE001 - a bad template (e.g. {{1/0}}, sandbox
        # violation) must be caught pre-flight, not abort the batch mid-run.
        return f"Template error: {e}"


def _tmpl_defaults(cfg):
    """Language-correct template fallback for a config that predates a template key."""
    return templates.defaults(cfg_get(cfg, "template_language"))


def _abort_note(n):
    return f"aborted: {n} consecutive send failures"


# The per-row state write (mark_sent + set_value + tracker files) is the only
# part of a batch that must be serialised against the scheduled tasks. The
# mailer.send() network call and the inter-send sleep are deliberately OUTSIDE
# the lock - with jittered pacing a batch can run for many minutes, and holding
# a global lock that whole time would block the reply/opt-out tasks.


def send_cold_batch(cfg, store, mailer, candidates, dry_run=False):
    """Sends the cold-intro email to each candidate row. Returns a summary dict."""
    result = {"sent": 0, "skipped": [], "errors": [], "preview": []}

    tmpl = _tmpl_defaults(cfg)
    subject_tmpl = cfg.get("cold_subject_template") or tmpl["cold_subject_template"]
    body_tmpl = cfg.get("cold_body_template") or tmpl["cold_body_template"]

    abort_threshold = cfg_get(cfg, "send_failure_abort_threshold")
    consecutive_failures = 0

    template_error = _check_template(subject_tmpl, body_tmpl)
    if template_error:
        log.critical(f"Cold intro template is broken, sent nothing: {template_error}")
        result["errors"].append(template_error)
        return result

    for row_idx, row in candidates:
        email = str(row["Email"]).strip()
        if not valid_email(email):
            log.warning(f"Skipping row {row_idx}: '{email}' doesn't look like a valid email address")
            result["skipped"].append(email)
            continue

        context = {
            "name": lead_name(row),
            "company": lead_company(row),
            "phone": row.get("Phone") or "",
            "sender_name": cfg["sender_name"],
            "sender_company": cfg["sender_company"],
            "sender_address": cfg.get("sender_address") or "",
            "unsubscribe_line": templates.unsubscribe_line(cfg_get(cfg, "template_language")),
            "sender_phone": cfg.get("sender_phone") or "",
            "sender_pitch": cfg.get("sender_pitch") or "",
        }
        subject = render(subject_tmpl, **context)
        body = render(body_tmpl, **context)

        if dry_run:
            result["preview"].append({"email": email, "subject": subject, "body": body})
            continue

        try:
            sent_meta = mailer.send(email, subject, body)
            with data_lock():
                store.mark_sent(row_idx, "ColdEmailSentAt")
                if isinstance(sent_meta, dict):
                    if sent_meta.get("message_id"):
                        store.set_value(row_idx, "ColdMessageId", sent_meta["message_id"])
                    if sent_meta.get("thread_id"):
                        store.set_value(row_idx, "ColdThreadId", sent_meta["thread_id"])
                record_sent(1)
                record_send_history("cold", email, row.get("Name"), row.get("Company"), subject)
            log.info(f"Sent cold intro to {email} (row {row_idx})")
            result["sent"] += 1
            consecutive_failures = 0
            time.sleep(_send_delay_seconds(cfg, "cold"))
        except GmailNeedsReconnect as e:
            log.critical(f"Gmail sign-in is dead, aborting cold batch: {e}")
            result["errors"].append(str(e))
            break
        except ExcelFileLocked as e:
            # The mail already went out - this is not a send failure.
            log.critical(f"Email to {email} was sent but could not be marked as sent: {e}")
            result["errors"].append(str(e))
        except Exception as e:
            log.error(f"Failed to send to {email} (row {row_idx}): {e}")
            result["errors"].append(str(e))
            consecutive_failures += 1
            if consecutive_failures >= abort_threshold:
                log.critical(f"Aborting cold batch after {consecutive_failures} consecutive "
                             f"send failures; last error: {e}")
                result["errors"].append(_abort_note(consecutive_failures))
                break

    return result


def send_reminder_batch(cfg, store, mailer, candidates, dry_run=False):
    """Sends the reminder email to each (row_idx, row, meeting_time) candidate. Returns a summary dict."""
    result = {"sent": 0, "skipped": [], "errors": [], "preview": []}

    tmpl = _tmpl_defaults(cfg)
    subject_tmpl = cfg.get("reminder_subject_template") or tmpl["reminder_subject_template"]
    body_tmpl = cfg.get("reminder_body_template") or tmpl["reminder_body_template"]

    abort_threshold = cfg_get(cfg, "send_failure_abort_threshold")
    consecutive_failures = 0

    template_error = _check_template(subject_tmpl, body_tmpl)
    if template_error:
        log.critical(f"Reminder template is broken, sent nothing: {template_error}")
        result["errors"].append(template_error)
        return result

    for row_idx, row, meeting_time in candidates:
        email = str(row["Email"]).strip()
        if not valid_email(email):
            log.warning(f"Skipping row {row_idx}: '{email}' doesn't look like a valid email address")
            result["skipped"].append(email)
            continue

        context = {
            "name": lead_name(row),
            "company": lead_company(row),
            "phone": row.get("Phone") or "",
            "meeting_time": meeting_time.strftime(templates.MEETING_TIME_DISPLAY_FMT),
            "sender_name": cfg["sender_name"],
            "sender_company": cfg["sender_company"],
            "sender_address": cfg.get("sender_address") or "",
            "unsubscribe_line": templates.unsubscribe_line(cfg_get(cfg, "template_language")),
            "sender_phone": cfg.get("sender_phone") or "",
        }
        subject = _threaded_subject(cfg, row, render(subject_tmpl, **context))
        body = render(body_tmpl, **context)

        if dry_run:
            result["preview"].append({"email": email, "subject": subject, "body": body})
            continue

        try:
            mailer.send(email, subject, body, **_thread_send_kwargs(row))
            with data_lock():
                store.mark_sent(row_idx, "ReminderSentAt")
                record_sent(1)
                record_send_history("reminder", email, row.get("Name"), row.get("Company"), subject)
            log.info(f"Sent reminder to {email} (row {row_idx})")
            result["sent"] += 1
            consecutive_failures = 0
            time.sleep(_send_delay_seconds(cfg, "reminder"))
        except GmailNeedsReconnect as e:
            log.critical(f"Gmail sign-in is dead, aborting reminder batch: {e}")
            result["errors"].append(str(e))
            break
        except ExcelFileLocked as e:
            log.critical(f"Reminder to {email} was sent but could not be marked as sent: {e}")
            result["errors"].append(str(e))
        except Exception as e:
            log.error(f"Failed to send reminder to {email} (row {row_idx}): {e}")
            result["errors"].append(str(e))
            consecutive_failures += 1
            if consecutive_failures >= abort_threshold:
                log.critical(f"Aborting reminder batch after {consecutive_failures} consecutive "
                             f"send failures; last error: {e}")
                result["errors"].append(_abort_note(consecutive_failures))
                break

    return result


def send_followup_batch(cfg, store, mailer, candidates, dry_run=False):
    """Sends the next follow-up nudge to each (row_idx, row, stage) candidate.

    Bumps FollowupStage and stamps FollowupSentAt on success. The final touch
    (stage == len(offsets) - 1) uses the breakup body. Returns a summary dict.
    """
    result = {"sent": 0, "skipped": [], "errors": [], "preview": []}

    offsets = list(cfg_get(cfg, "followup_offsets_days") or [])
    last_stage = len(offsets) - 1

    tmpl = _tmpl_defaults(cfg)
    subject_tmpl = cfg.get("followup_subject_template") or tmpl["followup_subject_template"]
    body_tmpl = cfg.get("followup_body_template") or tmpl["followup_body_template"]
    breakup_tmpl = cfg.get("followup_breakup_body_template") or tmpl["followup_breakup_body_template"]

    abort_threshold = cfg_get(cfg, "send_failure_abort_threshold")
    consecutive_failures = 0

    for tmpl in (body_tmpl, breakup_tmpl):
        template_error = _check_template(subject_tmpl, tmpl)
        if template_error:
            log.critical(f"Follow-up template is broken, sent nothing: {template_error}")
            result["errors"].append(template_error)
            return result

    for row_idx, row, stage in candidates:
        email = str(row["Email"]).strip()
        if not valid_email(email):
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
            "sender_address": cfg.get("sender_address") or "",
            "unsubscribe_line": templates.unsubscribe_line(cfg_get(cfg, "template_language")),
            "sender_phone": cfg.get("sender_phone") or "",
            "sender_pitch": cfg.get("sender_pitch") or "",
            "stage": stage + 1,
            "is_last": is_last,
        }
        subject = _threaded_subject(cfg, row, render(subject_tmpl, **context))
        body = render(breakup_tmpl if is_last else body_tmpl, **context)

        if dry_run:
            result["preview"].append({"email": email, "subject": subject, "body": body})
            continue

        try:
            mailer.send(email, subject, body, **_thread_send_kwargs(row))
            with data_lock():
                # Stamp the timestamp first: if the sheet is locked between these two
                # saves, next run re-sends this same nudge (one duplicate, caught by
                # the 1-day floor in followup_candidates) rather than skipping ahead.
                store.mark_sent(row_idx, "FollowupSentAt")
                store.set_value(row_idx, "FollowupStage", stage + 1)
                record_sent(1)
                record_send_history("followup", email, row.get("Name"), row.get("Company"), subject)
            log.info(f"Sent follow-up #{stage + 1} to {email} (row {row_idx})")
            result["sent"] += 1
            consecutive_failures = 0
            time.sleep(_send_delay_seconds(cfg, "followup"))
        except GmailNeedsReconnect as e:
            log.critical(f"Gmail sign-in is dead, aborting follow-up batch: {e}")
            result["errors"].append(str(e))
            break
        except ExcelFileLocked as e:
            log.critical(f"Follow-up to {email} was sent but could not be marked: {e}")
            result["errors"].append(str(e))
        except Exception as e:
            log.error(f"Failed to send follow-up to {email} (row {row_idx}): {e}")
            result["errors"].append(str(e))
            consecutive_failures += 1
            if consecutive_failures >= abort_threshold:
                log.critical(f"Aborting follow-up batch after {consecutive_failures} consecutive "
                             f"send failures; last error: {e}")
                result["errors"].append(_abort_note(consecutive_failures))
                break

    return result
