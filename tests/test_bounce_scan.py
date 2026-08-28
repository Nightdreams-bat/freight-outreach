"""Wave B: bounce detection + auto-suppress - no LLM, works with reply scan off."""

import pytest

from kairo import bounce_scan


class FakeStore:
    def __init__(self, rows):
        self._rows = rows
        self.writes = []

    def rows(self):
        yield from self._rows

    def set_value(self, row_idx, col, value):
        self.writes.append((row_idx, col, value))


CFG = {
    "gmail_address": "me@example.com",
    "reply_lookback_days": 30,
}

ROWS = [
    (2, {"Email": "jane@acme.test", "ColdEmailSentAt": "2026-08-01 09:00:00", "ReplyStatus": ""}),
    (3, {"Email": "bob@bolt.test", "ColdEmailSentAt": "2026-08-01 09:00:00", "ReplyStatus": ""}),
    (4, {"Email": "sue@cog.test", "ColdEmailSentAt": "2026-08-01 09:00:00", "ReplyStatus": "booked"}),
]


@pytest.fixture(autouse=True)
def _no_disk(monkeypatch):
    monkeypatch.setattr(bounce_scan.gmail_read, "mark_processed", lambda ids: None)


def _run(monkeypatch, bounces, cfg=None, retire_ok=True):
    monkeypatch.setattr(bounce_scan.gmail_read, "fetch_bounces",
                        lambda addr, lookback: bounces)
    retired_calls = []

    def fake_retire(store, row_idx, values, *, reason):
        retired_calls.append((row_idx, reason))
        return retire_ok

    monkeypatch.setattr(bounce_scan.suppression, "retire_lead", fake_retire)
    cfg = cfg if cfg is not None else dict(CFG)
    store = FakeStore(list(ROWS))
    result = bounce_scan.scan_bounces(cfg, store)
    return result, store, retired_calls


def test_permanent_bounce_retires_lead(monkeypatch):
    bounces = [{"message_id": "b1", "failed_email": "bob@bolt.test", "permanent": True, "received_at": ""}]
    retired, _, calls = _run(monkeypatch, bounces)
    assert retired == ["bob@bolt.test"]
    assert calls == [(3, "undeliverable: hard bounce (bob@bolt.test)")]


def test_transient_bounce_is_not_retired(monkeypatch):
    bounces = [{"message_id": "b1", "failed_email": "bob@bolt.test", "permanent": False, "received_at": ""}]
    marked = []
    monkeypatch.setattr(bounce_scan.gmail_read, "mark_processed", lambda ids: marked.extend(ids))
    retired, _, calls = _run(monkeypatch, bounces)
    assert retired == []
    assert calls == []
    assert marked == ["b1"]


def test_bounce_for_unknown_address_is_ignored(monkeypatch):
    bounces = [{"message_id": "b1", "failed_email": "stranger@nope.test", "permanent": True, "received_at": ""}]
    retired, _, calls = _run(monkeypatch, bounces)
    assert retired == [] and calls == []


def test_booked_lead_is_not_scanned(monkeypatch):
    bounces = [{"message_id": "b1", "failed_email": "sue@cog.test", "permanent": True, "received_at": ""}]
    retired, _, calls = _run(monkeypatch, bounces)
    assert retired == [] and calls == []


def test_locked_sheet_leaves_ndr_unprocessed(monkeypatch):
    bounces = [{"message_id": "b1", "failed_email": "bob@bolt.test", "permanent": True, "received_at": ""}]
    marked = []
    monkeypatch.setattr(bounce_scan.gmail_read, "mark_processed", lambda ids: marked.extend(ids))
    retired, _, _ = _run(monkeypatch, bounces, retire_ok=False)
    assert retired == []
    assert marked == []  # retry next run


def test_no_gmail_account_is_a_noop(monkeypatch):
    retired, _, calls = _run(monkeypatch, [], cfg={**CFG, "gmail_address": ""})
    assert retired == [] and calls == []
