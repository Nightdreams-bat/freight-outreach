"""The de-wizarded first run: dashboard works with no config, Settings maps columns."""

import pytest

from outreach.web import app as web_app
from tests.test_web_replies import BASE_CFG, FakeQueue


class FakeStore:
    def __init__(self, email_column_missing=False, all_rows=()):
        self.email_column_missing = email_column_missing
        self._all_rows = list(all_rows)

    def all_rows(self):
        return iter(self._all_rows)

    def rows(self):
        return iter([(i, v) for i, v, _ in self._all_rows])


@pytest.fixture
def client(monkeypatch, tmp_path):
    fake = FakeQueue()
    store_state = {"store": FakeStore()}
    cfg = dict(BASE_CFG)
    cfg.pop("column_map", None)
    cfg["excel_path"] = str(tmp_path / "leads.xlsx")

    monkeypatch.setattr(web_app, "reply_queue", fake)
    monkeypatch.setattr(web_app, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(web_app, "save_config", lambda c: cfg.update(c))
    monkeypatch.setattr(web_app, "task_status", lambda *a, **k: None)
    monkeypatch.setattr(web_app, "get_anthropic_key", lambda: None)
    monkeypatch.setattr(web_app, "ExcelStore", lambda *a, **k: store_state["store"])
    monkeypatch.setattr(web_app, "sheet_headers",
                        lambda path: ["Full Name", "Organisation", "E-mail Address", "Mobile"])

    application = web_app.create_app()
    application.config.update(TESTING=True)
    c = application.test_client()
    c.cfg = cfg
    c.store_state = store_state
    return c


def test_dashboard_ok_with_blank_business_details(client):
    client.cfg["sender_name"] = ""
    client.cfg["sender_company"] = ""
    r = client.get("/")
    assert r.status_code == 200
    assert b"Finish setting up" in r.data


def test_dashboard_flags_missing_email_column(client):
    client.store_state["store"] = FakeStore(email_column_missing=True)
    body = client.get("/").data.decode()
    assert "no email column" in body


def test_settings_shows_detected_column_mapping(client):
    body = client.get("/settings").data.decode()
    assert "Lead spreadsheet columns" in body
    assert "Full Name" in body and "Organisation" in body
    assert 'name="col_Name"' in body


def test_settings_saves_column_map_override(client):
    client.post("/settings", data={
        "col_Name": "Organisation",
        "col_Company": "",
        "col_Email": "E-mail Address",
        "col_Phone": "__none__",
    }, follow_redirects=True)
    assert client.cfg["column_map"] == {"Name": "Organisation", "Email": "E-mail Address"}


def test_leads_page_shows_derived_name_and_company(client):
    client.store_state["store"] = FakeStore(all_rows=[
        (2, {"Name": None, "Company": None, "Email": "p.smith@acme-freight.com"}, None),
    ])
    body = client.get("/leads").data.decode()
    assert "Smith" in body
    assert "Acme Freight" in body
    assert "from email" in body


def test_big_settings_form_does_not_wipe_column_map(client):
    client.cfg["column_map"] = {"Name": "Full Name"}
    client.post("/settings", data={**BASE_CFG, "sender_name": "New"}, follow_redirects=True)
    assert client.cfg["column_map"] == {"Name": "Full Name"}
