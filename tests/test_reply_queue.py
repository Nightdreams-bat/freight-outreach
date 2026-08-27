"""Wave 3: reply_queue - enqueue/pending/get/reject and approve() side effects."""

from datetime import datetime

import pytest

from outreach import reply_queue

CFG = {
    "daily_send_cap": 150,
    "gmail_address": "me@example.com",
    "excel_path": "unused-because-store-is-injected.xlsx",
    "meeting_duration_minutes": 30,
    "calendar_id": "primary",
}


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, to_addr, subject, body, **kwargs):
        self.sent.append((to_addr, subject, body, kwargs))


class FakeStore:
    def __init__(self):
        self.values = {}

    def set_value(self, row_idx, col, value):
        self.values[(row_idx, col)] = value


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(reply_queue, "REPLY_QUEUE_PATH", tmp_path / "reply_queue.jsonl")
    monkeypatch.setattr(reply_queue, "record_sent", lambda *a, **k: None)
    monkeypatch.setattr(reply_queue, "record_send_history", lambda *a, **k: None)
    monkeypatch.setattr(reply_queue, "remaining_today", lambda cap: 50)
    monkeypatch.setattr(reply_queue.calendar_api, "create_event", lambda *a, **k: "evt_test123")
    monkeypatch.setattr(reply_queue.calendar_api, "local_tz_name", lambda: "UTC")
    monkeypatch.setattr(reply_queue.calendar_api, "slot_is_free", lambda *a, **k: True)


def _enqueue_book():
    return reply_queue.enqueue(
        {
            "kind": "book",
            "start": datetime(2026, 9, 2, 14, 0),
            "email_subject": "Confirmed",
            "email_body": "See you then",
            "event_summary": "Intro call: FreightCo x Acme",
            "event_description": "booked from reply",
        },
        lead_row_idx=5,
        lead_email="jane@acme.test",
        lead_name="Jane",
        lead_company="Acme",
        thread_id="t_1",
        reply_summary="yes, Tuesday 2pm",
    )


# --- enqueue / pending / get / reject ------------------------------------

def test_enqueue_then_pending_and_get():
    qid = _enqueue_book()
    pend = reply_queue.pending()
    assert len(pend) == 1
    assert pend[0]["id"] == qid
    assert pend[0]["lead_company"] == "Acme"
    assert pend[0]["action"]["start_display"].startswith("Wednesday")  # 2026-09-02 is a Wednesday
    assert reply_queue.get(qid)["reply_summary"] == "yes, Tuesday 2pm"
    assert reply_queue.get("nope") is None


def test_reject_removes_from_pending():
    qid = _enqueue_book()
    assert reply_queue.reject(qid) is True
    assert reply_queue.pending() == []
    assert reply_queue.get(qid)["status"] == "rejected"
    assert reply_queue.reject(qid) is False  # already resolved


def test_newest_first():
    a = _enqueue_book()
    b = _enqueue_book()
    assert [r["id"] for r in reply_queue.pending()] == [b, a]


# --- approve: book ------------------------------------------------------

def test_approve_book_creates_event_sends_and_writes_sheet():
    qid = _enqueue_book()
    mailer, store = FakeMailer(), FakeStore()
    result = reply_queue.approve(qid, cfg=CFG, store=store, mailer=mailer)

    assert result["status"] == "done"
    assert result["event_id"] == "evt_test123"
    assert len(mailer.sent) == 1 and mailer.sent[0][0] == "jane@acme.test"
    assert store.values[(5, "MeetingDateTime")] == "2026-09-02 14:00:00"
    assert store.values[(5, "MeetingEventId")] == "evt_test123"
    assert store.values[(5, "ReplyStatus")] == "booked"
    assert reply_queue.get(qid)["status"] == "done"
    assert reply_queue.pending() == []


def test_approve_book_blocked_when_slot_taken_since_draft(monkeypatch):
    monkeypatch.setattr(reply_queue.calendar_api, "slot_is_free", lambda *a, **k: False)
    created = []
    monkeypatch.setattr(reply_queue.calendar_api, "create_event",
                        lambda *a, **k: created.append(1) or "evt_x")
    qid = _enqueue_book()
    result = reply_queue.approve(qid, cfg=CFG, store=FakeStore(), mailer=FakeMailer())
    assert result["status"] == "error"
    assert "taken" in result["message"]
    assert created == []
    assert reply_queue.get(qid)["status"] == "pending"


def test_approve_book_passes_deterministic_ical_uid(monkeypatch):
    seen = {}
    monkeypatch.setattr(reply_queue.calendar_api, "create_event",
                        lambda *a, **k: seen.update(k) or "evt_ical")
    qid = _enqueue_book()
    reply_queue.approve(qid, cfg=CFG, store=FakeStore(), mailer=FakeMailer())
    assert seen["ical_uid"] == f"freight-{qid}@freightoutreach"


def test_approve_book_soon_meeting_suppresses_reminder():
    from datetime import timedelta

    soon = datetime.now() + timedelta(hours=20)
    qid = reply_queue.enqueue(
        {"kind": "book", "start": soon, "email_subject": "Confirmed", "email_body": "see you",
         "event_summary": "s", "event_description": "d"},
        lead_row_idx=9, lead_email="s@x.test", lead_name="S", lead_company="Z",
    )
    store = FakeStore()
    reply_queue.approve(qid, cfg=CFG, store=store, mailer=FakeMailer())
    assert (9, "ReminderSentAt") in store.values


# --- approve: propose / decline_ack -----------------------------------

def test_approve_propose_sends_and_marks_scheduling():
    qid = reply_queue.enqueue(
        {"kind": "propose", "slots": [datetime(2026, 9, 2, 14, 0)],
         "email_subject": "Times", "email_body": "a few times"},
        lead_row_idx=3, lead_email="k@x.test", lead_name="K", lead_company="X",
    )
    mailer, store = FakeMailer(), FakeStore()
    result = reply_queue.approve(qid, cfg=CFG, store=store, mailer=mailer)
    assert result["status"] == "done"
    assert len(mailer.sent) == 1
    assert store.values[(3, "ReplyStatus")] == "scheduling"


def test_approve_decline_ack_marks_no():
    qid = reply_queue.enqueue(
        {"kind": "decline_ack", "email_subject": "Thanks", "email_body": "understood"},
        lead_row_idx=7, lead_email="d@x.test", lead_name="D", lead_company="Y",
    )
    mailer, store = FakeMailer(), FakeStore()
    reply_queue.approve(qid, cfg=CFG, store=store, mailer=mailer)
    assert store.values[(7, "ReplyStatus")] == "no"


# --- approve: guard rails --------------------------------------------

def test_approve_manual_is_rejected():
    qid = reply_queue.enqueue({"kind": "manual", "reason": "needs a human"}, lead_row_idx=1)
    result = reply_queue.approve(qid, cfg=CFG, store=FakeStore(), mailer=FakeMailer())
    assert result["status"] == "error"
    assert reply_queue.get(qid)["status"] == "pending"  # untouched


def test_approve_respects_daily_cap(monkeypatch):
    monkeypatch.setattr(reply_queue, "remaining_today", lambda cap: 0)
    qid = _enqueue_book()
    mailer = FakeMailer()
    result = reply_queue.approve(qid, cfg=CFG, store=FakeStore(), mailer=mailer)
    assert result["status"] == "deferred"
    assert mailer.sent == []
    assert reply_queue.get(qid)["status"] == "pending"  # still there for tomorrow


def test_approve_unknown_id():
    assert reply_queue.approve("ghost", cfg=CFG)["status"] == "error"


def test_approve_already_done_is_error():
    qid = _enqueue_book()
    reply_queue.approve(qid, cfg=CFG, store=FakeStore(), mailer=FakeMailer())
    again = reply_queue.approve(qid, cfg=CFG, store=FakeStore(), mailer=FakeMailer())
    assert again["status"] == "error"


def test_approve_send_failure_leaves_item_pending():
    qid = _enqueue_book()

    class Boom(FakeMailer):
        def send(self, *a):
            raise RuntimeError("smtp down")

    result = reply_queue.approve(qid, cfg=CFG, store=FakeStore(), mailer=Boom())
    assert result["status"] == "error"
    assert reply_queue.get(qid)["status"] == "pending"


def test_approve_retry_after_send_failure_does_not_rebook(monkeypatch):
    """create_event succeeded, the email send failed. Re-approving must reuse the
    existing event id, not book a second calendar slot."""
    calls = []
    monkeypatch.setattr(
        reply_queue.calendar_api, "create_event",
        lambda *a, **k: calls.append(1) or "evt_once",
    )
    qid = _enqueue_book()

    class Boom(FakeMailer):
        def send(self, *a):
            raise RuntimeError("smtp down")

    reply_queue.approve(qid, cfg=CFG, store=FakeStore(), mailer=Boom())
    assert reply_queue.get(qid)["event_id"] == "evt_once"

    result = reply_queue.approve(qid, cfg=CFG, store=FakeStore(), mailer=FakeMailer())
    assert result["status"] == "done"
    assert len(calls) == 1  # event created once, not twice
