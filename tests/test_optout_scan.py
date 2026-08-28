"""Wave 2: keyword-only opt-out scan - no LLM, works with reply scan off."""

import pytest

from kairo import optout_scan


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
    "reply_scan_enabled": False,
    "disallowed_emails": [],
}

ROWS = [
    (2, {"Email": "jane@acme.test", "ColdEmailSentAt": "2026-08-01 09:00:00", "ReplyStatus": ""}),
    (3, {"Email": "bob@bolt.test", "ColdEmailSentAt": "2026-08-01 09:00:00", "ReplyStatus": ""}),
]


@pytest.fixture(autouse=True)
def _no_disk(monkeypatch):
    monkeypatch.setattr(optout_scan, "save_config", lambda cfg: None)
    monkeypatch.setattr(optout_scan.gmail_read, "mark_processed", lambda ids: None)


def _run(monkeypatch, replies, cfg=None):
    monkeypatch.setattr(
        optout_scan.gmail_read, "fetch_new_replies",
        lambda addr, lookback, emails: replies,
    )
    cfg = cfg if cfg is not None else {**CFG, "disallowed_emails": []}
    store = FakeStore(list(ROWS))
    return optout_scan.scan_optouts(cfg, store), store, cfg


def test_matching_reply_is_blocked(monkeypatch):
    replies = [{"email": "bob@bolt.test", "message_id": "m2", "text": "please remove me from your list"}]
    opted, store, cfg = _run(monkeypatch, replies)
    assert opted == ["bob@bolt.test"]
    assert "bob@bolt.test" in cfg["disallowed_emails"]
    assert (3, "ReplyStatus", "optout") in store.writes


def test_romanian_optout_is_blocked(monkeypatch):
    replies = [{"email": "jane@acme.test", "message_id": "m1", "text": "Va rog sa ma dezabonati, multumesc"}]
    opted, _, cfg = _run(monkeypatch, replies)
    assert opted == ["jane@acme.test"]
    assert "jane@acme.test" in cfg["disallowed_emails"]


def test_non_matching_reply_is_left_alone(monkeypatch):
    replies = [{"email": "jane@acme.test", "message_id": "m1", "text": "Sounds good, can you call me tomorrow?"}]
    opted, store, cfg = _run(monkeypatch, replies)
    assert opted == []
    assert cfg["disallowed_emails"] == []
    assert store.writes == []


def test_no_gmail_account_is_a_noop(monkeypatch):
    opted, _, _ = _run(monkeypatch, [], cfg={**CFG, "gmail_address": "", "disallowed_emails": []})
    assert opted == []
