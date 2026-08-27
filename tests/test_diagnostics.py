"""outreach/diagnostics.py - every check is guarded and returns a verdict, never raises."""

from outreach import diagnostics

CFG = {
    "sender_name": "", "sender_company": "",
    "excel_path": "Z:\\missing-dir\\nope.xlsx", "gmail_address": "", "calendar_id": "primary",
    "llm_model": "claude-haiku-4-5-20251001",
}

_G = None  # the _gmail arg is unused by the checks we test directly


def test_run_checks_returns_a_verdict_per_check_and_never_raises(monkeypatch):
    monkeypatch.setattr(diagnostics, "get_logger", lambda n: __import__("logging").getLogger(n))
    results = diagnostics.run_checks(dict(CFG))
    assert isinstance(results, list) and len(results) == len(diagnostics.CHECK_NAMES)
    for r in results:
        assert set(r) == {"name", "status", "detail"}
        assert r["status"] in ("ok", "warn", "fail")


def test_business_details_warns_when_blank():
    assert diagnostics._check_config({"sender_name": "", "sender_company": ""}, _G)["status"] == "warn"


def test_business_details_ok_when_set():
    assert diagnostics._check_config({"sender_name": "Al", "sender_company": "FreightCo"}, _G)["status"] == "ok"


def test_gmail_check_fails_without_account():
    assert diagnostics._check_gmail_send({"gmail_address": ""}, _G)["status"] == "fail"


def test_anthropic_warns_without_key(monkeypatch):
    monkeypatch.setattr("outreach.credentials.get_anthropic_key", lambda: None)
    assert diagnostics._check_anthropic(dict(CFG), _G)["status"] == "warn"


def test_excel_check_fails_on_bad_path():
    assert diagnostics._check_excel({"excel_path": "Z:\\definitely\\missing\\dir\\x.xlsx"}, _G)["status"] in ("fail", "warn")


def test_a_crashing_check_is_caught(monkeypatch):
    monkeypatch.setattr(diagnostics, "_check_calendar", lambda cfg, g: 1 / 0)
    monkeypatch.setattr(diagnostics, "_CHECKS", [diagnostics._check_config, diagnostics._check_calendar])
    results = diagnostics.run_checks(dict(CFG))
    assert any(r["status"] == "fail" for r in results)


def test_checks_run_concurrently(monkeypatch):
    import time
    monkeypatch.setattr(diagnostics, "_CHECKS", [lambda c, g: (time.sleep(0.3), diagnostics._ok("x"))[1] for _ in range(5)])
    t = time.time()
    diagnostics.run_checks(dict(CFG))
    assert time.time() - t < 0.9  # 5 x 0.3s serial would be 1.5s
