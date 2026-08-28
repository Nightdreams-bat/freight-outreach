"""Wave 4: timezone config validation, poison-reply cap, web reminder brake."""

from datetime import datetime, timedelta

import pytest

from outreach import config, process_replies
from tests.test_process_replies import BASE_CFG, FakeStore  # noqa: F401


# --- timezone config (P1-12 / P1-6) --------------------------------------

def test_default_config_has_timezone_key():
    assert "timezone" in config.default_config()


def test_migrate_replaces_invalid_stored_timezone(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    path.write_text('{"timezone": "Not/AZone", "column_map": {}}', encoding="utf-8")
    cfg = config.load_config()
    assert cfg["timezone"] != "Not/AZone"  # dropped; re-detected (may be "")


def test_migrate_keeps_a_valid_stored_timezone(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    path.write_text('{"timezone": "Europe/Chisinau", "column_map": {}}', encoding="utf-8")
    assert config.load_config()["timezone"] == "Europe/Chisinau"


def test_is_valid_tz():
    assert config._is_valid_tz("America/New_York") is True
    assert config._is_valid_tz("Middle/Earth") is False
    assert config._is_valid_tz("") is False


# --- poison-reply cap (P1-19) -------------------------------------------

@pytest.fixture
def wired(monkeypatch, tmp_path):
    from outreach import gmail_read, llm, reply_queue, scheduling  # noqa: F401

    state = {
        "cfg": dict(BASE_CFG),
        "rows": [(2, {"Name": "J", "Company": "A", "Email": "j@a.test",
                      "ColdEmailSentAt": "2026-08-01 09:00:00", "ReplyStatus": ""})],
        "replies": [{"email": "j@a.test", "thread_id": "t", "message_id": "poison",
                     "received_at": "2026-08-27 10:00:00", "text": "hello"}],
        "processed": [],
    }
    store = FakeStore(state["rows"])
    monkeypatch.setattr(process_replies, "REPLY_FAILURES_PATH", tmp_path / "reply_failures.json")
    monkeypatch.setattr(process_replies, "load_config", lambda: state["cfg"])
    monkeypatch.setattr(process_replies, "ExcelStore", lambda *a, **k: store)
    monkeypatch.setattr(process_replies.gmail_read, "fetch_new_replies", lambda *a, **k: state["replies"])
    monkeypatch.setattr(process_replies.gmail_read, "mark_processed",
                        lambda ids: state["processed"].extend(ids))

    def boom(*a, **k):
        raise RuntimeError("cannot classify this one")

    monkeypatch.setattr(process_replies.llm, "classify_reply", boom)
    return state


def test_poison_message_marked_processed_after_three_failures(wired):
    for _ in range(2):
        summary = process_replies.main([])
        assert wired["processed"] == []  # not given up yet
        assert summary["skipped"] == 1
    summary = process_replies.main([])  # 3rd failure
    assert wired["processed"] == ["poison"]
    assert summary["failed"] == 1


def test_process_replies_returns_summary_dict(wired, monkeypatch):
    monkeypatch.setattr(process_replies.llm, "classify_reply",
                        lambda *a, **k: {"intent": "no", "proposed_start": None, "summary": "no"})
    monkeypatch.setattr(process_replies.reply_queue, "enqueue", lambda *a, **k: "q")
    summary = process_replies.main([])
    assert summary["classified"] == 1
    assert set(summary) >= {"classified", "enqueued", "flagged", "failed", "skipped"}


def _wait_for_job(web_app, timeout=5.0):
    """The dashboard runs the job on a daemon thread; block until it finishes."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if web_app._JOB["status"] != "running":
            return
        time.sleep(0.01)
    raise AssertionError("background job did not finish")


# --- web reminder brake sends soonest-N, never "sent none" (item 9) -----

def test_web_send_reminders_now_sends_soonest_n(monkeypatch):
    from outreach.web import app as web_app
    from tests.test_web_replies import BASE_CFG as WEB_CFG

    now = datetime.now()
    cands = [(i, {"Email": f"l{i}@x.test"}, now + timedelta(hours=1 + i)) for i in range(5)]
    cfg = dict(WEB_CFG, max_reminders_per_run=3, daily_send_cap=100)

    monkeypatch.setattr(web_app, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(web_app, "ExcelStore", lambda *a, **k: object())
    monkeypatch.setattr(web_app, "reminder_candidates", lambda store, w: list(cands))
    monkeypatch.setattr(web_app, "apply_daily_cap", lambda c, cap, sort_key=None: (list(c), cap, 0))
    monkeypatch.setattr(web_app, "build_mailer", lambda cfg: object())
    seen = {}
    monkeypatch.setattr(web_app, "send_reminder_batch",
                        lambda cfg, store, mailer, c, dry_run=False:
                        seen.update(ids=[x[0] for x in c]) or {"sent": len(c), "errors": []})

    application = web_app.create_app()
    application.config.update(TESTING=True)
    client = application.test_client()
    r = client.post("/send/reminders")
    assert r.status_code == 302  # redirect back to /send
    _wait_for_job(web_app)
    assert seen["ids"] == [0, 1, 2]  # soonest three, not "sent none"
