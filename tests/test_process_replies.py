"""Wave 3: process_replies end-to-end with every collaborator faked (no network)."""

import contextlib
from datetime import datetime

import pytest

from kairo import process_replies

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
def wired(monkeypatch, tmp_path):
    monkeypatch.setattr(process_replies, "REPLY_FAILURES_PATH", tmp_path / "reply_failures.json")
    monkeypatch.setattr(process_replies, "REPLY_SCAN_LOCK_PATH", tmp_path / "reply_scan.lock")
    monkeypatch.setattr(process_replies.llm_tracker, "LLM_CALLS_PATH", tmp_path / "llm_calls.json")
    monkeypatch.setattr(process_replies.llm_tracker, "data_lock",
                        lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(process_replies, "save_config", lambda cfg: None)
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
            {"email": "bob@bolt.test", "thread_id": "t2", "message_id": "m2", "received_at": "2026-08-27 10:05:00", "text": "Not interested at this time, thanks"},
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
    from kairo.llm import LLMNotConfigured

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


# --- Wave B: hardening + spend guardrail ----------------------------------

def _count_classifies(wired, monkeypatch):
    seen = []
    real = process_replies.llm.classify_reply

    def spy(text, **kw):
        seen.append(text)
        return real(text, **kw)

    monkeypatch.setattr(process_replies.llm, "classify_reply", spy)
    return seen


def test_optout_prefilter_skips_classify(wired, monkeypatch):
    seen = _count_classifies(wired, monkeypatch)
    wired["replies"][0]["text"] = "Please remove me from your list"
    process_replies.main([])
    assert "Please remove me from your list" not in seen  # no Claude call
    assert "m1" in wired["processed"]
    statuses = {(r, c): v for r, c, v in wired["store"].writes}
    assert statuses[(2, "ReplyStatus")] == "optout"
    assert "jane@acme.test" in wired["cfg"]["disallowed_emails"]


def test_ooo_prefilter_skips_classify(wired, monkeypatch):
    seen = _count_classifies(wired, monkeypatch)
    wired["replies"][0]["text"] = "I am out of office until Monday, back then."
    process_replies.main([])
    assert wired["replies"][0]["text"] not in seen
    assert "m1" in wired["processed"]
    assert "jane@acme.test" not in {meta["lead_email"] for _, meta in wired["enqueued"]}


def test_per_run_cap_trims_to_oldest(wired, monkeypatch):
    wired["cfg"]["max_classify_per_run"] = 2
    seen = _count_classifies(wired, monkeypatch)
    process_replies.main([])
    assert len(seen) == 2
    # sue's reply is the newest (10:10) - left for next run
    assert "m3" not in wired["processed"]
    assert "sue@cog.test" not in {meta["lead_email"] for _, meta in wired["enqueued"]}


def test_monthly_cap_breaks_loop(wired, monkeypatch):
    wired["cfg"]["max_llm_calls_per_month"] = 0
    seen = _count_classifies(wired, monkeypatch)
    process_replies.main([])
    assert seen == []
    assert wired["processed"] == []
    assert wired["enqueued"] == []


def test_record_llm_call_after_each_success(wired):
    process_replies.main([])
    assert process_replies.llm_tracker.calls_this_month() == 3


def test_mark_processed_happens_before_enqueue(wired, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("enqueue crashed")

    monkeypatch.setattr(process_replies.reply_queue, "enqueue", boom)
    with pytest.raises(RuntimeError):
        process_replies.main([])
    # the classified message was marked processed before the crash - never re-billed
    assert "m1" in wired["processed"]


def test_lock_file_short_circuits(wired, monkeypatch):
    process_replies.REPLY_SCAN_LOCK_PATH.write_text("999 now", encoding="utf-8")
    called = []
    monkeypatch.setattr(process_replies.gmail_read, "fetch_new_replies",
                        lambda *a, **k: called.append(1) or [])
    process_replies.main([])
    assert called == []


def test_stale_lock_is_broken(wired, monkeypatch):
    import os
    import time

    lock = process_replies.REPLY_SCAN_LOCK_PATH
    lock.write_text("999 old", encoding="utf-8")
    old = time.time() - 40 * 60
    os.utime(lock, (old, old))
    process_replies.main([])
    assert set(wired["processed"]) == {"m1", "m2", "m3"}
    assert not lock.exists()  # released in finally
