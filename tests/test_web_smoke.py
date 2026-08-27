"""Every route answers without a 500 - the 'make sure every button works' safety net."""

import pytest

from outreach.web import app as web_app
from tests.test_web_replies import BASE_CFG, FakeQueue


class FakeStore:
    email_column_missing = False

    def all_rows(self):
        return iter([(2, {"Email": "lead@acme.test", "Name": "Lee", "Company": "Acme",
                          "Notes": "", "Priority": "3"}, None)])

    def rows(self):
        return iter([(2, {"Email": "lead@acme.test", "Name": "Lee", "Company": "Acme",
                          "Notes": "", "Priority": "3"})])

    def get_row(self, i):
        return {"Suppressed": ""}

    def set_value(self, *a, **k):
        pass


@pytest.fixture
def client(monkeypatch, tmp_path):
    cfg = dict(BASE_CFG)
    cfg["excel_path"] = str(tmp_path / "leads.xlsx")
    cfg["followup_offsets_days"] = [3, 7]
    cfg["followup_enabled"] = True
    cfg["scoring_keywords"] = ["lane"]

    monkeypatch.setattr(web_app, "reply_queue", FakeQueue())
    monkeypatch.setattr(web_app, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(web_app, "save_config", lambda c: cfg.update(c))
    monkeypatch.setattr(web_app, "ExcelStore", lambda *a, **k: FakeStore())
    monkeypatch.setattr(web_app, "sheet_headers", lambda p: ["Name", "Email"])
    monkeypatch.setattr(web_app, "task_status", lambda *a, **k: None)
    monkeypatch.setattr(web_app, "get_anthropic_key", lambda: None)
    monkeypatch.setattr(web_app, "run_checks", lambda cfg: [
        {"name": "X", "status": "ok", "detail": "fine"}])
    monkeypatch.setattr(web_app, "build_mailer", lambda cfg: object())
    monkeypatch.setattr(web_app, "send_cold_batch", lambda *a, **k: {"sent": 1, "errors": []})
    monkeypatch.setattr(web_app, "send_followup_batch", lambda *a, **k: {"sent": 1, "errors": []})
    monkeypatch.setattr(web_app, "send_reminder_batch", lambda *a, **k: {"sent": 1, "errors": []})
    monkeypatch.setattr(web_app, "register_task", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(web_app, "unregister_task", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(web_app, "run_oauth_flow", lambda: "sender@test.com")
    monkeypatch.setattr(web_app, "_run_job", lambda action: None)

    application = web_app.create_app()
    application.config.update(TESTING=True)
    return application.test_client()


GET_ROUTES = ["/", "/leads", "/send", "/replies", "/history", "/diagnostics",
              "/blocklist", "/settings", "/run/status", "/logs/tail"]

POST_ROUTES = [
    ("/leads/2/suppress", {}),
    ("/send/cold", {}),
    ("/send/followups", {}),
    ("/send/reminders", {}),
    ("/run/cold", {}),
    ("/run/nonsense", {}),
    ("/blocklist/domain", {"domain": "x.com"}),
    ("/blocklist/domain/x.com/remove", {}),
    ("/blocklist/email", {"email": "a@x.com"}),
    ("/blocklist/email/a@x.com/remove", {}),
    ("/settings", {"sender_name": "Al"}),
    ("/settings", {"followup_settings": "1", "followup_enabled": "on",
                   "followup_offsets_days": "2, 5, bad, 9"}),
    ("/settings/connect-gmail", {}),
    ("/settings/automation/enable", {}),
    ("/settings/automation/disable", {}),
    ("/settings/replies/enable", {}),
    ("/settings/replies/disable", {}),
]


@pytest.mark.parametrize("route", GET_ROUTES)
def test_get_route_no_5xx(client, route):
    assert client.get(route).status_code < 500


@pytest.mark.parametrize("route,data", POST_ROUTES)
def test_post_route_no_5xx(client, route, data):
    assert client.post(route, data=data, follow_redirects=True).status_code < 500


def test_followup_offsets_parse_ignores_junk(client):
    client.post("/settings", data={"followup_settings": "1", "followup_enabled": "on",
                                   "followup_offsets_days": "2, 5, bad, 9"},
                follow_redirects=True)
    # load_config returns a fresh dict each call; check the shared cfg got updated
    assert web_app.load_config()["followup_offsets_days"] == [2, 5, 9]
