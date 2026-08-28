"""Tests for outreach.calendar_api - no network, fake Calendar service injected."""

from datetime import datetime, timedelta

import pytest
from googleapiclient.errors import HttpError

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


# --- timezone resolution ----------------------------------------------------

def test_local_tz_name_is_detection_only():
    name = calendar_api.local_tz_name()
    # detection-only now: a valid IANA name or "" (never a fixed Etc/GMT offset)
    assert isinstance(name, str)
    assert name == "" or "/" in name or name == "UTC"
    assert not name.startswith("Etc/GMT")


def test_resolve_timezone_uses_config_value():
    assert calendar_api.resolve_timezone({"timezone": "Europe/Chisinau"}) == "Europe/Chisinau"


def test_resolve_timezone_rejects_invalid():
    with pytest.raises(calendar_api.CalendarError):
        calendar_api.resolve_timezone({"timezone": "Mars/Olympus_Mons"})


def test_resolve_timezone_raises_when_unresolvable(monkeypatch):
    monkeypatch.setattr(calendar_api, "local_tz_name", lambda: "")
    with pytest.raises(calendar_api.CalendarError):
        calendar_api.resolve_timezone({"timezone": ""})


def test_create_event_uses_configured_zone_for_conversion():
    # busy interval given in UTC; with tz=America/New_York the slot check must
    # compare against New York wall-clock, not the test host's local zone.
    svc = FakeService(busy=[{"start": "2026-01-15T14:00:00+00:00", "end": "2026-01-15T15:00:00+00:00"}])
    # 14:00 UTC == 09:00 New York (EST). A 09:30 NY meeting overlaps; 10:00 doesn't.
    assert calendar_api.slot_is_free(
        "me@x.com", "primary", datetime(2026, 1, 15, 9, 30), 30, service=svc, tz="America/New_York"
    ) is False
    svc2 = FakeService(busy=[{"start": "2026-01-15T14:00:00+00:00", "end": "2026-01-15T15:00:00+00:00"}])
    assert calendar_api.slot_is_free(
        "me@x.com", "primary", datetime(2026, 1, 15, 10, 0), 30, service=svc2, tz="America/New_York"
    ) is True


class _Resp:
    def __init__(self, status):
        self.status = status
        self.reason = "Conflict"

    def get(self, _key, _default=None):
        return "application/json"


class _409ThenListEvents:
    """insert() raises 409 the first time; list() by iCalUID finds the event."""

    def __init__(self):
        self.insert_calls = 0
        self.list_calls = 0
        self._pending = None

    def insert(self, calendarId=None, body=None, sendUpdates=None):
        self.insert_calls += 1
        self._pending = "insert"
        return self

    def list(self, calendarId=None, iCalUID=None, showDeleted=None):
        self.list_calls += 1
        self._pending = "list"
        return self

    def execute(self):
        if self._pending == "insert":
            raise HttpError(_Resp(409), b'{"error": {"message": "duplicate"}}')
        return {"items": [{"id": "recovered_evt"}]}


class _RecoveryService:
    def __init__(self):
        self._ev = _409ThenListEvents()

    def events(self):
        return self._ev


def test_create_event_recovers_from_409_on_own_ical_uid():
    svc = _RecoveryService()
    eid = calendar_api.create_event(
        "me@x.com", "primary", summary="s", description="d",
        start=datetime(2026, 9, 1, 15, 0), duration_minutes=30,
        attendee_email="a@b.com", timezone="UTC", service=svc,
        ical_uid="freight-abc123@freightoutreach",
    )
    assert eid == "recovered_evt"
    assert svc.events().insert_calls == 1
    assert svc.events().list_calls == 1


def test_create_event_409_without_ical_uid_still_raises():
    class _Always409:
        def insert(self, **k):
            return self

        def execute(self):
            raise HttpError(_Resp(409), b"{}")

    svc = type("S", (), {"events": lambda self: _Always409()})()
    with pytest.raises(HttpError):
        calendar_api.create_event(
            "me@x.com", "primary", summary="s", description="d",
            start=datetime(2026, 9, 1, 15, 0), duration_minutes=30,
            attendee_email="a@b.com", timezone="UTC", service=svc,
        )


def test_create_event_sets_deterministic_ical_uid():
    svc = FakeService()
    calendar_api.create_event(
        "me@x.com", "primary", summary="s", description="d",
        start=datetime(2026, 9, 1, 15, 0), duration_minutes=30,
        attendee_email="a@b.com", timezone="UTC", service=svc, ical_uid="freight-abc123@freightoutreach",
    )
    assert svc.events().captured["body"]["iCalUID"] == "freight-abc123@freightoutreach"
