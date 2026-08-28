"""Batch circuit breaker in kairo.core - a run aborts after N consecutive failures."""

import pytest

from kairo import core

CFG = {"sender_name": "Al", "sender_company": "Co", "sender_phone": "", "sender_pitch": "",
       "send_failure_abort_threshold": 5}


class FakeStore:
    def __init__(self):
        self.stamped = []

    def mark_sent(self, row_idx, col, when=None):
        self.stamped.append(row_idx)


class FlakyMailer:
    def __init__(self, fail_first=None):
        self.fail_first = fail_first  # None => always fail
        self.calls = 0

    def send(self, to, subj, body):
        self.calls += 1
        if self.fail_first is None or self.calls <= self.fail_first:
            raise RuntimeError("token revoked")


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(core, "record_sent", lambda *a, **k: None)
    monkeypatch.setattr(core, "record_send_history", lambda *a, **k: None)
    monkeypatch.setattr(core.time, "sleep", lambda *_: None)
    monkeypatch.setattr(core.dns_check, "domain_resolves", lambda *a, **k: True)
    monkeypatch.setattr(core.suppression, "record_send_history", lambda *a, **k: None)


def _cands(n):
    return [(i, {"Email": f"lead{i}@acme.test", "Company": "Acme", "Phone": ""})
            for i in range(2, 2 + n)]


def test_batch_aborts_after_threshold_consecutive_failures():
    store, mailer = FakeStore(), FlakyMailer(fail_first=None)
    result = core.send_cold_batch(CFG, store, mailer, _cands(12))
    assert mailer.calls == 5  # stopped, did not try all 12
    assert store.stamped == []  # later rows left for the next run
    assert any("aborted: 5 consecutive send failures" in e for e in result["errors"])
    assert result["sent"] == 0


def test_batch_does_not_abort_when_failures_are_not_consecutive():
    store, mailer = FakeStore(), FlakyMailer(fail_first=4)
    result = core.send_cold_batch(CFG, store, mailer, _cands(10))
    assert mailer.calls == 10  # ran the whole list
    assert result["sent"] == 6
    assert not any("aborted" in e for e in result["errors"])


class _RetireStore:
    def __init__(self):
        self.values = {}
        self.stamped = []

    def mark_sent(self, row_idx, col, when=None):
        self.stamped.append(row_idx)

    def set_value(self, row_idx, col, value):
        self.values[(row_idx, col)] = value


def test_cold_batch_retires_lead_when_domain_does_not_resolve(monkeypatch):
    monkeypatch.setattr(core.dns_check, "domain_resolves", lambda *a, **k: False)
    store, mailer = _RetireStore(), FlakyMailer(fail_first=4)
    row = {"Email": "lead@dead-domain.test", "Company": "Acme", "Phone": "", "Notes": ""}
    result = core.send_cold_batch(CFG, store, mailer, [(2, row)])

    assert mailer.calls == 0  # never attempted a send
    assert result["sent"] == 0
    assert "lead@dead-domain.test" in result["skipped"]
    assert store.values[(2, "Suppressed")] == "yes"
    assert "does not resolve" in store.values[(2, "Notes")]


def test_cold_batch_dry_run_skips_the_domain_check(monkeypatch):
    called = []
    monkeypatch.setattr(core.dns_check, "domain_resolves",
                        lambda *a, **k: called.append(1) or False)
    store, mailer = _RetireStore(), FlakyMailer(fail_first=4)
    row = {"Email": "lead@dead-domain.test", "Company": "Acme", "Phone": ""}
    result = core.send_cold_batch(CFG, store, mailer, [(2, row)], dry_run=True)

    assert called == []  # not checked on a dry run
    assert len(result["preview"]) == 1
