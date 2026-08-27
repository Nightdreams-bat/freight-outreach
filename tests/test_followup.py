"""Multi-touch follow-up drip: outreach.core.followup_candidates + send_followup_batch."""

from datetime import datetime, timedelta

import pytest

from outreach import core

NOW = datetime(2026, 8, 27, 12, 0, 0)

CFG = {
    "sender_name": "Al", "sender_company": "FreightCo", "sender_phone": "",
    "sender_pitch": "", "followup_offsets_days": [3, 7, 14],
}


def _ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class FakeStore:
    def __init__(self, rows):
        # rows: list of dicts; row_idx starts at 2
        self._rows = list(rows)
        self.writes = {}

    def rows(self):
        for i, r in enumerate(self._rows, start=2):
            yield i, r

    def set_value(self, row_idx, col, value):
        self.writes[(row_idx, col)] = value
        self._rows[row_idx - 2][col] = value

    def mark_sent(self, row_idx, col, when=None):
        self.set_value(row_idx, col, _ts(when or NOW))


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subj, body):
        self.sent.append((to, subj, body))


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(core, "record_sent", lambda *a, **k: None)
    monkeypatch.setattr(core, "record_send_history", lambda *a, **k: None)
    monkeypatch.setattr(core.time, "sleep", lambda *_: None)


def _lead(email="lead@acme.test", cold_days_ago=5, **extra):
    row = {"Email": email, "Company": "Acme", "Phone": "",
           "ColdEmailSentAt": _ts(NOW - timedelta(days=cold_days_ago))}
    row.update(extra)
    return row


# --- candidate selection -------------------------------------------------

def test_due_when_first_offset_elapsed():
    store = FakeStore([_lead(cold_days_ago=4)])
    cands = core.followup_candidates(store, CFG, now=NOW)
    assert [(i, s) for i, _, s in cands] == [(2, 0)]


def test_not_due_before_first_offset():
    store = FakeStore([_lead(cold_days_ago=2)])
    assert core.followup_candidates(store, CFG, now=NOW) == []


def test_no_cold_email_is_skipped():
    store = FakeStore([{"Email": "x@y.test", "Company": "Y", "ColdEmailSentAt": ""}])
    assert core.followup_candidates(store, CFG, now=NOW) == []


def test_any_reply_pauses_the_drip():
    store = FakeStore([_lead(ReplyStatus="maybe")])
    assert core.followup_candidates(store, CFG, now=NOW) == []


def test_booked_meeting_pauses_the_drip():
    store = FakeStore([_lead(MeetingDateTime="2026-09-01 10:00:00")])
    assert core.followup_candidates(store, CFG, now=NOW) == []


def test_stage_gating_and_next_offset():
    # one nudge already sent 8 days ago -> stage 1, offset[1]=7 -> due
    store = FakeStore([_lead(cold_days_ago=20, FollowupStage=1,
                             FollowupSentAt=_ts(NOW - timedelta(days=8)))])
    cands = core.followup_candidates(store, CFG, now=NOW)
    assert [(i, s) for i, _, s in cands] == [(2, 1)]


def test_stage_exhausted_drops_out():
    store = FakeStore([_lead(cold_days_ago=90, FollowupStage=3,
                             FollowupSentAt=_ts(NOW - timedelta(days=40)))])
    assert core.followup_candidates(store, CFG, now=NOW) == []


# --- sending -----------------------------------------------------------

def test_send_bumps_stage_and_stamps_time():
    store = FakeStore([_lead(cold_days_ago=4)])
    cands = core.followup_candidates(store, CFG, now=NOW)
    mailer = FakeMailer()
    r = core.send_followup_batch(CFG, store, mailer, cands)
    assert r["sent"] == 1
    assert store.writes[(2, "FollowupStage")] == 1
    assert (2, "FollowupSentAt") in store.writes
    assert len(mailer.sent) == 1


def test_last_stage_uses_breakup_body():
    store = FakeStore([_lead(cold_days_ago=90, FollowupStage=2,
                             FollowupSentAt=_ts(NOW - timedelta(days=20)))])
    cands = core.followup_candidates(store, CFG, now=NOW)
    assert cands and cands[0][2] == 2  # final stage (len(offsets)-1)
    mailer = FakeMailer()
    core.send_followup_batch(CFG, store, mailer, cands)
    body = mailer.sent[0][2]
    assert "won't keep filling your inbox" in body or "leave it here" in body


def test_idempotent_same_day():
    store = FakeStore([_lead(cold_days_ago=4)])
    cands = core.followup_candidates(store, CFG, now=NOW)
    core.send_followup_batch(CFG, store, FakeMailer(), cands)
    # re-scan immediately: stage bumped + just-sent -> nothing due
    assert core.followup_candidates(store, CFG, now=NOW) == []
