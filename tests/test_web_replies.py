"""Wave 3: the /replies dashboard page + Settings additions for reply handling."""

import pytest

from kairo.web import app as web_app

BASE_CFG = {
    "excel_path": "unused.xlsx",
    "sender_name": "Al", "sender_company": "FreightCo", "sender_phone": "",
    "sender_pitch": "", "gmail_address": "al@freightco.test",
    "reminder_interval_hours": 2, "reminder_window_hours": 2,
    "max_reminders_per_run": 25, "daily_send_cap": 150,
    "cold_subject_template": "s", "cold_body_template": "b",
    "reminder_subject_template": "s", "reminder_body_template": "b",
    "meeting_confirm_subject_template": "s", "meeting_confirm_body_template": "b",
    "propose_times_subject_template": "s", "propose_times_body_template": "b",
    "decline_ack_subject_template": "s", "decline_ack_body_template": "b",
}


class FakeQueue:
    def __init__(self, items=None):
        self.items = items or []
        self.approved = []
        self.rejected = []

    def pending(self):
        return [i for i in self.items if i.get("status") == "pending"]

    def get(self, qid):
        return next((i for i in self.items if i["id"] == qid), None)

    def approve(self, qid, **kw):
        self.approved.append(qid)
        return {"status": "done", "message": "Booked it."}

    def reject(self, qid):
        self.rejected.append(qid)
        return True


def _item(qid, kind, **action):
    return {
        "id": qid, "created_at": "2026-08-27 10:00:00", "status": "pending",
        "lead_row_idx": 2, "lead_email": "lead@acme.test", "lead_name": "Lee",
        "lead_company": "Acme", "thread_id": "t1", "reply_summary": "wants to talk",
        "action": {"kind": kind, **action},
    }


@pytest.fixture
def client(monkeypatch):
    fake = FakeQueue()
    monkeypatch.setattr(web_app, "reply_queue", fake)
    monkeypatch.setattr(web_app, "load_config", lambda: dict(BASE_CFG))
    monkeypatch.setattr(web_app, "save_config", lambda cfg: None)
    monkeypatch.setattr(web_app, "task_status", lambda *a, **k: None)
    monkeypatch.setattr(web_app, "get_anthropic_key", lambda: None)
    application = web_app.create_app()
    application.config.update(TESTING=True)
    c = application.test_client()
    c.fake = fake
    return c


def test_replies_empty(client):
    r = client.get("/replies")
    assert r.status_code == 200
    assert b"Nothing waiting" in r.data


def test_replies_renders_each_kind(client):
    client.fake.items = [
        _item("q1", "book", start="2026-09-01T10:00:00", start_display="Mon, Sep 01 at 10:00 AM",
              email_subject="Confirmed", email_body="See you then",
              event_summary="Call", event_description=""),
        _item("q2", "propose", slots=["2026-09-02T14:00:00"],
              slots_display=["Tue, Sep 02 at 02:00 PM"],
              email_subject="Some times", email_body="pick one"),
        _item("q3", "manual", reason="asked about pricing"),
    ]
    body = client.get("/replies").data.decode()
    assert "Mon, Sep 01 at 10:00 AM" in body
    assert "Tue, Sep 02 at 02:00 PM" in body
    assert "asked about pricing" in body
    assert "mail.google.com/mail/u/0/#all/t1" in body


def test_approve_calls_queue(client):
    client.fake.items = [_item("q1", "propose", slots=[], email_subject="s", email_body="b")]
    r = client.post("/replies/q1/approve", follow_redirects=True)
    assert r.status_code == 200
    assert client.fake.approved == ["q1"]
    assert b"Booked it." in r.data


def test_approve_nonpending_is_noop(client):
    client.fake.items = [dict(_item("q1", "propose"), status="done")]
    client.post("/replies/q1/approve", follow_redirects=True)
    assert client.fake.approved == []


def test_reject_calls_queue(client):
    client.fake.items = [_item("q1", "manual", reason="x")]
    client.post("/replies/q1/reject", follow_redirects=True)
    assert client.fake.rejected == ["q1"]


def test_nav_badge_shows_pending_count(client):
    client.fake.items = [_item("q1", "manual", reason="x"), _item("q2", "manual", reason="y")]
    body = client.get("/replies").data.decode()
    assert ">2</span>" in body  # the badge


def test_replies_page_includes_live_refresh_script(client):
    body = client.get("/replies").data.decode()
    assert "replies.js" in body
    assert "window.__repliesRendered = 0" in body


def test_replies_count_endpoint(client):
    client.fake.items = [_item("q1", "manual", reason="x"), _item("q2", "manual", reason="y")]
    r = client.get("/replies/count")
    assert r.status_code == 200
    data = r.get_json()
    assert data == {"pending": 2, "job_running": False}


def test_replies_count_job_running_only_for_replies(client, monkeypatch):
    monkeypatch.setitem(web_app._JOB, "status", "running")
    monkeypatch.setitem(web_app._JOB, "action", "cold")
    assert client.get("/replies/count").get_json()["job_running"] is False
    monkeypatch.setitem(web_app._JOB, "action", "replies")
    assert client.get("/replies/count").get_json()["job_running"] is True


def test_settings_shows_reply_section(client):
    body = client.get("/settings").data.decode()
    assert "Reply handling" in body
    assert "not set" in body  # anthropic key status
    assert 'name="anthropic_api_key"' in body


def test_settings_saves_anthropic_key(client, monkeypatch):
    saved = {}
    monkeypatch.setattr(web_app, "set_anthropic_key", lambda k: saved.setdefault("key", k))
    client.post("/settings", data={**BASE_CFG, "anthropic_api_key": "sk-ant-xyz"},
                follow_redirects=True)
    assert saved["key"] == "sk-ant-xyz"


def test_replies_enable_requires_key(client, monkeypatch):
    called = []
    monkeypatch.setattr(web_app, "register_task", lambda *a, **k: called.append(a) or (True, ""))
    r = client.post("/settings/replies/enable", follow_redirects=True)
    assert b"Anthropic API key first" in r.data
    assert called == []


def test_replies_enable_with_key(client, monkeypatch):
    called = []
    monkeypatch.setattr(web_app, "get_anthropic_key", lambda: "sk-ant-xyz")
    monkeypatch.setattr(web_app, "register_task",
                        lambda *a, **k: called.append(a) or (True, "created"))
    client.post("/settings/replies/enable", follow_redirects=True)
    assert called and called[0][1] == web_app.REPLY_TASK_NAME and called[0][2] == "--replies"


def test_replies_disable(client, monkeypatch):
    called = []
    monkeypatch.setattr(web_app, "unregister_task", lambda *a, **k: called.append(a) or (True, "gone"))
    client.post("/settings/replies/disable", follow_redirects=True)
    assert called and called[0][0] == web_app.REPLY_TASK_NAME
