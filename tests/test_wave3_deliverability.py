"""Wave 3: jittered pacing, reminder catch-up + per-run brake, threaded nudges,
data-lock granularity, sane default send cap."""

import contextlib
from datetime import datetime, timedelta

import pytest

from outreach import config, core, send_reminders

NOW_FMT = "%Y-%m-%d %H:%M:%S"


def _ts(dt):
    return dt.strftime(NOW_FMT)


# --- jittered pacing (P1-2) ------------------------------------------------

def test_send_delay_within_configured_range():
    cfg = {"send_delay_min_seconds": 45, "send_delay_max_seconds": 150,
           "reminder_send_delay_seconds": 5}
    for _ in range(200):
        d = core._send_delay_seconds(cfg, "cold")
        assert 45 <= d <= 150
        assert core._send_delay_seconds(cfg, "followup") <= 150
    assert core._send_delay_seconds(cfg, "reminder") == 5


def test_send_delay_handles_reversed_range():
    cfg = {"send_delay_min_seconds": 150, "send_delay_max_seconds": 45,
           "reminder_send_delay_seconds": 5}
    assert 45 <= core._send_delay_seconds(cfg, "cold") <= 150


def test_send_delay_falls_back_to_defaults_for_bare_cfg():
    # a bare cfg dict (as tests pass around) still resolves via config.DEFAULTS
    d = core._send_delay_seconds({}, "cold")
    assert config.DEFAULTS["send_delay_min_seconds"] <= d <= config.DEFAULTS["send_delay_max_seconds"]


# --- default cap -> 20, migrate never lowers it (P1-3) --------------------

def test_default_cap_is_twenty():
    assert config.default_config()["daily_send_cap"] == 20


def test_migrate_does_not_lower_an_existing_higher_cap(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    path.write_text('{"daily_send_cap": 150, "column_map": {}}', encoding="utf-8")
    cfg = config.load_config()
    assert cfg["daily_send_cap"] == 150  # kept, not clamped to the new default


def test_migrate_backfills_cap_when_absent(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    path.write_text('{"sender_name": "Al"}', encoding="utf-8")
    assert config.load_config()["daily_send_cap"] == 20


# --- reminder catch-up (P1-16) ------------------------------------------

class _Store:
    def __init__(self, rows):
        self._rows = rows

    def rows(self):
        for i, r in enumerate(self._rows, start=2):
            yield i, r


def test_reminder_catch_up_fires_for_meeting_20h_out_with_empty_flag():
    meeting = datetime.now() + timedelta(hours=20)
    store = _Store([{"Email": "a@x.test", "MeetingDateTime": _ts(meeting), "ReminderSentAt": ""}])
    cands = core.reminder_candidates(store, window_hours=2)
    assert [i for i, _, _ in cands] == [2]


def test_reminder_not_sent_twice():
    meeting = datetime.now() + timedelta(hours=20)
    store = _Store([{"Email": "a@x.test", "MeetingDateTime": _ts(meeting),
                     "ReminderSentAt": _ts(datetime.now())}])
    assert core.reminder_candidates(store, window_hours=2) == []


def test_reminder_not_sent_for_past_meeting():
    store = _Store([{"Email": "a@x.test",
                     "MeetingDateTime": _ts(datetime.now() - timedelta(hours=1)),
                     "ReminderSentAt": ""}])
    assert core.reminder_candidates(store, window_hours=2) == []


def test_reminder_not_sent_far_in_future():
    store = _Store([{"Email": "a@x.test",
                     "MeetingDateTime": _ts(datetime.now() + timedelta(days=3)),
                     "ReminderSentAt": ""}])
    assert core.reminder_candidates(store, window_hours=2) == []


# --- per-run brake sends the soonest N, not zero (P1-17) ----------------

def test_per_run_brake_sends_soonest_n_not_zero(monkeypatch, caplog):
    now = datetime.now()
    cands = [
        (i, {"Email": f"l{i}@x.test"}, now + timedelta(hours=1 + i))
        for i in range(5)
    ]
    monkeypatch.setattr(send_reminders, "load_config",
                        lambda: {"excel_path": "x", "reminder_window_hours": 2,
                                 "max_reminders_per_run": 3, "daily_send_cap": 100})
    monkeypatch.setattr(send_reminders, "ExcelStore", lambda *a, **k: object())
    monkeypatch.setattr(send_reminders, "scan_optouts", lambda cfg, store: [])
    monkeypatch.setattr(send_reminders, "reminder_candidates", lambda store, w: list(cands))
    monkeypatch.setattr(send_reminders, "apply_daily_cap",
                        lambda c, cap, sort_key=None: (list(c), cap, 0))
    monkeypatch.setattr(send_reminders, "build_mailer", lambda cfg: object())
    seen = {}
    monkeypatch.setattr(send_reminders, "send_reminder_batch",
                        lambda cfg, store, mailer, c, dry_run=False: seen.update(n=len(c), ids=[x[0] for x in c])
                        or {"sent": len(c), "errors": []})
    monkeypatch.setattr("sys.argv", ["send_reminders.py"])
    send_reminders.main()
    assert seen["n"] == 3
    assert seen["ids"] == [0, 1, 2]  # the three soonest meetings


# --- threaded nudges (P1-1) -------------------------------------------

class _ThreadStore:
    def __init__(self, rows):
        self._rows = list(rows)
        self.writes = {}

    def rows(self):
        for i, r in enumerate(self._rows, start=2):
            yield i, r

    def set_value(self, row_idx, col, value):
        self.writes[(row_idx, col)] = value
        self._rows[row_idx - 2][col] = value

    def mark_sent(self, row_idx, col, when=None):
        self.set_value(row_idx, col, _ts(datetime.now()))


class _RecordingMailer:
    def __init__(self):
        self.calls = []

    def send(self, to, subj, body, **kwargs):
        self.calls.append({"to": to, "subject": subj, "kwargs": kwargs})
        return {"message_id": "<new@x>", "thread_id": "T"}


CFG = {"sender_name": "Al", "sender_company": "Co", "sender_phone": "", "sender_pitch": "",
       "followup_offsets_days": [3, 7], "template_language": "en",
       "cold_subject_template": "{{ company }} freight - quick question",
       "send_failure_abort_threshold": 5}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(core, "record_sent", lambda *a, **k: None)
    monkeypatch.setattr(core, "record_send_history", lambda *a, **k: None)
    monkeypatch.setattr(core.time, "sleep", lambda *_: None)


def test_followup_threads_when_cold_ids_present():
    row = {"Email": "lead@acme.test", "Company": "Acme", "Phone": "",
           "ColdEmailSentAt": _ts(datetime.now() - timedelta(days=5)),
           "ColdMessageId": "<cold@x>", "ColdThreadId": "T123"}
    store = _ThreadStore([row])
    cands = core.followup_candidates(store, CFG, now=datetime.now())
    mailer = _RecordingMailer()
    core.send_followup_batch(CFG, store, mailer, cands)
    call = mailer.calls[0]
    assert call["kwargs"]["in_reply_to"] == "<cold@x>"
    assert call["kwargs"]["references"] == "<cold@x>"
    assert call["kwargs"]["thread_id"] == "T123"
    assert call["subject"].startswith("Re: Acme freight")


def test_followup_not_threaded_without_ids():
    row = {"Email": "lead@acme.test", "Company": "Acme", "Phone": "",
           "ColdEmailSentAt": _ts(datetime.now() - timedelta(days=5))}
    store = _ThreadStore([row])
    cands = core.followup_candidates(store, CFG, now=datetime.now())
    mailer = _RecordingMailer()
    core.send_followup_batch(CFG, store, mailer, cands)
    assert mailer.calls[0]["kwargs"] == {}
    assert not mailer.calls[0]["subject"].startswith("Re:")


def test_cold_send_persists_message_and_thread_ids():
    store = _ThreadStore([{"Email": "lead@acme.test", "Company": "Acme", "Phone": ""}])
    mailer = _RecordingMailer()
    core.send_cold_batch(CFG, store, mailer, [(2, store._rows[0])])
    assert store.writes[(2, "ColdMessageId")] == "<new@x>"
    assert store.writes[(2, "ColdThreadId")] == "T"


# --- data_lock is not held during the network send (item 7) -------------

def test_data_lock_not_held_during_mailer_send(monkeypatch):
    state = {"held": 0, "held_during_send": False, "held_during_write": False}

    @contextlib.contextmanager
    def fake_lock(timeout=60):
        state["held"] += 1
        try:
            yield
        finally:
            state["held"] -= 1

    monkeypatch.setattr(core, "data_lock", fake_lock)

    class Mailer:
        def send(self, *a, **k):
            state["held_during_send"] = state["held"] > 0
            return {"message_id": "<m>", "thread_id": "t"}

    class Store(_ThreadStore):
        def set_value(self, row_idx, col, value):
            state["held_during_write"] = state["held"] > 0
            super().set_value(row_idx, col, value)

        def mark_sent(self, row_idx, col, when=None):
            state["held_during_write"] = state["held"] > 0
            super().mark_sent(row_idx, col, when)

    store = Store([{"Email": "lead@acme.test", "Company": "Acme", "Phone": ""}])
    core.send_cold_batch(CFG, store, Mailer(), [(2, store._rows[0])])
    assert state["held_during_send"] is False
    assert state["held_during_write"] is True
