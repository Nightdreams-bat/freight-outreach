"""The de-wizarded first run: dashboard works with no config, Settings maps columns."""

import json

import pytest

from kairo import google_client
from kairo import paths as kpaths
from kairo.web import app as web_app
from tests.test_web_replies import BASE_CFG, FakeQueue

_INSTALLED_JSON = json.dumps({
    "installed": {
        "client_id": "999-zzz.apps.googleusercontent.com",
        "client_secret": "shh",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
})


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


def test_settings_saves_valid_excel_path(client, tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "sheet_headers", lambda path: ["Name", "Email"])
    target = tmp_path / "my leads.xlsx"
    target.write_bytes(b"x")
    r = client.post("/settings", data={"excel_path": str(target)}, follow_redirects=True)
    assert client.cfg["excel_path"] == str(target)
    assert b"Leads file linked" in r.data


def test_resaving_the_same_path_does_not_recreate_a_deleted_file(client, tmp_path, monkeypatch):
    # The path box is pre-filled with the current path; re-saving Settings after
    # the operator deleted the file must NOT rebuild it (v0.1.3 intent).
    created = []
    monkeypatch.setattr(web_app, "ExcelStore",
                        lambda *a, **k: created.append(a) or client.store_state["store"])
    current = client.cfg["excel_path"]  # tmp_path / "leads.xlsx", never created on disk
    r = client.post("/settings", data={"excel_path": current}, follow_redirects=True)
    assert created == []
    assert b"recreate a deleted leads file" in r.data


def test_settings_creates_file_only_when_path_actually_changes(client, tmp_path, monkeypatch):
    created = []
    monkeypatch.setattr(web_app, "ExcelStore",
                        lambda *a, **k: created.append(a[0]) or client.store_state["store"])
    monkeypatch.setattr(web_app, "sheet_headers", lambda path: [])
    new_path = tmp_path / "brand new.xlsx"
    client.post("/settings", data={"excel_path": str(new_path)}, follow_redirects=True)
    assert created == [str(new_path)]


def test_settings_rejects_bogus_excel_path(client):
    before = client.cfg["excel_path"]
    r = client.post("/settings", data={"excel_path": r"C:\nope\missing\leads.txt"},
                    follow_redirects=True)
    assert client.cfg["excel_path"] == before
    assert b"kept the previous file" in r.data


def test_find_leads_autoimport_toggle_round_trips(client):
    client.post("/settings", data={"find_leads_settings": "1", "find_leads_autoimport": "on"},
                follow_redirects=True)
    assert client.cfg["find_leads_autoimport"] is True
    client.post("/settings", data={"find_leads_settings": "1"}, follow_redirects=True)
    assert client.cfg["find_leads_autoimport"] is False


def test_google_credentials_paste_switches_to_own_project_and_back(client, monkeypatch, tmp_path):
    monkeypatch.setattr(kpaths, "CLIENT_SECRET_PATH", tmp_path / "client_secret.json")
    monkeypatch.setattr(google_client, "load_config", lambda: dict(client.cfg))
    monkeypatch.setattr(google_client, "save_config", lambda c: client.cfg.update(c))
    monkeypatch.setattr(google_client, "delete_oauth_token", lambda a: None)
    monkeypatch.setattr(kpaths, "resource_path", lambda rel: tmp_path / "no-bundled")
    client.cfg["google_client_is_custom"] = False

    r = client.post("/settings/google-credentials",
                    data={"client_secret_json": _INSTALLED_JSON}, follow_redirects=True)
    assert b"your own Google project" in r.data
    assert client.cfg["google_client_is_custom"] is True
    assert client.cfg["gmail_address"] == ""
    body = client.get("/settings").data.decode()
    assert "your own Google project" in body

    client.post("/settings/google-credentials/reset", follow_redirects=True)
    assert client.cfg["google_client_is_custom"] is False
    assert "Using Kairo's shared Google app" in client.get("/settings").data.decode()


def test_google_credentials_web_json_flashes_error(client, monkeypatch, tmp_path):
    monkeypatch.setattr(kpaths, "CLIENT_SECRET_PATH", tmp_path / "client_secret.json")
    monkeypatch.setattr(google_client, "load_config", lambda: dict(client.cfg))
    monkeypatch.setattr(google_client, "save_config", lambda c: client.cfg.update(c))
    r = client.post("/settings/google-credentials",
                    data={"client_secret_json": '{"web": {"client_id": "x"}}'},
                    follow_redirects=True)
    assert b"Desktop app" in r.data
    assert client.cfg.get("google_client_is_custom") in (False, None)


def test_big_settings_form_does_not_wipe_column_map(client):
    client.cfg["column_map"] = {"Name": "Full Name"}
    client.post("/settings", data={**BASE_CFG, "sender_name": "New"}, follow_redirects=True)
    assert client.cfg["column_map"] == {"Name": "Full Name"}
