"""The Templates tab — the Gmail-style message library moved out of Settings."""

import pytest

from kairo import templates
from kairo.web import app as web_app


class _FakeStore:
    email_column_missing = False

    def all_rows(self):
        return iter(())


@pytest.fixture
def client(monkeypatch, tmp_path):
    from kairo.config import default_config

    state = {"cfg": default_config("en")}
    state["cfg"]["excel_path"] = str(tmp_path / "leads.xlsx")

    monkeypatch.setattr(web_app, "load_config", lambda: dict(state["cfg"]))
    monkeypatch.setattr(web_app, "save_config", lambda c: state["cfg"].update(c))
    monkeypatch.setattr(web_app, "reply_queue",
                        type("Q", (), {"pending": staticmethod(lambda: [])})())
    monkeypatch.setattr(web_app, "ExcelStore", lambda *a, **k: _FakeStore())
    monkeypatch.setattr(web_app, "sheet_headers", lambda path: [])
    monkeypatch.setattr(web_app, "task_status", lambda *a, **k: None)
    monkeypatch.setattr(web_app, "get_anthropic_key", lambda: None)

    application = web_app.create_app()
    application.config.update(TESTING=True)
    c = application.test_client()
    c.state = state
    return c


def test_page_lists_every_message_type(client):
    body = client.get("/templates").data.decode()
    for name in ("Cold intro", "Follow-up", "Reminder", "Confirmation",
                 "Propose times", "Decline reply"):
        assert name in body
    # both follow-up bodies are on the page
    assert 'name="followup_body_template"' in body
    assert 'name="followup_breakup_body_template"' in body


def test_open_specific_message(client):
    r = client.get("/templates?m=reminder")
    assert r.status_code == 200
    assert b'data-msg="reminder"' in r.data


def test_unknown_message_falls_back_to_first(client):
    body = client.get("/templates?m=nope").data.decode()
    assert 'data-msg="cold" aria-pressed="true"' in body


def test_save_updates_one_template_only(client):
    before_followup = client.state["cfg"]["followup_body_template"]
    client.post("/templates/save", data={
        "m": "cold",
        "cold_subject_template": "Brand new subject",
        "cold_body_template": "Brand new body {{ name }}",
    }, follow_redirects=False)
    assert client.state["cfg"]["cold_subject_template"] == "Brand new subject"
    assert client.state["cfg"]["cold_body_template"] == "Brand new body {{ name }}"
    # untouched templates are left alone
    assert client.state["cfg"]["followup_body_template"] == before_followup


def test_save_cannot_wipe_unrelated_config(client):
    client.state["cfg"]["column_map"] = {"Name": "Full Name"}
    client.post("/templates/save", data={
        "m": "cold", "cold_subject_template": "x", "cold_body_template": "y",
    })
    assert client.state["cfg"]["column_map"] == {"Name": "Full Name"}


def test_save_hook_snippets(client):
    client.post("/templates/save", data={
        "m": "cold",
        "cold_subject_template": "s", "cold_body_template": "b",
        "hooks": "1",
        "hook_snippets_enabled": "on",
        "hook_snippets_carrier": "line one\n\n  line two  \n",
        "hook_snippets_shipper": "",
    })
    assert client.state["cfg"]["hook_snippets_enabled"] is True
    assert client.state["cfg"]["hook_snippets_carrier"] == ["line one", "line two"]
    assert client.state["cfg"]["hook_snippets_shipper"] == []


def test_preview_renders_sample_data(client):
    r = client.post("/templates/preview", data={
        "subject": "{{ company }} — hello",
        "body": "Hi {{ name }}, from {{ sender_name }}",
    })
    data = r.get_json()
    assert data["subject"] == "Acme Logistics — hello"
    assert "Hi Maria," in data["body"]
    assert "errors" not in data


def test_preview_reports_broken_template_without_500(client):
    r = client.post("/templates/preview", data={"body": "{% if %}oops"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["body"] is None
    assert "body" in data["errors"]


def test_language_switch(client):
    client.state["cfg"]["cold_body_template"] = "my own English copy"
    client.post("/templates/language", data={"m": "cold", "template_language": "ro"})
    assert client.state["cfg"]["template_language"] == "ro"
    # switching language also swaps every template to that language's defaults
    assert client.state["cfg"]["cold_body_template"] == templates.defaults("ro")["cold_body_template"]


def test_reset_restores_defaults(client):
    client.state["cfg"]["cold_body_template"] = "mangled"
    client.post("/templates/reset", data={"m": "cold"})
    assert client.state["cfg"]["cold_body_template"] == templates.defaults("en")["cold_body_template"]


def test_settings_page_no_longer_has_template_editors(client):
    body = client.get("/settings").data.decode()
    assert 'name="cold_body_template"' not in body
    assert "Open Templates" in body
