"""Tests for outreach.calendar_api - no network, fake Calendar service injected."""

from datetime import datetime, timedelta

import pytest

from outreach import calendar_api


def _local_offset():
    """The machine's current UTC offset as '+HH:MM', so fake busy intervals line
    up with the naive-local wall clock the module works in on any test host."""
    z = datetime.now().astimezone().strftime("%z")  # e.g. '+0300'
    return f"{z[:3]}:{z[3:]}"


OFF = _local_offset()


class FakeFreebusy:
    def __init__(self, resp):
        self._resp = resp
        self.body = None

    def query(self, body=None):
        self.body = body
        return self

    def execute(self):
        return self._resp


class FakeEvents:
    def __init__(self, ret=None):
        self.ret = ret or {"id": "evt_123", "htmlLink": "https://cal/evt_123"}
        self.captured = None

    def insert(self, calendarId=None, body=None, sendUpdates=None):
        self.captured = {"calendarId": calendarId, "body": body, "sendUpdates": sendUpdates}
        return self

    def execute(self):
        return self.ret


class FakeService:
    def __init__(self, busy=None, freebusy_resp=None, event_ret=None):
        if freebusy_resp is None:
            freebusy_resp = {"calendars": {"primary": {"busy": busy or []}}}
        self._fb = FakeFreebusy(freebusy_resp)
        self._ev = FakeEvents(event_ret)

    def freebusy(self):
        return self._fb

    def events(self):
        return self._ev


def _busy(day, start_h, end_h):
    return {
        "start": f"{day}T{start_h:02d}:00:00{OFF}",
        "end": f"{day}T{end_h:02d}:00:00{OFF}",
    }


# --- busy_intervals -----------------------------------------------------------

def test_busy_intervals_parses_response():
    svc = FakeService(busy=[_busy("2026-08-31", 9, 10), _busy("2026-08-31", 14, 15)])
    got = calendar_api.busy_intervals("me@x.com", "primary", "a", "b", service=svc)
    assert got == [
        (f"2026-08-31T09:00:00{OFF}", f"2026-08-31T10:00:00{OFF}"),
        (f"2026-08-31T14:00:00{OFF}", f"2026-08-31T15:00:00{OFF}"),
    ]


def test_busy_intervals_raises_on_errors():
    svc = FakeService(freebusy_resp={"calendars": {"primary": {"errors": [{"reason": "notFound"}]}}})
    with pytest.raises(calendar_api.CalendarError):
        calendar_api.busy_intervals("me@x.com", "primary", "a", "b", service=svc)


# --- slot_is_free -----------------------------------------------------------

def test_slot_is_free_true_when_no_overlap():
    svc = FakeService(busy=[_busy("2026-08-31", 9, 10)])
    start = datetime(2026, 8, 31, 11, 0)
    assert calendar_api.slot_is_free("me@x.com", "primary", start, 30, service=svc) is True


def test_slot_is_free_false_when_overlapping():
    svc = FakeService(busy=[_busy("2026-08-31", 9, 10)])
    start = datetime(2026, 8, 31, 9, 30)
    assert calendar_api.slot_is_free("me@x.com", "primary", start, 30, service=svc) is False


def test_slot_is_free_touching_edge_is_free():
    # busy ends at 10:00, meeting starts at 10:00 -> not an overlap
    svc = FakeService(busy=[_busy("2026-08-31", 9, 10)])
    start = datetime(2026, 8, 31, 10, 0)
    assert calendar_api.slot_is_free("me@x.com", "primary", start, 30, service=svc) is True


# --- find_open_slots -----------------------------------------------------------

COMMON = dict(
    duration_minutes=30,
    business_hours={"start": 9, "end": 17},
    business_days=[0, 1, 2, 3, 4],
    window_days=7,
    min_notice_hours=1,
)


def test_find_open_slots_all_free_returns_count_from_day_start():
    svc = FakeService(busy=[])
    now = datetime(2026, 8, 31, 8, 0)  # Monday 08:00
    slots = calendar_api.find_open_slots("me@x.com", "primary", now=now, count=3, service=svc, **COMMON)
    assert slots == [
        datetime(2026, 8, 31, 9, 0),
        datetime(2026, 8, 31, 9, 30),
        datetime(2026, 8, 31, 10, 0),
    ]


def test_find_open_slots_skips_busy_block_at_start():
    svc = FakeService(busy=[_busy("2026-08-31", 9, 10)])
    now = datetime(2026, 8, 31, 8, 0)
    slots = calendar_api.find_open_slots("me@x.com", "primary", now=now, count=2, service=svc, **COMMON)
    assert slots == [datetime(2026, 8, 31, 10, 0), datetime(2026, 8, 31, 10, 30)]


def test_find_open_slots_respects_min_notice():
    svc = FakeService(busy=[])
    now = datetime(2026, 8, 31, 8, 0)  # Monday
    opts = dict(COMMON)
    opts["min_notice_hours"] = 26  # earliest = Tue 10:00
    slots = calendar_api.find_open_slots("me@x.com", "primary", now=now, count=1, service=svc, **opts)
    assert slots == [datetime(2026, 9, 1, 10, 0)]


def test_find_open_slots_skips_weekend():
    svc = FakeService(busy=[])
    now = datetime(2026, 9, 5, 8, 0)  # Saturday
    slots = calendar_api.find_open_slots("me@x.com", "primary", now=now, count=1, service=svc, **COMMON)
    assert slots == [datetime(2026, 9, 7, 9, 0)]  # Monday


def test_find_open_slots_last_slot_fits_before_close():
    # Fill the whole day except the final 16:30 slot; it must end exactly at 17:00, never later.
    svc = FakeService(busy=[_busy("2026-08-31", 9, 16), {"start": f"2026-08-31T16:30:00{OFF}",
                                                        "end": f"2026-08-31T17:00:00{OFF}"}])
    now = datetime(2026, 8, 31, 8, 0)
    slots = calendar_api.find_open_slots("me@x.com", "primary", now=now, count=5, service=svc, **COMMON)
    assert datetime(2026, 8, 31, 16, 0) in slots
    for s in slots:
        assert (s + timedelta(minutes=30)).time() <= datetime(2026, 8, 31, 17, 0).time()
        assert s.hour >= 9


def test_find_open_slots_returns_at_most_count():
    svc = FakeService(busy=[])
    now = datetime(2026, 8, 31, 8, 0)
    slots = calendar_api.find_open_slots("me@x.com", "primary", now=now, count=3, service=svc, **COMMON)
    assert len(slots) == 3


# --- create_event -----------------------------------------------------------

def test_create_event_builds_body_and_returns_id():
    svc = FakeService(event_ret={"id": "evt_abc", "htmlLink": "https://cal/evt_abc"})
    eid = calendar_api.create_event(
        "me@x.com", "primary",
        summary="Intro call: Acme x FreightCo",
        description="30-min intro.",
        start=datetime(2026, 9, 1, 15, 0),
        duration_minutes=30,
        attendee_email="lead@acme.com",
        timezone="Europe/Chisinau",
        service=svc,
    )
    assert eid == "evt_abc"
    cap = svc.events().captured
    assert cap["calendarId"] == "primary"
    assert cap["sendUpdates"] == "all"
    body = cap["body"]
    assert body["summary"] == "Intro call: Acme x FreightCo"
    assert body["start"] == {"dateTime": "2026-09-01T15:00:00", "timeZone": "Europe/Chisinau"}
    assert body["end"] == {"dateTime": "2026-09-01T15:30:00", "timeZone": "Europe/Chisinau"}
    assert body["attendees"] == [{"email": "lead@acme.com"}]


def test_create_event_send_updates_none():
    svc = FakeService()
    calendar_api.create_event(
        "me@x.com", "primary", summary="s", description="d",
        start=datetime(2026, 9, 1, 15, 0), duration_minutes=45,
        attendee_email="a@b.com", timezone="UTC", send_updates=False, service=svc,
    )
    assert svc.events().captured["sendUpdates"] == "none"
    assert svc.events().captured["body"]["end"]["dateTime"] == "2026-09-01T15:45:00"


# --- local_tz_name -----------------------------------------------------------

def test_local_tz_name_is_loadable_or_etc_gmt():
    name = calendar_api.local_tz_name()
    assert isinstance(name, str) and name
    assert name == "UTC" or name.startswith("Etc/GMT") or "/" in name
