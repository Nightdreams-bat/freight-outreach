"""outreach/diagnostics.py - every check is guarded and returns a verdict, never raises."""

import pytest

from outreach import diagnostics

CFG = {
    "sender_name": "", "sender_company": "",
    "excel_path": "Z:\\missing-dir\\nope.xlsx", "gmail_address": "", "calendar_id": "primary",
    "llm_model": "claude-haiku-4-5-20251001",
}


def test_run_checks_returns_a_verdict_per_check_and_never_raises(monkeypatch):
    monkeypatch.setattr(diagnostics, "get_logger", lambda n: __import__("logging").getLogger(n))
    results = diagnostics.run_checks(dict(CFG))
    assert isinstance(results, list) and results
    for r in results:
        assert set(r) == {"name", "status", "detail"}
        assert r["status"] in ("ok", "warn", "fail")


def test_business_details_warns_when_blank():
    r = diagnostics._check_config({"sender_name": "", "sender_company": ""})
    assert r["status"] == "warn"


def test_business_details_ok_when_set():
    r = diagnostics._check_config({"sender_name": "Al", "sender_company": "FreightCo"})
    assert r["status"] == "ok"


def test_gmail_check_fails_without_account():
    r = diagnostics._check_gmail_send({"gmail_address": ""})
    assert r["status"] == "fail"


def test_anthropic_warns_without_key(monkeypatch):
    monkeypatch.setattr("outreach.credentials.get_anthropic_key", lambda: None)
    r = diagnostics._check_anthropic(dict(CFG))
    assert r["status"] == "warn"


def test_excel_check_fails_on_bad_path():
    r = diagnostics._check_excel({"excel_path": "Z:\\definitely\\missing\\dir\\x.xlsx"})
    assert r["status"] in ("fail", "warn")


def test_a_crashing_check_is_caught(monkeypatch):
    monkeypatch.setattr(diagnostics, "_check_calendar", lambda cfg: 1 / 0)
    results = diagnostics.run_checks(dict(CFG))
    assert any(r["status"] == "fail" for r in results)
