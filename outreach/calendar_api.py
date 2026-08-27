"""Google Calendar access for the reply-handling feature: free/busy lookups,
finding open meeting slots, and creating events with an invite email.

Uses the same OAuth credentials as Gmail (see outreach/gmail_oauth.py). The
`calendar.events` and `calendar.freebusy` scopes must be granted - the client
re-runs "Connect Gmail" once after the feature is enabled.

All datetimes crossing this module's public API are naive wall-clock times, read
in the configured IANA time zone (`resolve_timezone(cfg)`), which callers pass in
as `tz`. Conversions to/from the RFC3339 strings the Google API expects happen
internally.
"""

import random
import time
from datetime import datetime, timedelta

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from outreach.gmail_oauth import get_credentials
from outreach.logging_setup import get_logger

try:  # Python 3.9+; always present on the 3.12 target
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

log = get_logger("calendar_api")


class CalendarError(RuntimeError):
    """A Calendar API call failed (bad calendar id, revoked scope, quota, ...)."""


# --- service -----------------------------------------------------------------

def _service(gmail_address, service=None):
    if service is not None:
        return service
    return build("calendar", "v3", credentials=get_credentials(gmail_address))


# --- timezone helpers ------------------------------------------------------------

def local_tz_name():
    """Best-effort IANA time zone name for this machine, or "" if none can be
    determined. Detection only - no fixed-offset 'Etc/GMT' fallback (that has no
    DST and silently books meetings an hour off across a transition)."""
    from outreach.config import detect_timezone

    return detect_timezone()


def resolve_timezone(cfg):
    """The IANA time zone name to use for all calendar work.

    `cfg["timezone"]` wins; if empty, fall back to machine detection. Raises
    CalendarError if nothing valid is resolvable - never guesses a fixed offset.
    """
    name = ""
    if isinstance(cfg, dict):
        name = str(cfg.get("timezone") or "").strip()
    if not name:
        name = local_tz_name()
    if not name:
        raise CalendarError(
            "No time zone configured. Set 'Time zone' on the Settings page "
            "(an IANA name like Europe/Chisinau)."
        )
    if ZoneInfo is None:  # pragma: no cover - zoneinfo is stdlib on the target
        raise CalendarError("zoneinfo is unavailable in this Python build.")
    try:
        ZoneInfo(name)
    except Exception as e:  # noqa: BLE001
        raise CalendarError(
            f"Configured time zone {name!r} is not a valid IANA name."
        ) from e
    return name


def _zone(tz):
    """ZoneInfo for an IANA name, or None to mean 'the machine's local zone'."""
    if not tz:
        return None
    if ZoneInfo is None:  # pragma: no cover
        raise CalendarError("zoneinfo is unavailable in this Python build.")
    return ZoneInfo(tz)


def _to_rfc3339(dt, tz=None):
    """Naive (wall-clock, in `tz` or the machine zone) or aware datetime ->
    RFC3339 string with an explicit UTC offset."""
    if dt.tzinfo is not None:
        return dt.isoformat()
    zone = _zone(tz)
    aware = dt.replace(tzinfo=zone) if zone is not None else dt.astimezone()
    return aware.isoformat()


def _parse_rfc3339(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _to_naive_local(aware_dt, tz=None):
    """Aware datetime -> naive wall-clock in `tz` (or the machine zone)."""
    return aware_dt.astimezone(_zone(tz)).replace(tzinfo=None)


def _overlaps(start, end, intervals):
    """True if [start, end) overlaps any [is, ie) in intervals (all naive-local)."""
    return any(start < ie and end > is_ for is_, ie in intervals)


# --- transient-error backoff --------------------------------------------------
# Mirrors mailer.py: retry 429/500/503 with exponential backoff + jitter so a
# blip on free/busy or events.insert doesn't surface as "Failed" to the client.

_RETRY_STATUSES = (429, 500, 503)
_MAX_BACKOFF = 30


def _retry_google(call, *, attempts=4):
    last = None
    for attempt in range(attempts):
        try:
            return call()
        except HttpError as e:
            status = e.resp.status if e.resp is not None else None
            if status not in _RETRY_STATUSES:
                raise
            last = e
        if attempt < attempts - 1:
            delay = min(2 ** attempt + random.uniform(0, 1), _MAX_BACKOFF)
            log.warning("Calendar API %s, retrying in %.1fs (attempt %d/%d)",
                        getattr(getattr(last, "resp", None), "status", "?"),
                        delay, attempt + 1, attempts)
            time.sleep(delay)
    raise last


# --- public API ----------------------------------------------------------------

def busy_intervals(gmail_address, calendar_id, start_iso, end_iso, *, service=None):
    """freebusy.query over [start_iso, end_iso] -> list of (busy_start, busy_end)
    RFC3339 strings (start inclusive, end exclusive)."""
    svc = _service(gmail_address, service)
    body = {
        "timeMin": start_iso,
        "timeMax": end_iso,
        "items": [{"id": calendar_id}],
    }
    resp = _retry_google(lambda: svc.freebusy().query(body=body).execute())
    cal = resp.get("calendars", {}).get(calendar_id, {})
    errors = cal.get("errors")
    if errors:
        raise CalendarError(f"free/busy lookup failed for calendar '{calendar_id}': {errors}")
    return [(b["start"], b["end"]) for b in cal.get("busy", [])]


def _busy_local(gmail_address, calendar_id, start, end, service=None, tz=None):
    raw = busy_intervals(
        gmail_address, calendar_id,
        _to_rfc3339(start, tz), _to_rfc3339(end, tz), service=service,
    )
    return [(_to_naive_local(_parse_rfc3339(s), tz), _to_naive_local(_parse_rfc3339(e), tz))
            for s, e in raw]


def slot_is_free(gmail_address, calendar_id, start, duration_minutes, *, service=None, tz=None):
    """True if nothing on the calendar overlaps [start, start+duration).

    `start` is wall-clock in `tz` (the configured IANA zone); pass tz=None only
    in tests to mean the machine's local zone."""
    end = start + timedelta(minutes=duration_minutes)
    return not _overlaps(start, end, _busy_local(gmail_address, calendar_id, start, end, service, tz))


def find_open_slots(gmail_address, calendar_id, *, duration_minutes, business_hours,
                    business_days, window_days, min_notice_hours, count=3,
                    now=None, service=None, tz=None):
    """Up to `count` slot-start datetimes (naive-local) that are:
      - on a weekday in `business_days` (Python weekday(): Mon=0),
      - fully inside [business_hours['start'], business_hours['end']) wall-clock,
      - at least `min_notice_hours` from `now`,
      - within `window_days` of `now`,
      - not overlapping any busy interval on the calendar.
    Slots are aligned to the hour and step by `duration_minutes`.
    """
    now = now or datetime.now()
    earliest = now + timedelta(hours=min_notice_hours)
    window_end = now + timedelta(days=window_days)

    busy = _busy_local(gmail_address, calendar_id, now, window_end, service, tz)

    step = timedelta(minutes=duration_minutes)
    start_h = business_hours["start"]
    end_h = business_hours["end"]

    slots = []
    day = now.date()
    while day <= window_end.date() and len(slots) < count:
        if day.weekday() in business_days:
            t = datetime(day.year, day.month, day.day, start_h, 0)
            last_start = datetime(day.year, day.month, day.day, end_h, 0) - step
            while t <= last_start and len(slots) < count:
                if t >= earliest and not _overlaps(t, t + step, busy):
                    slots.append(t)
                t += step
        day += timedelta(days=1)
    return slots


def create_event(gmail_address, calendar_id, *, summary, description, start, duration_minutes,
                 attendee_email, timezone, send_updates=True, service=None, ical_uid=None):
    """events.insert - creates the meeting and (with send_updates) emails the
    attendee a real Google Calendar invitation. Returns the created event id.

    Pass `ical_uid` (a stable string derived from the queue id) so a retry after
    a lost insert response collides with the first event instead of double-booking.
    """
    svc = _service(gmail_address, service)
    end = start + timedelta(minutes=duration_minutes)
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": timezone},
        "end": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": timezone},
        "attendees": [{"email": attendee_email}],
    }
    if ical_uid:
        body["iCalUID"] = ical_uid
    created = _retry_google(lambda: svc.events().insert(
        calendarId=calendar_id,
        body=body,
        sendUpdates="all" if send_updates else "none",
    ).execute())
    return created["id"]
