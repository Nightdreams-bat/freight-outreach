"""Google Calendar access for the reply-handling feature: free/busy lookups,
finding open meeting slots, and creating events with an invite email.

Uses the same OAuth credentials as Gmail (see outreach/gmail_oauth.py). The
`calendar.events` and `calendar.freebusy` scopes must be granted - the client
re-runs "Connect Gmail" once after the feature is enabled.

All datetimes crossing this module's public API are naive and in the machine's
local wall-clock time. Conversions to/from the RFC3339 strings the Google API
expects happen internally, attaching the local UTC offset.
"""

import os
from datetime import datetime, timedelta

from googleapiclient.discovery import build

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
    """Best-effort IANA timezone name for the machine's local time.

    Tries $TZ, then falls back to a fixed-offset 'Etc/GMT<n>' zone (valid IANA,
    accepted by Google Calendar). Half-hour offsets fall back to plain UTC labels
    with a warning - not a case that matters for this tool's users.
    """
    tz = os.environ.get("TZ")
    if tz and ZoneInfo is not None:
        try:
            ZoneInfo(tz)
            return tz
        except Exception:
            pass

    key = getattr(datetime.now().astimezone().tzinfo, "key", None)
    if key:
        return key

    offset = datetime.now().astimezone().utcoffset() or timedelta(0)
    total_minutes = int(offset.total_seconds() // 60)
    if total_minutes == 0:
        return "UTC"
    hours, minutes = divmod(abs(total_minutes), 60)
    if minutes:
        log.warning("Local timezone has a %d-min offset; using UTC for the Calendar API.", total_minutes)
        return "UTC"
    # 'Etc/GMT' zones use the POSIX sign convention (inverted): Etc/GMT-3 == UTC+3.
    sign = "-" if total_minutes > 0 else "+"
    return f"Etc/GMT{sign}{hours}"


def _to_rfc3339(dt):
    """Naive-local (or aware) datetime -> RFC3339 string with a UTC offset."""
    aware = dt.astimezone() if dt.tzinfo is None else dt
    return aware.isoformat()


def _parse_rfc3339(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _to_naive_local(aware_dt):
    return aware_dt.astimezone().replace(tzinfo=None)


def _overlaps(start, end, intervals):
    """True if [start, end) overlaps any [is, ie) in intervals (all naive-local)."""
    return any(start < ie and end > is_ for is_, ie in intervals)


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
    resp = svc.freebusy().query(body=body).execute()
    cal = resp.get("calendars", {}).get(calendar_id, {})
    errors = cal.get("errors")
    if errors:
        raise CalendarError(f"free/busy lookup failed for calendar '{calendar_id}': {errors}")
    return [(b["start"], b["end"]) for b in cal.get("busy", [])]


def _busy_local(gmail_address, calendar_id, start, end, service=None):
    raw = busy_intervals(
        gmail_address, calendar_id, _to_rfc3339(start), _to_rfc3339(end), service=service
    )
    return [(_to_naive_local(_parse_rfc3339(s)), _to_naive_local(_parse_rfc3339(e))) for s, e in raw]


def slot_is_free(gmail_address, calendar_id, start, duration_minutes, *, service=None):
    """True if nothing on the calendar overlaps [start, start+duration)."""
    end = start + timedelta(minutes=duration_minutes)
    return not _overlaps(start, end, _busy_local(gmail_address, calendar_id, start, end, service))


def find_open_slots(gmail_address, calendar_id, *, duration_minutes, business_hours,
                    business_days, window_days, min_notice_hours, count=3,
                    now=None, service=None):
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

    busy = _busy_local(gmail_address, calendar_id, now, window_end, service)

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
                 attendee_email, timezone, send_updates=True, service=None):
    """events.insert - creates the meeting and (with send_updates) emails the
    attendee a real Google Calendar invitation. Returns the created event id."""
    svc = _service(gmail_address, service)
    end = start + timedelta(minutes=duration_minutes)
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": timezone},
        "end": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": timezone},
        "attendees": [{"email": attendee_email}],
    }
    created = svc.events().insert(
        calendarId=calendar_id,
        body=body,
        sendUpdates="all" if send_updates else "none",
    ).execute()
    return created["id"]
