"""The /leads list and the separate /leads/suppressed page."""

import pytest

from kairo.web import app as web_app
from tests.test_web_replies import BASE_CFG, FakeQueue

ACTIVE = {"Email": "active@acme.test", "Name": "Ava", "Company": "Acme", "Notes": "", "Priority": "3"}
BLOCKED = {"Email": "blocked@bad.test", "Name": "Bo", "Company": "Bad Co", "Notes": "", "Priority": "1"}
SUPPRESSED = {"Email": "hush@quiet.test", "Name": "Sy", "Company": "Quiet", "Notes": "", "Priority": "2"}


class FakeStore:
    email_column_missing = False

    def __init__(self):
        self._rows = {
            2: (dict(ACTIVE), None),
            3: (dict(BLOCKED), "blocked"),
            4: (dict(SUPPRESSED), "suppressed"),
        }

    def all_rows(self):
        return iter([(i, v, r) for i, (v, r) in sorted(self._rows.items())])

    def rows(self):
        return iter([(i, v) for i, (v, r) in sorted(self._rows.items()) if r is None])

    def get_row(self, i):
        v, r = self._rows[i]
        return {**v, "Suppressed": "yes" if r == "suppressed" else ""}

    def set_value(self, i, logical, value):
        if logical == "Suppressed":
            v, _ = self._rows[i]
            self._rows[i] = (v, "suppressed" if value else None)

    def existing_emails(self):
        return {v["Email"].lower() for v, _ in self._rows.values()}

    def add_lead(self, data):
        return 5

    def remove_rows(self, row_idxs):
        removed = 0
        for i in row_idxs:
            if i in self._rows:
                del self._rows[i]
                removed += 1
        return removed


@pytest.fixture
def client(monkeypatch, tmp_path):
    cfg = dict(BASE_CFG)
    cfg["excel_path"] = str(tmp_path / "leads.xlsx")
    cfg["scoring_keywords"] = ["lane"]

    store = FakeStore()
    monkeypatch.setattr(web_app, "reply_queue", FakeQueue())
    monkeypatch.setattr(web_app, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(web_app, "save_config", lambda c: cfg.update(c))
    monkeypatch.setattr(web_app, "ExcelStore", lambda *a, **k: store)

    application = web_app.create_app()
    application.config.update(TESTING=True)
    return application.test_client()


def test_leads_list_hides_suppressed_shows_active_and_blocked(client):
    html = client.get("/leads").get_data(as_text=True)
    assert "active@acme.test" in html
    assert "blocked@bad.test" in html
    assert "hush@quiet.test" not in html


def test_suppressed_page_shows_only_suppressed(client):
    html = client.get("/leads/suppressed").get_data(as_text=True)
    assert "hush@quiet.test" in html
    assert "active@acme.test" not in html


def test_suppressed_count_shown_on_leads(client):
    html = client.get("/leads").get_data(as_text=True)
    assert "Suppressed (1)" in html


def test_suppressed_page_has_delete_and_block_buttons(client):
    html = client.get("/leads/suppressed").get_data(as_text=True)
    assert "/leads/4/delete" in html
    assert "/leads/4/block" in html
    # the main list must not offer destructive actions
    assert "/delete" not in client.get("/leads").get_data(as_text=True)


def test_delete_removes_the_row(client):
    client.post("/leads/4/delete", follow_redirects=True)
    assert "hush@quiet.test" not in client.get("/leads/suppressed").get_data(as_text=True)


def test_block_adds_email_to_blocklist(client):
    r = client.post("/leads/4/block", follow_redirects=True)
    assert "hush@quiet.test" in web_app.load_config()["disallowed_emails"]
    assert b"Blocked" in r.data


def test_toggle_moves_lead_between_pages(client):
    # Suppress the active lead -> it leaves /leads and appears on /leads/suppressed
    client.post("/leads/2/suppress", follow_redirects=True)
    assert "active@acme.test" not in client.get("/leads").get_data(as_text=True)
    assert "active@acme.test" in client.get("/leads/suppressed").get_data(as_text=True)

    # Unsuppress it again -> back on the main list
    client.post("/leads/2/suppress", follow_redirects=True)
    assert "active@acme.test" in client.get("/leads").get_data(as_text=True)
    assert "active@acme.test" not in client.get("/leads/suppressed").get_data(as_text=True)
