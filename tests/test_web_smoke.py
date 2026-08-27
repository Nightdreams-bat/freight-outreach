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

    def existing_emails(self):
        return {"lead@acme.test"}

    def add_lead(self, data):
        return 3


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
    monkeypatch.setattr(web_app.lead_sourcing, "search_businesses",
                        lambda what, where, **k: [{"Name": "", "Company": "Found SRL",
                                                   "Email": "hi@found.test", "Phone": "",
                                                   "Website": "", "Address": "", "Source": "OSM"}])
    monkeypatch.setattr(web_app.lead_sourcing, "enrich", lambda b, **k: b)

    application = web_app.create_app()
    application.config.update(TESTING=True)
    return application.test_client()


GET_ROUTES = ["/", "/leads", "/send", "/replies", "/history", "/diagnostics",
              "/diagnostics/run", "/blocklist", "/settings", "/run/status", "/logs/tail",
              "/activity", "/logs", "/find-leads"]

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
    ("/settings", {"template_language": "ro"}),
    ("/settings/templates/reset", {}),
    ("/find-leads/search", {"what": "transport", "where": "Chisinau", "scrape": "on"}),
    ("/find-leads/import", {"pick": "0"}),
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


def test_followup_offsets_parse_ignores_junk_and_sub_one(client):
    client.post("/settings", data={"followup_settings": "1", "followup_enabled": "on",
                                   "followup_offsets_days": "9, 2, bad, 0, -3, 5"},
                follow_redirects=True)
    # non-numbers and values < 1 dropped; result sorted ascending
    assert web_app.load_config()["followup_offsets_days"] == [2, 5, 9]


def test_relative_time_buckets():
    from datetime import datetime, timedelta

    now = datetime.now()
    fmt = "%Y-%m-%d %H:%M:%S"
    assert web_app._relative_time((now - timedelta(seconds=10)).strftime(fmt)) == "just now"
    assert web_app._relative_time((now - timedelta(minutes=5)).strftime(fmt)) == "5 min ago"
    assert web_app._relative_time((now - timedelta(hours=3)).strftime(fmt)) == "3 h ago"
    assert web_app._relative_time((now - timedelta(days=1, hours=2)).strftime(fmt)) == "yesterday"
    assert web_app._relative_time("garbage") == ""


def test_activity_items_friendly_text(monkeypatch):
    monkeypatch.setattr(web_app, "recent_history", lambda limit=12: [
        {"timestamp": "2026-08-27 10:00:00", "kind": "followup", "email": "o@x.com",
         "name": "Owen Reyes", "company": "Tri-State Haul", "subject": "re: lanes"},
        {"timestamp": "2026-08-27 09:00:00", "kind": "reply", "email": "a@x.com",
         "name": "Ann", "company": "C", "subject": "Pricing?"},
    ])
    items = web_app._activity_items()
    assert items[0]["text"].startswith("Follow-up nudge sent to Owen Reyes")
    assert "Tri-State Haul" in items[0]["text"]
    assert items[0]["icon"] == "nudge"
    assert items[1]["text"].startswith("Reply handled")
    assert "Pricing?" in items[1]["text"]


def test_find_leads_sidebar_link_and_beta_badge(client):
    html = client.get("/find-leads").get_data(as_text=True)
    assert "/find-leads" in html
    assert 'class="beta"' in html


def test_find_leads_search_then_import(client):
    r = client.post("/find-leads/search",
                    data={"what": "transport", "where": "Chisinau", "scrape": "on"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Found SRL" in body
    imp = client.post("/find-leads/import", data={"pick": "0"}, follow_redirects=True)
    assert imp.status_code == 200
    assert "Added 1" in imp.get_data(as_text=True)


def test_cross_origin_post_is_rejected(client):
    r = client.post("/blocklist/domain", data={"domain": "x.com"},
                    headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_cross_origin_referer_post_is_rejected(client):
    r = client.post("/blocklist/domain", data={"domain": "x.com"},
                    headers={"Referer": "http://evil.example/page"})
    assert r.status_code == 403


def test_foreign_host_post_is_rejected(client):
    r = client.post("/blocklist/domain", data={"domain": "x.com"},
                    base_url="http://attacker.test")
    assert r.status_code == 403


def test_same_origin_post_is_allowed(client):
    r = client.post("/blocklist/domain", data={"domain": "x.com"},
                    headers={"Origin": "http://localhost"}, follow_redirects=True)
    assert r.status_code < 400


def test_no_origin_post_is_allowed(client):
    # The desktop WebView / test client sends no Origin - must still work.
    r = client.post("/blocklist/domain", data={"domain": "x.com"}, follow_redirects=True)
    assert r.status_code < 400


def test_get_routes_never_blocked_by_guard(client):
    assert client.get("/leads", headers={"Origin": "http://evil.example"}).status_code < 400


def test_run_job_followups_noop_when_drip_disabled(monkeypatch):
    cfg = dict(BASE_CFG)
    cfg["followup_enabled"] = False
    monkeypatch.setattr(web_app, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(web_app, "ExcelStore", lambda *a, **k: FakeStore())
    sent = []
    monkeypatch.setattr(web_app, "send_followup_batch", lambda *a, **k: sent.append(1) or {"sent": 1, "errors": []})
    web_app._run_job("followups")
    assert sent == []
    assert "off" in web_app._JOB["summary"].lower()
