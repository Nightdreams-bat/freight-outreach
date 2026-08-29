"""Wave 3: scheduling.plan_action routing - every branch, no network."""

from datetime import datetime, timedelta

import pytest

from kairo import scheduling

CFG = {
    "sender_name": "Al",
    "sender_company": "FreightCo",
    "sender_phone": "555-0100",
    "meeting_duration_minutes": 30,
    "calendar_id": "primary",
    "business_hours": {"start": 9, "end": 17},
    "business_days": [0, 1, 2, 3, 4],
    "scheduling_window_days": 10,
    "min_notice_hours": 24,
}
LEAD = {"Name": "Jane Lee", "Company": "Acme Freight", "Email": "jane@acme.test"}

DEFAULT_SLOTS = [
    datetime(2026, 9, 1, 9, 0),
    datetime(2026, 9, 1, 9, 30),
    datetime(2026, 9, 1, 10, 0),
]

_RealCalendarError = scheduling.calendar_api.CalendarError


class FakeCal:
    CalendarError = _RealCalendarError

    def __init__(self, free=True, slots=None, raise_error=False):
        self._free = free
        self._slots = DEFAULT_SLOTS if slots is None else slots
        self._raise = raise_error
        self.calls = []

    def slot_is_free(self, *args, **kwargs):
        self.calls.append("slot_is_free")
        if self._raise:
            raise self.CalendarError("freebusy failed")
        return self._free

    def find_open_slots(self, *args, **kwargs):
        self.calls.append("find_open_slots")
        if self._raise:
            raise self.CalendarError("freebusy failed")
        return list(self._slots)


@pytest.fixture
def cal(monkeypatch):
    fake = FakeCal()
    monkeypatch.setattr(scheduling, "calendar_api", fake)
    return fake


def _plan(classification, cal_fake=None, monkeypatch=None):
    if cal_fake is not None:
        monkeypatch.setattr(scheduling, "calendar_api", cal_fake)
    return scheduling.plan_action(classification, LEAD, CFG, "me@example.com")


# --- non-yes intents --------------------------------------------------------

def test_no_intent_drafts_decline_ack(cal):
    action = _plan({"intent": "no", "summary": "not interested"})
    assert action["kind"] == "decline_ack"
    assert "Jane" in action["email_body"]
    assert action["email_subject"]
    assert cal.calls == []  # no calendar lookup for a decline


def test_maybe_intent_is_manual(cal):
    action = _plan({"intent": "maybe", "summary": "wants to think about it"})
    assert action == {"kind": "manual", "reason": "wants to think about it"}


def test_question_intent_is_manual(cal):
    action = _plan({"intent": "question", "summary": "asked about pricing"})
    assert action["kind"] == "manual"


def test_unknown_intent_is_manual(cal):
    action = _plan({"intent": "banana"})
    assert action["kind"] == "manual"


def test_empty_classification_returns_none(cal):
    assert _plan({}) is None
    assert scheduling.plan_action(None, LEAD, CFG, "me@x.com") is None


# --- yes intent -----------------------------------------------------------

def test_yes_with_free_proposed_time_books(monkeypatch):
    cal = FakeCal(free=True)
    action = _plan(
        {"intent": "yes", "proposed_start": "2026-09-02T14:00:00", "summary": "yes, Tuesday 2pm"},
        cal, monkeypatch,
    )
    assert action["kind"] == "book"
    assert action["start"] == datetime(2026, 9, 2, 14, 0)
    assert "Tuesday" in action["email_body"] or "Sep 02" in action["email_body"]
    assert "Acme Freight" in action["event_summary"]
    assert "slot_is_free" in cal.calls


def test_yes_with_taken_proposed_time_proposes_alternatives(monkeypatch):
    cal = FakeCal(free=False)
    action = _plan(
        {"intent": "yes", "proposed_start": "2026-09-02T14:00:00", "summary": "yes, Tuesday 2pm"},
        cal, monkeypatch,
    )
    assert action["kind"] == "propose"
    assert action["slots"] == DEFAULT_SLOTS
    assert cal.calls == ["slot_is_free", "find_open_slots"]
    # the three slots are rendered into the email
    assert action["email_body"].count("  - ") == 3


def test_yes_without_a_time_proposes(monkeypatch):
    cal = FakeCal()
    action = _plan({"intent": "yes", "proposed_start": None, "summary": "yes, sounds good"}, cal, monkeypatch)
    assert action["kind"] == "propose"
    assert cal.calls == ["find_open_slots"]  # never checked a specific slot


def test_yes_calendar_error_falls_back_to_manual(monkeypatch):
    cal = FakeCal(raise_error=True)
    action = _plan({"intent": "yes", "proposed_start": None, "summary": "yes"}, cal, monkeypatch)
    assert action["kind"] == "manual"
    assert "calendar lookup failed" in action["reason"]


def test_yes_no_slots_available_is_manual(monkeypatch):
    cal = FakeCal(slots=[])
    action = _plan({"intent": "yes", "proposed_start": None, "summary": "yes"}, cal, monkeypatch)
    assert action["kind"] == "manual"
    assert "no open slots" in action["reason"]


def test_yes_unparseable_proposed_time_still_proposes(monkeypatch):
    cal = FakeCal()
    action = _plan(
        {"intent": "yes", "proposed_start": "sometime next week", "summary": "yes"},
        cal, monkeypatch,
    )
    assert action["kind"] == "propose"
    assert cal.calls == ["find_open_slots"]


def test_yes_proposed_time_in_the_past_proposes_not_books(monkeypatch):
    cal = FakeCal(free=True)
    monkeypatch.setattr(scheduling, "calendar_api", cal)
    past = datetime(2020, 1, 2, 10, 0).isoformat()
    action = scheduling.plan_action(
        {"intent": "yes", "proposed_start": past, "summary": "yes"}, LEAD, CFG, "me@x.com"
    )
    assert action["kind"] == "propose"
    assert "slot_is_free" not in cal.calls  # never even checked the bogus time


def test_yes_proposed_time_beyond_window_proposes_not_books(monkeypatch):
    cal = FakeCal(free=True)
    monkeypatch.setattr(scheduling, "calendar_api", cal)
    now = datetime(2026, 6, 1, 9, 0)
    far = (now.replace(hour=10) + timedelta(days=90)).isoformat()
    action = scheduling.plan_action(
        {"intent": "yes", "proposed_start": far, "summary": "yes"}, LEAD, CFG, "me@x.com", now=now,
    )
    assert action["kind"] == "propose"
    assert cal.calls == ["find_open_slots"]


def test_yes_proposed_time_outside_business_hours_proposes(monkeypatch):
    cal = FakeCal(free=True)
    monkeypatch.setattr(scheduling, "calendar_api", cal)
    now = datetime(2026, 6, 1, 9, 0)  # Monday
    evening = datetime(2026, 6, 3, 21, 0).isoformat()  # Wed 21:00, past business end
    action = scheduling.plan_action(
        {"intent": "yes", "proposed_start": evening, "summary": "yes"}, LEAD, CFG, "me@x.com", now=now,
    )
    assert action["kind"] == "propose"


def test_yes_in_bounds_still_books(monkeypatch):
    cal = FakeCal(free=True)
    monkeypatch.setattr(scheduling, "calendar_api", cal)
    now = datetime(2026, 6, 1, 9, 0)  # Monday
    good = datetime(2026, 6, 3, 14, 0).isoformat()  # Wed 14:00, ~2 days out
    action = scheduling.plan_action(
        {"intent": "yes", "proposed_start": good, "summary": "yes"}, LEAD, CFG, "me@x.com", now=now,
    )
    assert action["kind"] == "book"
    assert action["start"] == datetime(2026, 6, 3, 14, 0)


def test_propose_acknowledges_a_declined_out_of_bounds_time(monkeypatch):
    cal = FakeCal(free=True)
    monkeypatch.setattr(scheduling, "calendar_api", cal)
    past = datetime(2020, 1, 2, 10, 0).isoformat()
    action = scheduling.plan_action(
        {"intent": "yes", "proposed_start": past, "summary": "yes"}, LEAD, CFG, "me@x.com"
    )
    assert action["kind"] == "propose"
    # the rejected time the lead asked for is named in the email
    assert "Jan 02 at 10:00 AM" in action["email_body"]
    assert "doesn't work on my end" in action["email_body"]


def test_propose_acknowledges_a_taken_proposed_time(monkeypatch):
    cal = FakeCal(free=False)  # slot_is_free -> False, so we decline it
    action = _plan(
        {"intent": "yes", "proposed_start": "2026-09-02T14:00:00", "summary": "yes"},
        cal, monkeypatch,
    )
    assert action["kind"] == "propose"
    assert "Sep 02 at 02:00 PM" in action["email_body"]


def test_propose_without_a_declined_time_uses_the_plain_opener(monkeypatch):
    cal = FakeCal()
    action = _plan({"intent": "yes", "proposed_start": None, "summary": "yes"}, cal, monkeypatch)
    assert action["kind"] == "propose"
    assert "Glad you're open to a call" in action["email_body"]
    assert "doesn't work on my end" not in action["email_body"]


def test_custom_templates_from_config_are_used(monkeypatch):
    cal = FakeCal(free=True)
    cfg = dict(CFG, meeting_confirm_body_template="CUSTOM {{ name }} {{ meeting_time }}")
    monkeypatch.setattr(scheduling, "calendar_api", cal)
    action = scheduling.plan_action(
        {"intent": "yes", "proposed_start": "2026-09-02T14:00:00"}, LEAD, cfg, "me@x.com"
    )
    assert action["email_body"].startswith("CUSTOM Jane Lee")
