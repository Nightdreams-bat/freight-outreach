"""Wave A: shared retire-a-lead helper (outreach/suppression.py)."""

from datetime import datetime

import pytest

from outreach import suppression
from outreach.excel_store import ExcelFileLocked


class FakeStore:
    def __init__(self, locked=False):
        self.writes = []
        self.locked = locked

    def set_value(self, row_idx, col, value):
        if self.locked:
            raise ExcelFileLocked("clients.xlsx is open in Excel")
        self.writes.append((row_idx, col, value))


@pytest.fixture(autouse=True)
def _capture_history(monkeypatch):
    calls = []
    monkeypatch.setattr(suppression, "record_send_history", lambda *a: calls.append(a))
    return calls


VALUES = {"Email": "bob@deadco.test", "Name": "Bob Vance", "Company": "Dead Co", "Notes": ""}


def test_note_line_without_existing_notes():
    stamp = datetime.now().strftime("%Y-%m-%d")
    assert suppression.note_line("", "hard bounce") == f"[{stamp}] hard bounce"
    assert suppression.note_line(None, "hard bounce") == f"[{stamp}] hard bounce"


def test_note_line_appends_to_existing_notes():
    stamp = datetime.now().strftime("%Y-%m-%d")
    out = suppression.note_line("earlier note", "hard bounce")
    assert out == f"earlier note\n[{stamp}] hard bounce"


def test_retire_lead_sets_suppressed_and_notes_and_history(_capture_history):
    store = FakeStore()
    ok = suppression.retire_lead(store, 4, VALUES, reason="undeliverable: hard bounce")
    assert ok is True
    assert (4, "Suppressed", "yes") in store.writes
    note_write = [w for w in store.writes if w[1] == "Notes"][0]
    assert "undeliverable: hard bounce" in note_write[2]
    assert _capture_history == [
        ("suppressed", "bob@deadco.test", "Bob Vance", "Dead Co", "undeliverable: hard bounce")
    ]


def test_retire_lead_returns_false_and_logs_when_sheet_locked(_capture_history, caplog):
    store = FakeStore(locked=True)
    with caplog.at_level("WARNING"):
        ok = suppression.retire_lead(store, 4, VALUES, reason="hard bounce")
    assert ok is False
    assert _capture_history == []
    assert any("locked" in r.message.lower() for r in caplog.records)
