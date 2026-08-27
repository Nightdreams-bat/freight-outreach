"""Wave 3: process_replies end-to-end with every collaborator faked (no network)."""

from datetime import datetime

import pytest

from outreach import process_replies

BASE_CFG = {
    "reply_scan_enabled": True,
    "gmail_address": "me@example.com",
    "excel_path": "injected.xlsx",
    "sender_company": "FreightCo",
    "llm_model": "claude-haiku-4-5-20251001",
    "reply_lookback_days": 30,
    "meeting_duration_minutes": 30,
    "calendar_id": "primary",
    "business_hours": {"start": 9, "end": 17},
    "business_days": [0, 1, 2, 3, 4],
    "scheduling_window_days": 10,
    "min_notice_hours": 24,
}


class FakeStore:
    def __init__(self, rows):
        self._rows = rows  # list of (row_idx, values)
        self.writes = []

    def rows(self):
        yield from self._rows

    def set_value(self, row_idx, col, value):
        self.writes.append((row_idx, col, value))


@pytest.fixture
def wired(monkeypatch):
    """Patch process_replies' collaborators; return a dict the test tweaks."""
    state = {
        "cfg": dict(BASE_CFG),
        "rows": [
            (2, {"Name": "Jane", "Company": "Acme", "Email": "jane@acme.test", "ColdEmailSentAt": "2026-08-01 09:00:00", "ReplyStatus": ""}),
            (3, {"Name": "Bob", "Company": "Bolt", "Email": "bob@bolt.test", "ColdEmailSentAt": "2026-08-01 09:00:00", "ReplyStatus": ""}),
            (4, {"Name": "Sue", "Company": "Cog", "Email": "sue@cog.test", "ColdEmailSentAt": "2026-08-01 09:00:00", "ReplyStatus": ""}),
        ],
        "replies": [
            {"email": "jane@acme.test", "thread_id": "t1", "message_id": "m1", "received_at": "2026-08-27 10:00:00", "text": "Yes let's talk"},
            {"email": "bob@bolt.test", "thread_id": "t2", "message_id": "m2", "received_at": "2026-08-27 10:05:00", "text": "Not interested, remove me"},
            {"email": "sue@cog.test", "thread_id": "t3", "message_id": "m3", "received_at": "2026-08-27 10:10:00", "text": "What do you charge?"},
        ],
        "classify": {
            "jane@acme.test": {"intent": "yes", "proposed_start": None, "proposed_end": None, "summary": "keen to talk"},
            "bob@bolt.test": {"intent": "no", "proposed_start": None, "proposed_end": None, "summary": "not interested"},
            "sue@cog.test": {"intent": "question", "proposed_start": None, "proposed_end": None, "summary": "asked about pricing"},
        },
        "enqueued": [],
        "processed": [],
    }

    store = FakeStore(state["rows"])
    state["store"] = store

    monkeypatch.setattr(process_replies, "load_config", lambda: state["cfg"])
    monkeypatch.setattr(process_replies, "ExcelStore", lambda *a, **k: store)
    monkeypatch.setattr(process_replies.gmail_read, "fetch_new_replies",
                        lambda *a, **k: state["replies"])
    monkeypatch.setattr(process_replies.gmail_read, "mark_processed",
                        lambda ids: state["processed"].extend(ids))

    def fake_classify(text, *, sender_company, now_iso, model):
        for r in state["replies"]:
            if r["text"] == text:
                return state["classify"][r["email"]]
        raise AssertionError(f"classify_reply got unexpected text {text!r}")

    monkeypatch.setattr(process_replies.llm, "classify_reply", fake_classify)
    monkeypatch.setattr(process_replies.reply_queue, "enqueue",
                        lambda action, **meta: state["enqueued"].append((action, meta)) or "qid")
    # scheduling.plan_action runs for real; only the calendar calls it makes are stubbed
    monkeypatch.setattr(process_replies.scheduling.calendar_api, "find_open_slots",
                        lambda *a, **k: [datetime(2026, 9, 1, 9, 0), datetime(2026, 9, 1, 9, 30)])
    monkeypatch.setattr(process_replies.scheduling.calendar_api, "slot_is_free",
                        lambda *a, **k: True)
    return state


def test_disabled_gate_returns_early(wired, monkeypatch):
    wired["cfg"]["reply_scan_enabled"] = False
    called = []
    monkeypatch.setattr(process_replies.gmail_read, "fetch_new_replies",
                        lambda *a, **k: called.append(1) or [])
    process_replies.main([])
    assert called == []
    assert wired["enqueued"] == []


def test_no_gmail_account_returns_early(wired):
    wired["cfg"]["gmail_address"] = ""
    process_replies.main([])
    assert wired["enqueued"] == []


def test_end_to_end_queues_and_marks(wired):
    process_replies.main([])

    kinds = sorted(a["kind"] for a, _ in wired["enqueued"])
    assert kinds == ["decline_ack", "manual", "propose"]  # no, question, yes
    assert set(wired["processed"]) == {"m1", "m2", "m3"}

    # each lead got ReplyStatus + LastReplyAt written
    statuses = {(r, c): v for r, c, v in wired["store"].writes}
    assert statuses[(2, "ReplyStatus")] == "yes"
    assert statuses[(3, "ReplyStatus")] == "no"
    assert statuses[(4, "ReplyStatus")] == "question"
    assert (2, "LastReplyAt") in statuses


def test_terminal_reply_state_is_skipped(wired):
    wired["rows"][1][1]["ReplyStatus"] = "booked"  # Bob already booked
    # only jane + sue remain as candidates; fetch is still faked to return all 3,
    # but bob won't be in the by_email map so his reply is ignored
    process_replies.main([])
    emails = {meta["lead_email"] for _, meta in wired["enqueued"]}
    assert "bob@bolt.test" not in emails


def test_llm_not_configured_aborts(wired, monkeypatch):
    from outreach.llm import LLMNotConfigured

    def boom(*a, **k):
        raise LLMNotConfigured("no key")

    monkeypatch.setattr(process_replies.llm, "classify_reply", boom)
    process_replies.main([])
    assert wired["enqueued"] == []


def test_empty_reply_text_is_skipped(wired):
    wired["replies"][0]["text"] = "   "
    process_replies.main([])
    emails = {meta["lead_email"] for _, meta in wired["enqueued"]}
    assert "jane@acme.test" not in emails
    assert "m1" not in wired["processed"]
