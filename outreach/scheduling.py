"""Turn one classified reply into a drafted action for the approval queue.

This is decision logic plus email rendering. The only outside calls are
free/busy / open-slot lookups on the client's calendar, and only for a "yes".
Nothing here sends an email or books anything - that happens later in
`reply_queue.approve`, after the client clicks Approve on the dashboard.

`plan_action` returns one of:

    {"kind": "book",        "start": datetime, "email_subject", "email_body",
     "event_summary", "event_description"}
    {"kind": "propose",     "slots": [datetime, ...], "email_subject", "email_body"}
    {"kind": "decline_ack", "email_subject", "email_body"}
    {"kind": "manual",      "reason": str}      # maybe / question / a lookup failed

or None if there is genuinely nothing to do.
"""

from datetime import datetime

from outreach import calendar_api
from outreach.config import get as cfg_get
from outreach.lead_fields import lead_company, lead_name
from outreach.logging_setup import get_logger
from outreach.templates import (
    DECLINE_ACK_BODY,
    DECLINE_ACK_SUBJECT,
    MEETING_CONFIRM_BODY,
    MEETING_CONFIRM_SUBJECT,
    PROPOSE_TIMES_BODY,
    PROPOSE_TIMES_SUBJECT,
    render,
)

log = get_logger("scheduling")

# Same human format the reminder emails use (see core.send_reminder_batch).
MEETING_TIME_FMT = "%A, %b %d at %I:%M %p"
SLOTS_TO_OFFER = 3


def _parse_iso(value):
    """LLM-supplied ISO 8601 string -> naive-local datetime, or None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        log.warning("Could not parse proposed time %r", value)
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _fmt(dt):
    return dt.strftime(MEETING_TIME_FMT)


def _tmpl(cfg, key, fallback):
    return cfg.get(key) or fallback


def _base_ctx(lead, cfg):
    return {
        "name": lead_name(lead),
        "company": lead_company(lead),
        "sender_name": cfg.get("sender_name") or "",
        "sender_company": cfg.get("sender_company") or "",
        "sender_phone": cfg.get("sender_phone") or "",
    }


def _decline_ack(lead, cfg):
    ctx = _base_ctx(lead, cfg)
    return {
        "kind": "decline_ack",
        "email_subject": render(_tmpl(cfg, "decline_ack_subject_template", DECLINE_ACK_SUBJECT), **ctx),
        "email_body": render(_tmpl(cfg, "decline_ack_body_template", DECLINE_ACK_BODY), **ctx),
    }


def _propose(lead, cfg, slots):
    ctx = _base_ctx(lead, cfg)
    ctx["slots"] = [_fmt(s) for s in slots]
    return {
        "kind": "propose",
        "slots": list(slots),
        "email_subject": render(_tmpl(cfg, "propose_times_subject_template", PROPOSE_TIMES_SUBJECT), **ctx),
        "email_body": render(_tmpl(cfg, "propose_times_body_template", PROPOSE_TIMES_BODY), **ctx),
    }


def _book(lead, cfg, start):
    ctx = _base_ctx(lead, cfg)
    ctx["meeting_time"] = _fmt(start)
    company = lead_company(lead)
    who = lead_name(lead) if lead_name(lead) != "there" else (lead.get("Email") or "the lead")
    return {
        "kind": "book",
        "start": start,
        "email_subject": render(_tmpl(cfg, "meeting_confirm_subject_template", MEETING_CONFIRM_SUBJECT), **ctx),
        "email_body": render(_tmpl(cfg, "meeting_confirm_body_template", MEETING_CONFIRM_BODY), **ctx),
        "event_summary": f"Intro call: {cfg.get('sender_company') or 'Freight'} x {company}",
        "event_description": (
            f"Intro call with {who} from {company}, booked from their email reply."
        ),
    }


def plan_action(classification, lead, cfg, gmail_address):
    if not classification:
        return None

    intent = (classification.get("intent") or "").strip().lower()

    if intent == "no":
        return _decline_ack(lead, cfg)

    if intent in ("maybe", "question"):
        return {
            "kind": "manual",
            "reason": classification.get("summary") or f"reply classified as '{intent}'",
        }

    if intent != "yes":
        log.warning("plan_action: unrecognised intent %r -> manual", intent)
        return {"kind": "manual", "reason": f"unrecognised intent '{intent}'"}

    # --- intent == "yes" -----------------------------------------------------
    duration = int(cfg_get(cfg, "meeting_duration_minutes"))
    calendar_id = cfg_get(cfg, "calendar_id")
    proposed = _parse_iso(classification.get("proposed_start"))

    try:
        if proposed is not None and calendar_api.slot_is_free(
            gmail_address, calendar_id, proposed, duration
        ):
            return _book(lead, cfg, proposed)

        if proposed is not None:
            log.info("Lead's proposed time %s is taken - offering alternatives", proposed)

        slots = calendar_api.find_open_slots(
            gmail_address,
            calendar_id,
            duration_minutes=duration,
            business_hours=cfg_get(cfg, "business_hours"),
            business_days=cfg_get(cfg, "business_days"),
            window_days=cfg_get(cfg, "scheduling_window_days"),
            min_notice_hours=cfg_get(cfg, "min_notice_hours"),
            count=SLOTS_TO_OFFER,
        )
    except calendar_api.CalendarError as e:
        log.error("Calendar lookup failed, routing to manual: %s", e)
        return {"kind": "manual", "reason": f"calendar lookup failed: {e}"}

    if not slots:
        return {
            "kind": "manual",
            "reason": "no open slots in the scheduling window - widen business hours or the window",
        }

    return _propose(lead, cfg, slots)
