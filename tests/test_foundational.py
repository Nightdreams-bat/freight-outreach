"""Wave 1: config defaults, Anthropic key storage, new Excel columns, new templates."""

import openpyxl
import pytest

from outreach import config, credentials, templates
from outreach.excel_store import LOGICAL_COLUMNS, ExcelStore

NEW_COLUMNS = ["ReplyStatus", "LastReplyAt", "MeetingEventId"]


# --- config defaults -------------------------------------------------------

def test_new_keys_have_defaults():
    for key in (
        "reply_scan_enabled", "llm_model", "meeting_duration_minutes",
        "business_hours", "business_days", "scheduling_window_days",
        "min_notice_hours", "calendar_id", "reply_lookback_days",
    ):
        assert key in config.DEFAULTS


def test_get_falls_back_to_default():
    assert config.get({}, "llm_model") == config.DEFAULTS["llm_model"]
    assert config.get({}, "reply_scan_enabled") is False


def test_get_prefers_config_value():
    assert config.get({"llm_model": "custom"}, "llm_model") == "custom"


def test_get_unknown_key_raises():
    with pytest.raises(KeyError):
        config.get({}, "no_such_key")


# --- Anthropic key storage ----------------------------------------------

class _FakeKeyring:
    def __init__(self):
        self.store = {}

    def set_password(self, service, user, value):
        self.store[(service, user)] = value

    def get_password(self, service, user):
        return self.store.get((service, user))

    def delete_password(self, service, user):
        del self.store[(service, user)]


@pytest.fixture
def fake_keyring(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr(credentials, "_keyring", lambda: fake)
    return fake


def test_anthropic_key_absent_returns_none(fake_keyring):
    assert credentials.get_anthropic_key() is None


def test_anthropic_key_roundtrip(fake_keyring):
    credentials.set_anthropic_key("sk-ant-test")
    assert credentials.get_anthropic_key() == "sk-ant-test"
    credentials.clear_anthropic_key()
    assert credentials.get_anthropic_key() is None


# --- Excel columns -----------------------------------------------------

def test_logical_columns_include_new_ones():
    for col in NEW_COLUMNS:
        assert col in LOGICAL_COLUMNS


def test_fresh_workbook_has_new_columns(tmp_path):
    store = ExcelStore(tmp_path / "fresh.xlsx")
    for col in NEW_COLUMNS:
        assert col in store.col_index


def test_preexisting_workbook_gets_new_columns(tmp_path):
    path = tmp_path / "legacy.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    legacy_headers = [
        "Name", "Company", "Email", "Phone", "MeetingDateTime", "Status",
        "ColdEmailSentAt", "ReminderSentAt", "Suppressed", "Notes",
    ]
    ws.append(legacy_headers)
    ws.append(["Jane", "Acme", "jane@acme.test", "", "", "", "", "", "", ""])
    wb.save(path)

    store = ExcelStore(path)
    for col in NEW_COLUMNS:
        assert col in store.col_index

    reopened = openpyxl.load_workbook(path)
    assert set(NEW_COLUMNS).issubset({c.value for c in reopened.active[1]})


# --- templates -------------------------------------------------------

def test_meeting_confirm_renders():
    out = templates.render(
        templates.MEETING_CONFIRM_BODY,
        name="Jane", company="Acme", sender_name="Al", sender_company="FreightCo",
        sender_phone="555-0100", meeting_time="Monday, Sep 1 at 10:00 AM",
    )
    assert "Jane" in out and "Monday, Sep 1 at 10:00 AM" in out
    assert templates.render(templates.MEETING_CONFIRM_SUBJECT,
                            meeting_time="Monday") == "Confirmed - our call Monday"


def test_propose_times_renders_slot_list():
    out = templates.render(
        templates.PROPOSE_TIMES_BODY,
        name="Jane", company="Acme", sender_name="Al", sender_company="FreightCo",
        sender_phone="", slots=["Mon 10:00 AM", "Tue 2:00 PM", "Wed 9:30 AM"],
    )
    assert "Mon 10:00 AM" in out and "Tue 2:00 PM" in out and "Wed 9:30 AM" in out


def test_decline_ack_renders():
    out = templates.render(
        templates.DECLINE_ACK_BODY,
        name="Jane", company="Acme", sender_name="Al", sender_company="FreightCo",
    )
    assert "Jane" in out and "won't follow up again" in out


def test_all_new_templates_are_valid_jinja():
    dummy = dict(
        name="n", company="c", sender_name="s", sender_company="sc",
        sender_phone="p", meeting_time="m", slots=["a", "b"],
    )
    for tmpl in (
        templates.MEETING_CONFIRM_SUBJECT, templates.MEETING_CONFIRM_BODY,
        templates.PROPOSE_TIMES_SUBJECT, templates.PROPOSE_TIMES_BODY,
        templates.DECLINE_ACK_SUBJECT, templates.DECLINE_ACK_BODY,
    ):
        templates.render(tmpl, **dummy)
